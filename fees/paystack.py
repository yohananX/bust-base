"""
Paystack integration module.

This module handles Paystack payment gateway operations including:
- Webhook signature verification (security-critical)
- Webhook handling for payment confirmation and failure recording
- Payment initiation via Paystack API
- Transaction verification via the Paystack verify endpoint
- Fee receipt issuance for confirmed payments
"""

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime
from decimal import Decimal

import requests as http_requests
from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Invoice, Payment

logger = logging.getLogger(__name__)

DEFAULT_API_BASE_URL = 'https://api.paystack.co'


def _paystack_base_url():
    """Return the configured Paystack API base URL (falls back to the default)."""
    return getattr(settings, 'PAYSTACK_BASE_URL', '') or DEFAULT_API_BASE_URL


def _default_currency():
    """Return the configured default currency, falling back to NGN."""
    return getattr(settings, 'DEFAULT_CURRENCY', 'NGN')


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


def _parse_paid_at(paid_at):
    """Parse a Paystack paid_at timestamp, falling back to now on failure."""
    try:
        return (
            timezone.make_aware(datetime.strptime(paid_at, '%Y-%m-%dT%H:%M:%S.%fZ'))
            if paid_at
            else timezone.now()
        )
    except (ValueError, TypeError):
        return timezone.now()


def _resolve_event_school(event):
    """Resolve the tenant school for a webhook event from its payload."""
    data = event.get('data') or {}
    metadata = data.get('metadata') or {}
    school_id = metadata.get('school_id')
    if school_id:
        from core.models import School
        school = School.objects.filter(pk=school_id).first()
        if school:
            return school
    reference = data.get('reference')
    if reference:
        payment = Payment.objects.filter(reference=reference).first()
        if payment:
            return payment.school
    invoice_id = metadata.get('invoice_id')
    if invoice_id:
        invoice = Invoice.objects.filter(pk=invoice_id).first()
        if invoice:
            return invoice.school
    return None


def _create_webhook_log(event_name, event, ip_address):
    """
    Persist a WebhookLog row for a received event.

    Returns the log row, or None when no tenant school could be resolved.
    """
    from .models import WebhookLog
    school = _resolve_event_school(event)
    if school is None:
        logger.warning('Could not resolve school for webhook event, skipping WebhookLog')
        return None
    return WebhookLog.objects.create(
        school=school,
        event=(event_name or '')[:50],
        payload=event,
        ip_address=ip_address,
        processed=False,
    )


def _mark_webhook_log_processed(webhook_log):
    """Mark a WebhookLog row as processed (no-op when the row is None)."""
    if webhook_log is not None and not webhook_log.processed:
        webhook_log.processed = True
        webhook_log.save(update_fields=['processed'])


def issue_receipt(payment):
    """
    Issue a fee receipt for a confirmed payment. Idempotent.

    Returns the FeeReceipt instance (existing one if already issued).
    """
    from .models import FeeReceipt
    receipt, created = FeeReceipt.objects.get_or_create(
        payment=payment,
        defaults={
            'school': payment.school,
            'receipt_number': f'RCP-{timezone.now().year}-{payment.pk:06d}',
        },
    )
    return receipt


def _handle_charge_success(event, data, webhook_log):
    """Process a charge.success webhook event (idempotent, tamper-checked)."""
    reference = data.get('reference')
    amount_kobo = data.get('amount')  # Amount in kobo (currency * 100)
    paid_at = data.get('paid_at')

    if not reference:
        logger.error('Webhook charge.success without reference')
        return JsonResponse({'status': 'missing reference'}, status=400)

    payment = Payment.objects.select_for_update().filter(reference=reference).first()

    if payment:
        if payment.status == Payment.Status.CONFIRMED and payment.webhook_processed:
            # Already confirmed — idempotent, do nothing
            logger.info(f'Payment {reference} already confirmed, skipping')
            _mark_webhook_log_processed(webhook_log)
            return JsonResponse({'status': 'already confirmed'})

        # TAMPER CHECK: amount in the webhook must match what we sent to Paystack
        if payment.amount is not None and int(payment.amount * 100) != amount_kobo:
            payment.status = Payment.Status.FAILED
            payment.webhook_processed = True
            payment.webhook_payload = event
            payment.save(update_fields=['status', 'webhook_processed', 'webhook_payload'])
            logger.warning(
                f'Amount mismatch for payment {reference}: '
                f'expected {payment.amount} but webhook reports {amount_kobo} kobo'
            )
            _mark_webhook_log_processed(webhook_log)
            return JsonResponse({'status': 'amount mismatch'})

        # Amount matches — confirm the existing payment row
        payment.status = Payment.Status.CONFIRMED
        payment.paid_on = _parse_paid_at(paid_at)
        payment.webhook_processed = True
        payment.webhook_payload = event
        payment.verified_at = timezone.now()
        payment.currency = data.get('currency') or _default_currency()
        payment.fees_charged = Decimal(str(data.get('fees') or 0)) / Decimal('100')
        authorization = data.get('authorization') or {}
        payment.channel = authorization.get('channel', '')
        payment.card_last4 = str(authorization.get('last4') or '')
        payment.card_brand = authorization.get('card_type', '')
        payment.bank_name = authorization.get('bank', '')
        customer = data.get('customer') or {}
        payment.paid_by_email = customer.get('email', '')
        payment.paid_by_name = (
            (customer.get('first_name') or '') + ' ' + (customer.get('last_name') or '')
        ).strip()
        payment.paid_by_phone = str(customer.get('phone') or '')
        payment.save(update_fields=[
            'status', 'paid_on', 'webhook_processed', 'webhook_payload',
            'verified_at', 'currency', 'fees_charged', 'channel',
            'card_last4', 'card_brand', 'bank_name', 'paid_by_email',
            'paid_by_name', 'paid_by_phone',
        ])
        issue_receipt(payment)
        _mark_webhook_log_processed(webhook_log)
        logger.info(f'Payment {reference} confirmed (updated)')
        return JsonResponse({'status': 'confirmed'})

    # No existing payment row — webhook-first fallback
    metadata = data.get('metadata', {})
    invoice_id = metadata.get('invoice_id')

    if not invoice_id:
        logger.error(f'Webhook charge.success for {reference} without invoice_id in metadata')
        return JsonResponse({'status': 'missing invoice_id'}, status=400)

    if not amount_kobo or amount_kobo <= 0:
        logger.error(f'Webhook charge.success for {reference} with invalid amount')
        return JsonResponse({'status': 'invalid amount'}, status=400)

    try:
        invoice = Invoice.objects.get(pk=invoice_id)
    except Invoice.DoesNotExist:
        logger.error(f'Invoice {invoice_id} not found for reference {reference}')
        return JsonResponse({'status': 'invoice not found'}, status=404)

    authorization = data.get('authorization') or {}
    customer = data.get('customer') or {}

    # Create the payment as CONFIRMED (it's already been charged by Paystack)
    payment = Payment.objects.create(
        school=invoice.school,
        invoice=invoice,
        amount=Decimal(amount_kobo) / Decimal('100'),
        method=Payment.Method.PAYSTACK,
        reference=reference,
        status=Payment.Status.CONFIRMED,
        paid_on=_parse_paid_at(paid_at),
        recorded_by=None,  # Webhook — no user
        webhook_processed=True,
        webhook_payload=event,
        verified_at=timezone.now(),
        currency=data.get('currency') or _default_currency(),
        fees_charged=Decimal(str(data.get('fees') or 0)) / Decimal('100'),
        channel=authorization.get('channel', ''),
        card_last4=str(authorization.get('last4') or ''),
        card_brand=authorization.get('card_type', ''),
        bank_name=authorization.get('bank', ''),
        paid_by_email=customer.get('email', ''),
        paid_by_name=(
            (customer.get('first_name') or '') + ' ' + (customer.get('last_name') or '')
        ).strip(),
        paid_by_phone=str(customer.get('phone') or ''),
    )
    issue_receipt(payment)
    _mark_webhook_log_processed(webhook_log)
    logger.info(f'Payment {reference} created and confirmed via webhook')
    return JsonResponse({'status': 'created'})


def _handle_charge_failure(event_name, event, data, webhook_log):
    """Process a charge failure webhook event (charge.failed, charge.error, ...)."""
    reference = data.get('reference')
    if not reference:
        logger.error(f'Webhook {event_name} without reference')
        return JsonResponse({'status': 'missing reference'}, status=400)

    payment = Payment.objects.select_for_update().filter(reference=reference).first()
    if payment and payment.status == Payment.Status.PENDING:
        payment.status = Payment.Status.FAILED
        payment.webhook_processed = True
        payment.webhook_payload = event
        payment.save(update_fields=['status', 'webhook_processed', 'webhook_payload'])
        _mark_webhook_log_processed(webhook_log)
        logger.info(f'Payment {reference} recorded as failed via {event_name}')
        return JsonResponse({'status': 'recorded'})

    return JsonResponse({'status': 'ignored'})


@csrf_exempt
@require_POST
def handle_webhook(request):
    """
    Handle Paystack webhook events.

    Verifies the webhook signature, logs every event, then processes it.
    Handles 'charge.success' (confirmation with tamper check), charge
    failures, and ignores unknown events.

    This endpoint is idempotent: processing the same event twice
    will not create duplicate payments or double-count amounts.
    """
    # Verify signature
    signature = request.META.get('HTTP_X_PAYSTACK_SIGNATURE', '')
    if not signature or not verify_webhook_signature(request.body, signature):
        logger.warning('Invalid webhook signature received')
        return JsonResponse({'status': 'invalid signature'}, status=400)

    try:
        event = json.loads(request.body)
    except json.JSONDecodeError:
        logger.error('Invalid JSON in webhook payload')
        return JsonResponse({'status': 'invalid JSON'}, status=400)

    event_name = event.get('event')
    data = event.get('data') or {}

    with transaction.atomic():
        # Log every event before dispatch (unhandled events are logged too)
        webhook_log = _create_webhook_log(
            event_name, event, request.META.get('REMOTE_ADDR')
        )

        if event_name == 'charge.success':
            return _handle_charge_success(event, data, webhook_log)

        if event_name is not None and event_name.startswith('charge.'):
            return _handle_charge_failure(event_name, event, data, webhook_log)

        logger.info(f'Ignoring unhandled webhook event: {event_name}')
        return JsonResponse({'status': 'ignored'})


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
        payment = Payment.objects.filter(reference=existing_reference).first()
    else:
        reference = f'GH-{invoice.id}-{uuid.uuid4().hex[:8].upper()}'
        # Create PENDING payment row BEFORE calling Paystack
        payment = Payment.objects.create(
            school=invoice.school,
            invoice=invoice,
            amount=invoice.balance,  # Server-side computed, never from client
            method=Payment.Method.PAYSTACK,
            reference=reference,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
            initiated_at=timezone.now(),
            recorded_by=None,
        )

    url = f'{_paystack_base_url()}/transaction/initialize'
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
            'custom_fields': [
                {
                    'display_name': 'Invoice',
                    'variable_name': 'invoice',
                    'value': str(invoice.id),
                },
            ],
        },
    }

    try:
        resp = http_requests.post(url, json=payload, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get('status'):
            # Persist the Paystack session details onto the payment row
            if payment is not None:
                Payment.objects.filter(pk=payment.pk).update(
                    authorization_url=data['data'].get('authorization_url', ''),
                    access_code=data['data'].get('access_code', ''),
                    initiated_at=timezone.now(),
                )
            return {
                'authorization_url': data['data']['authorization_url'],
                'reference': reference,
            }
        return {'error': data.get('message', 'Paystack initialization failed')}
    except Exception as e:
        logger.error(f'Paystack API error: {e}')
        return {'error': 'Payment gateway error. Please try again.'}


def verify_transaction(reference):
    """
    Verify a Paystack transaction by its reference.

    Args:
        reference: The Paystack transaction reference

    Returns:
        The full Paystack response dict on success, or {'error': ...} on failure.
    """
    url = f'{_paystack_base_url()}/transaction/verify/{reference}'
    headers = {
        'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}',
        'Content-Type': 'application/json',
    }
    try:
        resp = http_requests.get(url, headers=headers, timeout=15)
        data = resp.json()
        if resp.status_code != 200 or not data.get('status'):
            return {'error': data.get('message', 'Verification failed')}
        return data
    except Exception as e:
        logger.error(f'Paystack verification error: {e}')
        return {'error': 'Payment gateway error. Please try again.'}
