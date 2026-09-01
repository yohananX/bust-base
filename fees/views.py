import json
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from django.shortcuts import get_object_or_404, render, redirect
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import transaction
from django.views.generic.base import View

from .checkout import reconcile_checkout, current_term, get_selected_items
from .models import Invoice, Payment, PaymentLineItem
from .paystack import initiate_payment as paystack_initiate
from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from students.models import Student, StudentGuardianLink

# process-local guard so the htmx poll hits Paystack's verify endpoint at most
# once per payment instead of every 2 seconds.
_verify_attempted_ids = set()


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


@login_required
@require_GET
def invoice_status_partial(request, invoice_id):
    """Return an HTML snippet with the current invoice status for htmx polling.

    Used by the parent portal to show live invoice status updates.
    """
    from django.http import HttpResponseForbidden
    from django.shortcuts import render, get_object_or_404
    from .models import Invoice

    invoice = get_object_or_404(Invoice, pk=invoice_id, school=request.school)
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
    """Parent/student clicks 'Pay' — creates PENDING payment and redirects to Paystack.

    Supports flexible payment initiation:
    - By invoice:  GET /fees/pay/<invoice_id>/ (legacy links, no amount = full balance)
                   or POST/GET with invoice_id in the query string / form body.
    - Free-form:   invoice_id absent → student_id required, amount required (> 0).
    Params (query string or form body): invoice_id, student_id, amount, description.
    """
    allowed_roles = [Roles.PARENT, Roles.STUDENT]

    def _params(self, request):
        """Params come from the form body on POST, the query string on GET."""
        return request.POST if request.method == 'POST' else request.GET

    def _back_url(self, request):
        """Page to return to on error — the pay page for the caller's portal."""
        return 'parent-pay' if request.user.role == Roles.PARENT else 'student-pay'

    def get(self, request, invoice_id=None):
        return self._initiate(request, invoice_id)

    def post(self, request, invoice_id=None):
        return self._initiate(request, invoice_id)

    def _initiate(self, request, invoice_id):
        role = request.user.role
        back_url = self._back_url(request)
        params = self._params(request)

        # invoice_id may arrive via the path kwarg, query string or form body
        if invoice_id is None:
            raw_invoice_id = params.get('invoice_id')
            try:
                invoice_id = int(raw_invoice_id) if raw_invoice_id else None
            except (TypeError, ValueError):
                invoice_id = None

        invoice = None
        student = None

        if invoice_id is not None:
            invoice = get_object_or_404(Invoice, pk=invoice_id, school=request.school)

            # Guardian scope check
            if role == Roles.PARENT:
                if not invoice.student.guardian_links.filter(guardian=request.user).exists():
                    messages.error(request, 'You are not authorized to pay this invoice.')
                    return redirect(back_url)
            elif role == Roles.STUDENT:
                if invoice.student.user != request.user:
                    messages.error(request, 'You are not authorized to pay this invoice.')
                    return redirect(back_url)

            if invoice.balance <= 0:
                messages.info(request, 'This invoice is already fully paid.')
                return redirect(back_url)

            student = invoice.student
            amount = invoice.balance  # default: full balance
            if params.get('amount'):
                try:
                    amount = Decimal(str(params['amount']))
                except (InvalidOperation, TypeError, ValueError):
                    messages.error(request, 'Enter a valid payment amount.')
                    return redirect(back_url)
                if amount <= 0 or amount > invoice.balance:
                    messages.error(
                        request,
                        f'Amount must be greater than 0 and at most '
                        f'{invoice.balance:,.2f}.',
                    )
                    return redirect(back_url)
        else:
            # Free-form payment — student_id required, amount required (> 0)
            raw_student_id = params.get('student_id')
            if not raw_student_id:
                messages.error(request, 'Select a student or an invoice to pay for.')
                return redirect(back_url)
            try:
                student_id = int(raw_student_id)
            except (TypeError, ValueError):
                messages.error(request, 'Invalid student selected.')
                return redirect(back_url)

            student = get_object_or_404(Student, pk=student_id, school=request.school)

            if role == Roles.PARENT:
                if not StudentGuardianLink.objects.filter(
                    guardian=request.user, student=student,
                ).exists():
                    messages.error(request, 'You are not authorized to pay for this student.')
                    return redirect(back_url)
            elif role == Roles.STUDENT:
                if student.user != request.user:
                    messages.error(request, 'You are not authorized to pay for this student.')
                    return redirect(back_url)

            try:
                amount = Decimal(str(params.get('amount') or '0'))
            except (InvalidOperation, TypeError, ValueError):
                amount = Decimal('0')
            if amount <= 0:
                messages.error(request, 'Enter an amount greater than 0.')
                return redirect(back_url)

        description = (params.get('description') or '').strip()

        # Deduplication: reuse a recent PENDING Paystack payment for the same
        # invoice (or same student when invoice-less) from the last 30 minutes
        # — but only when the amount matches.
        cutoff = timezone.now() - timedelta(minutes=30)
        existing_qs = Payment.objects.filter(
            method=Payment.Method.PAYSTACK,
            status=Payment.Status.PENDING,
            paid_on__gte=cutoff,
        )
        if invoice_id is not None:
            existing_qs = existing_qs.filter(invoice=invoice)
        else:
            existing_qs = existing_qs.filter(invoice__isnull=True, student=student)
        existing = existing_qs.first()
        if existing is not None and existing.amount != amount:
            existing = None

        # Call Paystack. The callback URL points at the pay page — Paystack
        # appends ?reference=XXX automatically.
        callback_url = request.build_absolute_uri(reverse(back_url))
        result = paystack_initiate(
            invoice if invoice_id is not None else None,
            request.user.email,
            callback_url,
            existing_reference=existing.reference if existing else None,
            amount=amount,
            description=description,
            student=None if invoice_id is not None else student,
        )

        if 'error' in result:
            messages.error(request, result['error'])
            return redirect(back_url)

        return redirect(result['authorization_url'])


class CheckoutSubmitView(RoleRequiredMixin, View):
    """Handles the checkout form POST on the parent/student pay pages.

    Serves both portals. Reconciles the submitted selections against the
    checkout cart, then either records BANK_TRANSFER payments as PENDING or
    initiates a Paystack charge. A split checkout (current + next term)
    registers both payments up front so the return page can offer to continue
    the sibling after the first clears.
    """
    allowed_roles = [Roles.PARENT, Roles.STUDENT]

    def post(self, request):
        back_url = 'parent-pay' if request.user.role == Roles.PARENT else 'student-pay'
        role = request.user.role

        raw_student_id = request.POST.get('student_id')
        if not raw_student_id:
            messages.error(request, 'Select a student or an invoice to pay for.')
            return redirect(back_url)
        try:
            student_id = int(raw_student_id)
        except (TypeError, ValueError):
            messages.error(request, 'Invalid student selected.')
            return redirect(back_url)

        student = get_object_or_404(Student, pk=student_id, school=request.school)

        if role == Roles.PARENT:
            if not StudentGuardianLink.objects.filter(
                guardian=request.user, student=student,
            ).exists():
                messages.error(request, 'You are not authorized to pay for this student.')
                return redirect(back_url)
        elif role == Roles.STUDENT:
            if student.user != request.user:
                messages.error(request, 'You are not authorized to pay for this student.')
                return redirect(back_url)

        term = current_term(request.school)
        if term is None:
            messages.error(request, 'No active term yet.')
            return redirect(back_url)

        try:
            amount = Decimal(str(request.POST.get('amount') or '0'))
        except (InvalidOperation, TypeError, ValueError):
            messages.error(request, 'Enter a valid payment amount.')
            return redirect(back_url)
        if amount <= 0:
            messages.error(request, 'Enter an amount greater than 0.')
            return redirect(back_url)

        selected_keys = request.POST.getlist('item')

        try:
            result = reconcile_checkout(student, term, selected_keys, amount)
        except ValidationError as e:
            messages.error(request, str(e))
            return redirect(back_url)

        method = request.POST.get('method', 'paystack')
        if method == 'bank_transfer':
            proof = request.FILES.get('proof_image')
            if proof is None:
                messages.error(
                    request,
                    'Upload a screenshot of your transfer before submitting.',
                )
                return redirect(back_url)

            from fees.validators import validate_proof_file
            try:
                validate_proof_file(proof)
            except ValidationError as e:
                messages.error(request, str(e))
                return redirect(back_url)

            paid_by_name = request.POST.get('paid_by_name', '').strip()
            paid_by_relation = request.POST.get('paid_by_relation', '').strip()

            with transaction.atomic():
                payments = []
                for alloc in result.allocations:
                    payment = Payment.objects.create(
                        school=student.school,
                        invoice=alloc.invoice,
                        student=student,
                        amount=alloc.amount,
                        method=Payment.Method.BANK_TRANSFER,
                        reference=None,
                        status=Payment.Status.PENDING,
                        paid_on=timezone.now(),
                        recorded_by=None,
                        description='Fee checkout',
                        proof_image=proof,
                        paid_by_name=paid_by_name,
                        paid_by_relation=paid_by_relation,
                    )
                    payments.append(payment)
                selected_items = get_selected_items(student, term, selected_keys)
                self._create_payment_line_items(payments, selected_items)
            from notifications.utils import notify_admins
            notify_admins(
                school=student.school,
                subject=f'Bank transfer of ₦{amount:,.2f} awaiting approval',
                message=(
                    f'{student} submitted a bank transfer of ₦{amount:,.2f} '
                    f'({"split across " + str(len(result.allocations)) + " invoices" if result.is_split else "pending your confirmation"}).'
                ),
                reference=f'transfer-pending:{student.pk}:{timezone.now():%Y%m%d%H%M%S}',
                url=reverse('school_admin:pending_transfers'),
                action_label='Review',
            )
            if result.is_split:
                messages.success(
                    request,
                    '2 payments will be recorded — one for this term, '
                    'one for next term. Pending confirmation.',
                )
            else:
                messages.success(
                    request,
                    f'Payment of ₦{amount} submitted for confirmation.',
                )
            return redirect(back_url)

        # Paystack branch — the callback URL points at the pay page, which
        # appends ?reference= automatically.
        callback_url = request.build_absolute_uri(reverse(back_url))

        if result.is_split:
            first_alloc, second_alloc = result.allocations
            with transaction.atomic():
                first_payment = Payment.objects.create(
                    school=student.school,
                    invoice=first_alloc.invoice,
                    student=student,
                    amount=first_alloc.amount,
                    method=Payment.Method.PAYSTACK,
                    reference=f'GH-{first_alloc.invoice.id}-{uuid.uuid4().hex[:8].upper()}',
                    status=Payment.Status.PENDING,
                    paid_on=timezone.now(),
                    recorded_by=None,
                    description='Fee checkout',
                )
                Payment.objects.create(
                    school=student.school,
                    invoice=second_alloc.invoice,
                    student=student,
                    amount=second_alloc.amount,
                    method=Payment.Method.PAYSTACK,
                    reference=f'GH-{second_alloc.invoice.id}-{uuid.uuid4().hex[:8].upper()}',
                    status=Payment.Status.PENDING,
                    paid_on=timezone.now(),
                    recorded_by=None,
                    description='Fee checkout',
                )
                selected_items = get_selected_items(student, term, selected_keys)
                self._create_payment_line_items(
                    [first_payment, second_payment], selected_items,
                )

            # Reuse the first row's reference so Paystack refreshes it with an
            # authorization URL; the second row stays PENDING without one for
            # the sibling-continue flow on the return page.
            result_first = paystack_initiate(
                first_alloc.invoice,
                request.user.email,
                callback_url,
                existing_reference=first_payment.reference,
                amount=first_alloc.amount,
                student=student,
                description='Fee checkout',
            )
            if 'error' in result_first:
                messages.error(request, result_first['error'])
                return redirect(back_url)
            return redirect(result_first['authorization_url'])

        # Single invoice — same dedup flow as InitiatePaymentView.
        alloc = result.allocations[0]
        cutoff = timezone.now() - timedelta(minutes=30)
        existing = Payment.objects.filter(
            method=Payment.Method.PAYSTACK,
            status=Payment.Status.PENDING,
            paid_on__gte=cutoff,
            invoice=alloc.invoice,
        ).first()
        if existing is not None and existing.amount != alloc.amount:
            existing = None

        result_init = paystack_initiate(
            alloc.invoice,
            request.user.email,
            callback_url,
            existing_reference=existing.reference if existing else None,
            amount=alloc.amount,
            description='Fee checkout',
            student=None,
        )
        if 'error' in result_init:
            messages.error(request, result_init['error'])
            return redirect(back_url)
        payment = Payment.objects.filter(
            reference=result_init['reference'], school=student.school,
        ).first()
        if payment is not None:
            selected_items = get_selected_items(student, term, selected_keys)
            self._create_payment_line_items([payment], selected_items)
        return redirect(result_init['authorization_url'])

    def _create_payment_line_items(self, payments, selected_items):
        """Create PaymentLineItems for the given payments from selected checkout items."""
        by_invoice = {p.invoice_id: p for p in payments if p.invoice_id}
        for item in selected_items:
            invoice = item.get('invoice')
            payment = by_invoice.get(invoice.pk if invoice else None)
            if payment is None:
                continue
            PaymentLineItem.objects.get_or_create(
                payment=payment,
                source_key=item['source_key'],
                defaults={
                    'kind': item['kind'],
                    'label': item['label'],
                    'amount': item['amount'],
                    'category': item.get('category'),
                    'term': item.get('term'),
                    'session': item.get('session'),
                    'invoice': invoice,
                },
            )


class CheckoutContinueView(RoleRequiredMixin, View):
    """Continues a split checkout's sibling payment on the return page.

    The first allocation is initiated at submit time; the second row is
    registered PENDING without an authorization URL and is initiated here when
    the user opts to continue (reusing its reference refreshes the row).
    """
    allowed_roles = [Roles.PARENT, Roles.STUDENT]

    def get(self, request):
        back_url = 'parent-pay' if request.user.role == Roles.PARENT else 'student-pay'
        raw_payment_id = request.GET.get('payment_id')
        if not raw_payment_id:
            return redirect(back_url)
        try:
            payment_id = int(raw_payment_id)
        except (TypeError, ValueError):
            return redirect(back_url)

        payment = get_object_or_404(Payment, pk=payment_id, school=request.school)

        student = payment.student
        if student is None and payment.invoice is not None:
            student = payment.invoice.student

        role = request.user.role
        if role == Roles.PARENT:
            if student is not None and not student.guardian_links.filter(
                guardian=request.user,
            ).exists():
                return redirect(back_url)
        elif role == Roles.STUDENT:
            if student is None or student.user != request.user:
                return redirect(back_url)

        if (
            payment.status != Payment.Status.PENDING
            or payment.method != Payment.Method.PAYSTACK
            or payment.authorization_url
        ):
            return redirect(back_url)

        callback_url = request.build_absolute_uri(reverse(back_url))
        result = paystack_initiate(
            payment.invoice,
            request.user.email,
            callback_url,
            existing_reference=payment.reference,
            amount=payment.amount,
            student=payment.student,
            description=payment.description,
        )
        if 'error' in result:
            messages.error(request, result['error'])
            return redirect(back_url)
        return redirect(result['authorization_url'])


class PaymentReturnView(RoleRequiredMixin, View):
    """Return page after Paystack redirect. Shows waiting state, polls via htmx.

    Works both for invoice-backed payments (legacy ?invoice_id= links) and
    invoice-less payments — when invoice_id is absent the payment is resolved
    by reference alone (template is null-safe for invoice=None).
    """
    allowed_roles = [Roles.PARENT, Roles.STUDENT]

    def get(self, request):
        invoice_id = request.GET.get('invoice_id')
        reference = request.GET.get('reference')

        invoice = None
        if invoice_id:
            invoice = get_object_or_404(Invoice, pk=invoice_id, school=request.school)

            # Guardian scope check
            if request.user.role == Roles.PARENT:
                if not invoice.student.guardian_links.filter(guardian=request.user).exists():
                    return redirect('parent-pay')

        payment = None
        if reference:
            payment = Payment.objects.filter(
                reference=reference, school=request.school,
            ).first()

        return render(request, 'fees/payment_return.html', {
            'invoice': invoice,
            'payment': payment,
            'reference': reference,
        })


class PaymentStatusPartialView(RoleRequiredMixin, View):
    """Lightweight status check for htmx polling on the return page.

    invoice_id is optional — the payment is resolved by reference + school.
    When absent (invoice-less payments) the partial renders with invoice=None.
    """
    allowed_roles = [Roles.PARENT, Roles.STUDENT]

    def get(self, request):
        reference = request.GET.get('reference')
        invoice_id = request.GET.get('invoice_id')

        if not reference:
            return HttpResponse('<span class="text-gray-500">Invalid request.</span>')

        payment = Payment.objects.filter(
            reference=reference, school=request.school,
        ).first()

        if not payment:
            return HttpResponse('<span class="text-gray-500">Payment not found.</span>')

        invoice = None
        if invoice_id:
            invoice = Invoice.objects.filter(
                pk=invoice_id, school=request.school,
            ).first()

        # Fallback confirmation: if the webhook hasn't arrived (not yet
        # configured / delayed) verify against Paystack once and confirm when
        # the charge succeeded. Only fires for mature PENDING payments.
        if (
            payment.status == Payment.Status.PENDING
            and payment.initiated_at is not None
            and timezone.now() - payment.initiated_at >= timedelta(seconds=5)
            and payment.id not in _verify_attempted_ids
        ):
            _verify_attempted_ids.add(payment.id)
            from fees.paystack import verify_transaction, confirm_payment_from_verify
            result = verify_transaction(reference)
            if 'error' not in result:
                data = result.get('data') or {}
                if data.get('status') == 'success' and data.get('amount'):
                    confirm_payment_from_verify(payment, data)
                    payment.refresh_from_db()

        # Split checkout support: surface the latest sibling PENDING Paystack
        # row so the return page can offer to continue paying it.
        sibling_student = payment.student
        if sibling_student is None and payment.invoice is not None:
            sibling_student = payment.invoice.student
        sibling_pending = None
        if sibling_student is not None:
            sibling_pending = Payment.objects.filter(
                student=sibling_student,
                method=Payment.Method.PAYSTACK,
                status=Payment.Status.PENDING,
                authorization_url='',
            ).exclude(pk=payment.pk).select_related(
                'invoice', 'invoice__student',
            ).first()

        return render(request, 'fees/partials/payment_status.html', {
            'payment': payment,
            'invoice': invoice,
            'reference': reference,
            'sibling_pending': sibling_pending,
        })


class VerifyPaymentView(RoleRequiredMixin, View):
    """Server-side verification of a payment against the Paystack API.

    Tamper-reconciles the paid amount (kobo) with the recorded amount before
    confirming, then issues a receipt. Idempotent: already-confirmed payments
    short-circuit to the status partial without double crediting.
    """
    allowed_roles = [Roles.PARENT, Roles.STUDENT]

    def get(self, request):
        reference = request.GET.get('reference')
        invoice_id = request.GET.get('invoice_id')

        if not reference:
            return HttpResponse('<span class="text-gray-500">Invalid request.</span>')

        payment = Payment.objects.filter(
            reference=reference, school=request.school,
        ).first()
        if not payment:
            return HttpResponse('<span class="text-gray-500">Payment not found.</span>')

        # Optional invoice — resolves the student for scope checks. When the
        # invoice is absent (invoice-less payments) scope is checked against
        # payment.student instead.
        invoice = None
        if invoice_id:
            invoice = Invoice.objects.filter(
                pk=invoice_id, school=request.school,
            ).first()

        student = None
        if invoice is not None:
            student = invoice.student
        elif payment.student is not None:
            student = payment.student

        # Scope check — same role rules as the receipt resolver
        if student is not None:
            if request.user.role == Roles.PARENT:
                if not student.guardian_links.filter(guardian=request.user).exists():
                    return redirect('parent-pay')
            elif request.user.role == Roles.STUDENT:
                if student.user != request.user:
                    return redirect('student-pay')

        # Split checkout support: surface the latest sibling PENDING Paystack
        # row so the return page can offer to continue paying it.
        sibling_pending = None
        if student is not None:
            sibling_pending = Payment.objects.filter(
                student=student,
                method=Payment.Method.PAYSTACK,
                status=Payment.Status.PENDING,
                authorization_url='',
            ).exclude(pk=payment.pk).select_related(
                'invoice', 'invoice__student',
            ).first()

        # Already confirmed (e.g. via webhook) — no double-credit, show current state.
        if payment.status == Payment.Status.CONFIRMED:
            return render(request, 'fees/partials/payment_status.html', {
                'payment': payment,
                'invoice': invoice,
                'reference': reference,
                'receipt': getattr(payment, 'receipt', None),
                'sibling_pending': sibling_pending,
            })

        # PENDING/FAILED — verify against Paystack. Imports deferred: the
        # paystack helpers are provided by a parallel agent.
        from fees.paystack import verify_transaction, confirm_payment_from_verify
        result = verify_transaction(reference)

        if 'error' in result:
            # Gateway unreachable — leave status unchanged; user can retry later.
            return render(request, 'fees/partials/payment_status.html', {
                'payment': payment,
                'invoice': invoice,
                'reference': reference,
                'receipt': getattr(payment, 'receipt', None),
                'sibling_pending': sibling_pending,
            })

        data = result.get('data') or {}

        if data.get('status') == 'success' and data.get('amount'):
            confirm_payment_from_verify(payment, data)

        # Re-render with fresh state (refreshed in case a webhook landed meanwhile).
        payment.refresh_from_db()
        return render(request, 'fees/partials/payment_status.html', {
            'payment': payment,
            'invoice': invoice,
            'reference': reference,
            'receipt': getattr(payment, 'receipt', None),
            'sibling_pending': sibling_pending,
        })


def _resolve_receipt_payment(request, payment_id):
    """Resolve a payment for receipt views with role and tenant scoping.

    Null-safe for invoice-less payments: the student is derived from
    payment.student, falling back to payment.invoice.student.

    Returns a (payment, redirect_name) tuple — when redirect_name is not
    None the caller should redirect there instead of serving the receipt.
    """
    payment = get_object_or_404(Payment, pk=payment_id, school=request.school)

    student = payment.student
    if student is None and payment.invoice is not None:
        student = payment.invoice.student

    role = request.user.role
    if role == Roles.PARENT:
        if student is not None and not student.guardian_links.filter(
            guardian=request.user,
        ).exists():
            return None, 'parent-pay'
    elif role == Roles.STUDENT:
        if student is not None and student.user != request.user:
            return None, 'student-pay'
    # ADMIN passes without extra checks.

    if payment.status != Payment.Status.CONFIRMED:
        if role == Roles.PARENT:
            return None, 'parent-pay'
        if role == Roles.STUDENT:
            return None, 'student-pay'
        return None, 'school_admin:invoice_list'

    return payment, None


class PaymentReceiptView(RoleRequiredMixin, View):
    """Renders the receipt page for a confirmed payment.

    The receipt is issued lazily and idempotently via fees.paystack.issue_receipt.
    Null-safe for invoice-less payments: invoice and term are None, student
    comes from the payment itself.
    """
    allowed_roles = [Roles.PARENT, Roles.STUDENT, Roles.ADMIN]

    def get(self, request, payment_id):
        payment, redirect_name = _resolve_receipt_payment(request, payment_id)
        if payment is None:
            return redirect(redirect_name)

        from fees.paystack import issue_receipt
        receipt = issue_receipt(payment)

        student = payment.student
        if student is None and payment.invoice is not None:
            student = payment.invoice.student
        term = payment.invoice.term if payment.invoice is not None else None

        return render(request, 'fees/receipt_view.html', {
            'payment': payment,
            'invoice': payment.invoice,
            'receipt': receipt,
            'student': student,
            'term': term,
            'school': request.school,
        })


class PaymentTimeoutHelpView(RoleRequiredMixin, View):
    """Shows a help message after payment processing takes too long."""
    allowed_roles = [Roles.PARENT, Roles.STUDENT]

    def get(self, request):
        return HttpResponse(
            '<p class="text-amber-600 text-sm mt-4">Still processing? '
            'If this persists, contact the school office.</p>'
        )
