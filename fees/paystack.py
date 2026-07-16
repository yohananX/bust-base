"""
Paystack integration module.

This module handles Paystack payment gateway operations including:
- Webhook signature verification (security-critical)
- Webhook handling for payment confirmation
- Payment initiation via Paystack API
"""

import hashlib
import hmac
import logging
import uuid
from decimal import Decimal
from datetime import datetime

import requests as http_requests
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db import transaction

from .models import Payment, Invoice

logger = logging.getLogger(__name__)


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """
    Verify Paystack webhook HMAC-SHA256 signature.

    Paystack sends an 'x-paystack-signature' header which is the HMAC-SHA256
    hash of the raw request body, using the secret key as the HMAC key.

    Args:
        payload: Raw request body as bytes
        signature: The signature from the 'x-paystack-signature' header

    Returns:
        True if the signature is valid, False otherwise
    """
    secret_key = settings.PAYSTACK_SECRET_KEY
    expected = hmac.new(
        key=secret_key.encode('utf-8'),
        msg=payload,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@csrf_exempt
@require_POST
def handle_webhook(request):
    """
    Handle Paystack webhook events.

    Verifies the webhook signature, then processes the event.
    Currently handles 'charge.success' events.

    This endpoint is idempotent: processing the same event twice
    will not create duplicate payments or double-count amounts.
    """
    # Verify signature
    signature = request.META.get('HTTP_X_PAYSTACK_SIGNATURE', '')
    if not signature or not verify_webhook_signature(request.body, signature):
        logger.warning('Invalid webhook signature received')
        return JsonResponse({'status': 'invalid signature'}, status=400)

    import json
    try:
        event = json.loads(request.body)
    except json.JSONDecodeError:
        logger.error('Invalid JSON in webhook payload')
        return JsonResponse({'status': 'invalid JSON'}, status=400)

    # Only process charge.success events
    if event.get('event') != 'charge.success':
        return JsonResponse({'status': 'ignored'})

    data = event.get('data', {})
    reference = data.get('reference')
    amount_kobo = data.get('amount')  # Amount in kobo (NGN * 100)
    paid_at = data.get('paid_at')

    if not reference:
        logger.error('Webhook charge.success without reference')
        return JsonResponse({'status': 'missing reference'}, status=400)

    with transaction.atomic():
        # Look up existing payment by reference
        payment = Payment.objects.select_for_update().filter(reference=reference).first()

        if payment:
            if payment.status == Payment.Status.CONFIRMED:
                # Already confirmed — idempotent, do nothing
                logger.info(f'Payment {reference} already confirmed, skipping')
                return JsonResponse({'status': 'already confirmed'})
            # Update existing pending payment to confirmed
            payment.status = Payment.Status.CONFIRMED
            if paid_at:
                try:
                    payment.paid_on = timezone.make_aware(
                        datetime.strptime(paid_at, '%Y-%m-%dT%H:%M:%S.%fZ')
                    )
                except (ValueError, TypeError):
                    payment.paid_on = timezone.now()
            payment.save(update_fields=['status', 'paid_on'])
            logger.info(f'Payment {reference} confirmed (updated)')
            return JsonResponse({'status': 'confirmed'})

        # No existing payment — we need to find the invoice somehow
        # For MVP, we handle this by having the invoice reference in metadata
        metadata = data.get('metadata', {})
        invoice_id = metadata.get('invoice_id')

        if not invoice_id:
            logger.error(f'Webhook charge.success for {reference} without invoice_id in metadata')
            return JsonResponse({'status': 'missing invoice_id'}, status=400)

        try:
            invoice = Invoice.objects.get(pk=invoice_id)
        except Invoice.DoesNotExist:
            logger.error(f'Invoice {invoice_id} not found for reference {reference}')
            return JsonResponse({'status': 'invoice not found'}, status=404)

        # Parse paid_at
        try:
            paid_on = timezone.make_aware(
                datetime.strptime(paid_at, '%Y-%m-%dT%H:%M:%S.%fZ')
            ) if paid_at else timezone.now()
        except (ValueError, TypeError):
            paid_on = timezone.now()

        # Create the payment as CONFIRMED (it's already been charged by Paystack)
        Payment.objects.create(
            school=invoice.school,
            invoice=invoice,
            amount=Decimal(amount_kobo) / Decimal('100') if amount_kobo else invoice.total_amount,
            method=Payment.Method.PAYSTACK,
            reference=reference,
            status=Payment.Status.CONFIRMED,
            paid_on=paid_on,
            recorded_by=None,  # Webhook — no user
        )

        logger.info(f'Payment {reference} created and confirmed via webhook')
        return JsonResponse({'status': 'created'})


def initiate_payment(invoice, parent_email, callback_url, existing_reference=None):
    """
    Initiate a Paystack transaction.

    If existing_reference is provided, reuses it (deduplication).
    Otherwise creates a new PENDING payment row and generates a new reference.

    Args:
        invoice: The Invoice to be paid
        parent_email: Email of the parent making payment
        callback_url: URL to redirect after payment
        existing_reference: Optional reference from a recent PENDING payment

    Returns:
        dict with 'authorization_url' and 'reference', or 'error' key on failure.
    """
    if existing_reference:
        reference = existing_reference
    else:
        reference = f'GH-{invoice.id}-{uuid.uuid4().hex[:8].upper()}'
        # Create PENDING payment row BEFORE calling Paystack
        Payment.objects.create(
            school=invoice.school,
            invoice=invoice,
            amount=invoice.balance,  # Server-side computed, never from client
            method=Payment.Method.PAYSTACK,
            reference=reference,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
            recorded_by=None,
        )

    url = 'https://api.paystack.co/transaction/initialize'
    headers = {
        'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
        'Content-Type': 'application/json',
    }
    payload = {
        'email': parent_email,
        'amount': int(invoice.balance * 100),  # kobo
        'reference': reference,
        'callback_url': callback_url,
        'metadata': {
            'invoice_id': invoice.id,
            'school_id': str(invoice.school_id),
        },
    }

    try:
        resp = http_requests.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get('status'):
            return {
                'authorization_url': data['data']['authorization_url'],
                'reference': reference,
            }
        return {'error': data.get('message', 'Paystack initialization failed')}
    except Exception as e:
        logger.error(f'Paystack API error: {e}')
        return {'error': 'Payment gateway error. Please try again.'}
