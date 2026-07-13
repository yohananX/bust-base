import json
from decimal import Decimal
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.conf import settings
from django.db import transaction

from .models import Invoice, Payment
from .paystack import initiate_payment as paystack_initiate, handle_webhook as paystack_webhook


@login_required
@require_GET
def invoice_detail(request, invoice_id):
    """Return invoice details as JSON. Students see own invoices, parents see linked children's."""
    invoice = get_object_or_404(Invoice, pk=invoice_id)

    # Permission check
    user = request.user
    if user.role == 'STUDENT':
        if invoice.student.user != user:
            return JsonResponse({'error': 'Forbidden'}, status=403)
    elif user.role == 'PARENT':
        if not invoice.student.guardian_links.filter(guardian=user).exists():
            return JsonResponse({'error': 'Forbidden'}, status=403)
    elif user.role != 'ADMIN':
        return JsonResponse({'error': 'Forbidden'}, status=403)

    line_items = invoice.line_items.all().values('category__name', 'amount')
    payments = invoice.payments.all().values('amount', 'method', 'status', 'paid_on', 'reference')

    return JsonResponse({
        'id': invoice.id,
        'student': str(invoice.student),
        'term': str(invoice.term),
        'total_amount': str(invoice.total_amount),
        'amount_paid': str(invoice.amount_paid),
        'balance': str(invoice.balance),
        'status': invoice.status,
        'generated_on': invoice.generated_on.isoformat(),
        'line_items': list(line_items),
        'payments': list(payments),
    })


@login_required
@require_POST
def make_payment(request, invoice_id):
    """Initiate a Paystack payment for an invoice."""
    invoice = get_object_or_404(Invoice, pk=invoice_id)

    user = request.user
    if user.role == 'STUDENT':
        if invoice.student.user != user:
            return JsonResponse({'error': 'Forbidden'}, status=403)
    elif user.role == 'PARENT':
        if not invoice.student.guardian_links.filter(guardian=user).exists():
            return JsonResponse({'error': 'Forbidden'}, status=403)
    elif user.role != 'ADMIN':
        return JsonResponse({'error': 'Forbidden'}, status=403)

    if invoice.balance <= 0:
        return JsonResponse({'error': 'Invoice already paid'}, status=400)

    data = json.loads(request.body)
    parent_email = data.get('email', user.email)
    callback_url = data.get('callback_url', f'{request.build_absolute_uri("/fees/payment/callback/")}')

    result = paystack_initiate(invoice, parent_email, callback_url)
    return JsonResponse(result)


@require_POST
def record_cash_payment(request, invoice_id):
    """Record a cash payment (admin only)."""
    from accounts.mixins import Roles
    if request.user.role != Roles.ADMIN:
        return JsonResponse({'error': 'Forbidden'}, status=403)

    invoice = get_object_or_404(Invoice, pk=invoice_id)
    data = json.loads(request.body)
    amount = Decimal(str(data.get('amount', 0)))

    if amount <= 0:
        return JsonResponse({'error': 'Amount must be positive'}, status=400)

    payment = Payment.objects.create(
        school=invoice.school,
        invoice=invoice,
        amount=amount,
        method=Payment.Method.CASH,
        reference=data.get('reference', ''),
        status=Payment.Status.CONFIRMED,
        paid_on=timezone.now(),
        recorded_by=request.user,
    )

    return JsonResponse({
        'id': payment.id,
        'amount': str(payment.amount),
        'status': payment.status,
        'new_balance': str(invoice.balance),
    })
