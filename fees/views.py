import json
from datetime import timedelta
from decimal import Decimal
from django.shortcuts import get_object_or_404, render, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from django.conf import settings
from django.db import transaction
from django.views.generic.base import View

from .models import Invoice, Payment
from .paystack import initiate_payment as paystack_initiate, handle_webhook as paystack_webhook
from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles


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


@login_required
@require_GET
def invoice_status_partial(request, invoice_id):
    """Return an HTML snippet with the current invoice status for htmx polling.

    Used by the parent portal to show live invoice status updates.
    """
    from django.http import HttpResponseForbidden
    from django.shortcuts import render, get_object_or_404
    from .models import Invoice

    invoice = get_object_or_404(Invoice, pk=invoice_id)
    user = request.user

    # Permission check — same pattern as invoice_detail
    if user.role == 'STUDENT':
        if invoice.student.user != user:
            return HttpResponseForbidden()
    elif user.role == 'PARENT':
        if not invoice.student.guardian_links.filter(guardian=user).exists():
            return HttpResponseForbidden()
    elif user.role != 'ADMIN':
        return HttpResponseForbidden()

    return render(request, 'fees/partials/invoice_status.html', {
        'invoice': invoice,
    })


class InitiatePaymentView(RoleRequiredMixin, View):
    """Parent/student clicks 'Pay' — creates PENDING payment and redirects to Paystack."""
    allowed_roles = [Roles.PARENT, Roles.STUDENT]

    def get(self, request, invoice_id):
        invoice = get_object_or_404(Invoice, pk=invoice_id, school=request.school)

        # Guardian scope check
        if request.user.role == Roles.PARENT:
            if not invoice.student.guardian_links.filter(guardian=request.user).exists():
                messages.error(request, 'You are not authorized to pay this invoice.')
                return redirect('parent-children')
        elif request.user.role == Roles.STUDENT:
            if invoice.student.user != request.user:
                messages.error(request, 'You are not authorized to pay this invoice.')
                return redirect('student-overview')

        if invoice.balance <= 0:
            messages.info(request, 'This invoice is already fully paid.')
            if request.user.role == Roles.PARENT:
                return redirect('parent-child-detail', pk=invoice.student.pk)
            return redirect('student-overview')

        # Deduplication: reuse existing PENDING payment from last 30 minutes
        cutoff = timezone.now() - timedelta(minutes=30)
        existing = Payment.objects.filter(
            invoice=invoice,
            method=Payment.Method.PAYSTACK,
            status=Payment.Status.PENDING,
            paid_on__gte=cutoff,
        ).first()

        # Call Paystack
        callback_url = request.build_absolute_uri(
            reverse('fees:payment-return') + f'?invoice_id={invoice.id}'
        )
        result = paystack_initiate(
            invoice, request.user.email, callback_url,
            existing_reference=existing.reference if existing else None,
        )

        if 'error' in result:
            messages.error(request, result['error'])
            if request.user.role == Roles.PARENT:
                return redirect('parent-child-detail', pk=invoice.student.pk)
            return redirect('student-overview')

        return redirect(result['authorization_url'])


class PaymentReturnView(RoleRequiredMixin, View):
    """Return page after Paystack redirect. Shows waiting state, polls via htmx."""
    allowed_roles = [Roles.PARENT, Roles.STUDENT]

    def get(self, request):
        invoice_id = request.GET.get('invoice_id')
        reference = request.GET.get('reference')

        if not invoice_id:
            messages.error(request, 'Invalid payment return.')
            return redirect('/')

        invoice = get_object_or_404(Invoice, pk=invoice_id, school=request.school)

        # Guardian scope check
        if request.user.role == Roles.PARENT:
            if not invoice.student.guardian_links.filter(guardian=request.user).exists():
                return redirect('parent-children')

        payment = None
        if reference:
            payment = Payment.objects.filter(reference=reference, invoice=invoice).first()

        return render(request, 'fees/payment_return.html', {
            'invoice': invoice,
            'payment': payment,
            'reference': reference,
        })


class PaymentStatusPartialView(RoleRequiredMixin, View):
    """Lightweight status check for htmx polling on the return page."""
    allowed_roles = [Roles.PARENT, Roles.STUDENT]

    def get(self, request):
        reference = request.GET.get('reference')
        invoice_id = request.GET.get('invoice_id')

        if not reference or not invoice_id:
            return HttpResponse('<span class="text-gray-500">Invalid request.</span>')

        invoice = get_object_or_404(Invoice, pk=invoice_id)
        payment = Payment.objects.filter(reference=reference, invoice=invoice).first()

        if not payment:
            return HttpResponse('<span class="text-gray-500">Payment not found.</span>')

        return render(request, 'fees/partials/payment_status.html', {
            'payment': payment,
            'invoice': invoice,
            'reference': reference,
        })


class PaymentTimeoutHelpView(RoleRequiredMixin, View):
    """Shows a help message after payment processing takes too long."""
    allowed_roles = [Roles.PARENT, Roles.STUDENT]

    def get(self, request):
        return HttpResponse(
            '<p class="text-amber-600 text-sm mt-4">Still processing? '
            'If this persists, contact the school office.</p>'
        )
