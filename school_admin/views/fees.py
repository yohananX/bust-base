"""Fee and invoice management views for school admin portal."""
import csv
from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.views.generic.base import View
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.http import HttpResponse
from django.utils import timezone

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from core.models import Term
from fees.models import FeeCategory, FeeStructure, Invoice, InvoiceLineItem, Payment
from fees.selectors import invoices_with_balance
from students.models import Student, SchoolClass, ClassEnrollment


class FeeCategoryListView(RoleRequiredMixin, View):
    """List fee categories."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        categories = FeeCategory.objects.filter(school=school).order_by('name')
        return render(request, 'school_admin/fee_category_list.html', {
            'categories': categories,
        })


class FeeCategoryCreateView(RoleRequiredMixin, View):
    """Create a new fee category."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        return render(request, 'school_admin/fee_category_form.html', {
            'is_edit': False,
        })

    def post(self, request):
        school = request.school
        name = request.POST.get('name', '').strip()
        is_compulsory = request.POST.get('is_compulsory') == 'on'

        if not name:
            messages.error(request, 'Category name is required.')
            return render(request, 'school_admin/fee_category_form.html', {
                'is_edit': False,
            })

        if FeeCategory.objects.filter(school=school, name__iexact=name).exists():
            messages.error(request, 'A category with that name already exists.')
            return render(request, 'school_admin/fee_category_form.html', {
                'is_edit': False,
            })

        FeeCategory.objects.create(
            school=school, name=name, is_compulsory=is_compulsory,
        )
        messages.success(request, f'Category "{name}" created successfully.')
        return redirect('school_admin:fee_category_list')


class FeeCategoryEditView(RoleRequiredMixin, View):
    """Edit an existing fee category."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        category = get_object_or_404(FeeCategory, school=school, pk=pk)
        return render(request, 'school_admin/fee_category_form.html', {
            'category': category,
            'is_edit': True,
        })

    def post(self, request, pk):
        school = request.school
        category = get_object_or_404(FeeCategory, school=school, pk=pk)
        name = request.POST.get('name', '').strip()
        is_compulsory = request.POST.get('is_compulsory') == 'on'

        if not name:
            messages.error(request, 'Category name is required.')
            return render(request, 'school_admin/fee_category_form.html', {
                'category': category,
                'is_edit': True,
            })

        if FeeCategory.objects.filter(
            school=school, name__iexact=name,
        ).exclude(pk=category.pk).exists():
            messages.error(request, 'A category with that name already exists.')
            return render(request, 'school_admin/fee_category_form.html', {
                'category': category,
                'is_edit': True,
            })

        category.name = name
        category.is_compulsory = is_compulsory
        category.save()
        messages.success(request, f'Category "{name}" updated successfully.')
        return redirect('school_admin:fee_category_list')


class FeeCategoryDeleteView(RoleRequiredMixin, View):
    """Delete a fee category with confirmation."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        category = get_object_or_404(FeeCategory, school=school, pk=pk)
        context = {
            'category': category,
            'structure_count': category.feestructure_set.count(),
            'line_item_count': InvoiceLineItem.objects.filter(category=category).count(),
        }
        return render(request, 'school_admin/fee_category_confirm_delete.html', context)

    def post(self, request, pk):
        school = request.school
        category = get_object_or_404(FeeCategory, school=school, pk=pk)

        if category.feestructure_set.exists():
            messages.error(request, 'Cannot delete — assigned to fee structures.')
            return redirect('school_admin:fee_category_list')

        name = category.name
        category.delete()
        messages.success(request, f'Category "{name}" deleted successfully.')
        return redirect('school_admin:fee_category_list')


class FeePricingListView(RoleRequiredMixin, View):
    """List fee price lines with class and term filters."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        from core.models import Term
        school = request.school
        pricing = FeeStructure.objects.filter(
            school=school
        ).select_related('school_class', 'term', 'category')

        class_id = request.GET.get('class_id', '')
        if class_id:
            pricing = pricing.filter(school_class_id=class_id)

        term_id = request.GET.get('term_id', '')
        if term_id:
            pricing = pricing.filter(term_id=term_id)

        classes = SchoolClass.objects.filter(school=school, is_active=True)
        terms = Term.for_current_session(school)

        return render(request, 'school_admin/fee_pricing_list.html', {
            'pricing': pricing,
            'classes': classes,
            'terms': terms,
            'filter_class': class_id,
            'filter_term': term_id,
        })


class FeePricingCreateView(RoleRequiredMixin, View):
    """Add a single fee price line (category + class + term + amount)."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        from core.models import Term
        school = request.school
        return render(request, 'school_admin/fee_pricing_form.html', {
            'is_edit': False,
            'categories': FeeCategory.objects.filter(school=school),
            'classes': SchoolClass.objects.filter(school=school, is_active=True),
            'terms': Term.for_current_session(school),
        })

    def post(self, request):
        from core.models import Term
        school = request.school
        category_id = request.POST.get('category_id', '')
        class_id = request.POST.get('class_id', '')
        term_id = request.POST.get('term_id', '')
        raw_amount = request.POST.get('amount', '').strip()

        categories = FeeCategory.objects.filter(school=school)
        classes = SchoolClass.objects.filter(school=school, is_active=True)
        terms = Term.for_current_session(school)

        def re_render():
            return render(request, 'school_admin/fee_pricing_form.html', {
                'is_edit': False,
                'categories': categories,
                'classes': classes,
                'terms': terms,
                'selected_category_id': category_id,
                'selected_class_id': class_id,
                'selected_term_id': term_id,
                'entered_amount': raw_amount,
            })

        if not category_id or not class_id or not term_id or not raw_amount:
            messages.error(request, 'All fields are required.')
            return re_render()

        category = get_object_or_404(FeeCategory, school=school, pk=category_id)
        school_class = get_object_or_404(SchoolClass, school=school, pk=class_id)
        term = get_object_or_404(Term, school=school, pk=term_id)

        try:
            amount = Decimal(raw_amount)
        except (ValueError, ArithmeticError):
            messages.error(request, 'Invalid amount.')
            return re_render()

        if amount < 0:
            messages.error(request, 'Amount cannot be negative.')
            return re_render()

        if FeeStructure.objects.filter(
            school=school,
            school_class_id=class_id,
            term_id=term_id,
            category_id=category_id,
        ).exists():
            messages.error(
                request, 'Pricing already exists for that category, class and term.'
            )
            return re_render()

        FeeStructure.objects.create(
            school=school,
            school_class=school_class,
            term=term,
            category=category,
            amount=amount,
        )
        from fees.generation import generate_invoices_for_class
        generated = generate_invoices_for_class(school_class, term)
        messages.success(
            request,
            f'Pricing added: {category.name} — {school_class.name} ({term.name}). '
            f'{generated} invoice(s) generated for students without one.',
        )
        return redirect('school_admin:fee_pricing_list')


class FeePricingEditView(RoleRequiredMixin, View):
    """Edit a single fee price line."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        from core.models import Term
        school = request.school
        structure = get_object_or_404(FeeStructure, school=school, pk=pk)
        return render(request, 'school_admin/fee_pricing_form.html', {
            'is_edit': True,
            'structure': structure,
            'categories': FeeCategory.objects.filter(school=school),
            'classes': SchoolClass.objects.filter(school=school, is_active=True),
            'terms': Term.objects.filter(school=school).order_by('-start_date'),
            'selected_category_id': structure.category_id,
            'selected_class_id': structure.school_class_id,
            'selected_term_id': structure.term_id,
        })

    def post(self, request, pk):
        from core.models import Term
        school = request.school
        structure = get_object_or_404(FeeStructure, school=school, pk=pk)

        category_id = request.POST.get('category_id', '')
        class_id = request.POST.get('class_id', '')
        term_id = request.POST.get('term_id', '')
        raw_amount = request.POST.get('amount', '').strip()

        categories = FeeCategory.objects.filter(school=school)
        classes = SchoolClass.objects.filter(school=school, is_active=True)
        terms = Term.for_current_session(school)

        def re_render():
            return render(request, 'school_admin/fee_pricing_form.html', {
                'is_edit': True,
                'structure': structure,
                'categories': categories,
                'classes': classes,
                'terms': terms,
                'selected_category_id': category_id,
                'selected_class_id': class_id,
                'selected_term_id': term_id,
                'entered_amount': raw_amount,
            })

        if not category_id or not class_id or not term_id or not raw_amount:
            messages.error(request, 'All fields are required.')
            return re_render()

        category = get_object_or_404(FeeCategory, school=school, pk=category_id)
        school_class = get_object_or_404(SchoolClass, school=school, pk=class_id)
        term = get_object_or_404(Term, school=school, pk=term_id)

        try:
            amount = Decimal(raw_amount)
        except (ValueError, ArithmeticError):
            messages.error(request, 'Invalid amount.')
            return re_render()

        if amount < 0:
            messages.error(request, 'Amount cannot be negative.')
            return re_render()

        if FeeStructure.objects.filter(
            school=school,
            school_class_id=class_id,
            term_id=term_id,
            category_id=category_id,
        ).exclude(pk=pk).exists():
            messages.error(
                request, 'Pricing already exists for that category, class and term.'
            )
            return re_render()

        structure.school_class = school_class
        structure.term = term
        structure.category = category
        structure.amount = amount
        structure.save()
        from fees.generation import (
            generate_invoices_for_class,
            sync_class_invoices,
        )
        generated = generate_invoices_for_class(school_class, term)
        re_priced = sync_class_invoices(school_class, term)
        messages.success(
            request,
            f'Pricing updated: {category.name} — {school_class.name} ({term.name}). '
            f'{generated} invoice(s) generated, {re_priced} unpaid invoice(s) re-priced.',
        )
        return redirect('school_admin:fee_pricing_list')


class FeePricingDeleteView(RoleRequiredMixin, View):
    """Delete a single fee price line with confirmation."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        structure = get_object_or_404(FeeStructure, school=school, pk=pk)
        return render(request, 'school_admin/fee_pricing_confirm_delete.html', {
            'structure': structure,
        })

    def post(self, request, pk):
        school = request.school
        structure = get_object_or_404(FeeStructure, school=school, pk=pk)
        message = (
            f'Pricing removed: {structure.category.name} — '
            f'{structure.school_class.name} ({structure.term.name}).'
        )
        structure.delete()
        messages.success(request, message)
        return redirect('school_admin:fee_pricing_list')


class InvoiceListView(RoleRequiredMixin, View):
    """List invoices with filters."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        invoices = Invoice.objects.filter(
            school=school
        ).select_related('student', 'student__user', 'term')

        term_id = request.GET.get('term_id', '')
        if term_id:
            invoices = invoices.filter(term_id=term_id)

        from fees.selectors import invoices_with_balance
        invoices = invoices_with_balance(invoices)

        status = request.GET.get('status', '')
        if status == 'PAID':
            invoices = invoices.filter(balance_annotated__lte=0)
        elif status == 'PARTIAL':
            invoices = invoices.filter(balance_annotated__gt=0, amount_paid_annotated__gt=0)
        elif status == 'UNPAID':
            invoices = invoices.filter(amount_paid_annotated__lte=0)

        student_q = request.GET.get('q', '')
        if student_q:
            invoices = invoices.filter(
                student__user__first_name__icontains=student_q
            ) | invoices.filter(
                student__user__last_name__icontains=student_q
            )

        from core.models import Term
        terms = Term.for_current_session(school)

        return render(request, 'school_admin/invoice_list.html', {
            'invoices': invoices,
            'terms': terms,
            'filter_term': term_id,
            'filter_status': status,
            'q': student_q,
        })


class InvoiceDetailView(RoleRequiredMixin, View):
    """Invoice detail with payment history."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        invoice = get_object_or_404(Invoice, school=school, pk=pk)
        line_items = invoice.line_items.all()
        payments = invoice.payments.select_related('recorded_by').order_by('-paid_on')

        return render(request, 'school_admin/invoice_detail.html', {
            'invoice': invoice,
            'line_items': line_items,
            'payments': payments,
        })

    def post(self, request, pk):
        """Record a cash payment against this invoice."""
        school = request.school
        invoice = get_object_or_404(Invoice, school=school, pk=pk)

        try:
            amount = Decimal(request.POST.get('amount', '0'))
        except (ValueError, ArithmeticError):
            messages.error(request, 'Invalid amount.')
            return redirect('school_admin:invoice_detail', pk=pk)

        if amount <= 0:
            messages.error(request, 'Amount must be positive.')
            return redirect('school_admin:invoice_detail', pk=pk)

        reference = request.POST.get('reference', '')
        method = request.POST.get('method', '')
        if method not in Payment.Method.values:
            method = Payment.Method.CASH
        Payment.objects.create(
            school=school,
            invoice=invoice,
            amount=amount,
            method=method,
            reference=reference,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            recorded_by=request.user,
            paid_by_name=request.POST.get('paid_by_name', '').strip(),
            paid_by_relation=request.POST.get('paid_by_relation', '').strip(),
        )
        messages.success(request, f'Payment of NGN{amount} recorded.')
        return redirect('school_admin:invoice_detail', pk=pk)


class GenerateInvoicesView(RoleRequiredMixin, View):
    """Generate invoices for all active students in a term."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        from core.models import Term
        school = request.school
        terms = Term.for_current_session(school)
        return render(request, 'school_admin/generate_invoices.html', {
            'terms': terms,
        })

    def post(self, request):
        from core.models import Term
        school = request.school
        term_id = request.POST.get('term_id')

        if not term_id:
            messages.error(request, 'Please select a term.')
            return redirect('school_admin:generate_invoices')

        term = get_object_or_404(Term, school=school, pk=term_id)

        from fees.generation import generate_invoice_for_student

        generated = 0
        skipped = 0

        students = Student.objects.filter(
            school=school,
            status=Student.ACTIVE,
            enrollments__session=term.session,
            enrollments__is_current=True,
        ).distinct()

        for student in students:
            if Invoice.objects.filter(school=school, student=student, term=term).exists():
                skipped += 1
                continue
            if generate_invoice_for_student(student, term) is None:
                skipped += 1
            else:
                generated += 1

        messages.success(
            request,
            f'Generated {generated} invoice(s). {skipped} skipped (already exist or no enrollment).'
        )
        return redirect('school_admin:invoice_list')


class OutstandingFeesReportView(RoleRequiredMixin, View):
    """Dedicated outstanding-fees report: KPIs, breakdowns, debtor list, CSV export."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school

        # ── Term scope: default to current term, 'all' for everything ──
        term_id = request.GET.get('term_id', '')
        current_term = Term.objects.filter(school=school, is_current=True).first()
        if term_id == 'all':
            selected_term = None
        elif term_id:
            selected_term = get_object_or_404(Term, school=school, pk=term_id)
        else:
            selected_term = current_term

        class_id = request.GET.get('class_id', '')
        status_filter = request.GET.get('status', '')
        q = request.GET.get('q', '').strip()

        terms = Term.for_current_session(school)
        classes = SchoolClass.objects.filter(
            school=school, is_active=True
        ).order_by('level', 'name')

        # ── Base debtor queryset: annotated, filtered, current class name ──
        current_class_name = ClassEnrollment.objects.filter(
            student=OuterRef('student_id'),
            is_current=True,
        ).values('school_class__name')[:1]

        qs = invoices_with_balance(Invoice.objects.filter(school=school))
        if selected_term:
            qs = qs.filter(term=selected_term)
        if class_id:
            qs = qs.filter(
                student__enrollments__school_class_id=class_id,
                student__enrollments__is_current=True,
            )
        if status_filter == 'UNPAID':
            qs = qs.filter(amount_paid_annotated=Decimal('0.00'))
        elif status_filter == 'PARTIAL':
            qs = qs.filter(amount_paid_annotated__gt=Decimal('0.00'))
        if q:
            qs = qs.filter(
                Q(student__user__first_name__icontains=q)
                | Q(student__user__last_name__icontains=q)
                | Q(student__admission_number__icontains=q)
            )
        qs = qs.filter(balance_annotated__gt=Decimal('0.00'))
        qs = qs.select_related('student__user', 'term').annotate(
            current_class_name=Subquery(current_class_name)
        )

        # ── CSV export reuses the exact same filtered queryset ──
        if request.GET.get('export') == 'csv':
            return self._csv_response(qs)

        # ── KPIs ──
        total_outstanding = qs.aggregate(
            total=Sum('balance_annotated')
        )['total'] or Decimal('0.00')
        students_owing = qs.values('student').distinct().count()
        unpaid_count = qs.filter(amount_paid_annotated=Decimal('0.00')).count()
        partial_count = qs.filter(amount_paid_annotated__gt=Decimal('0.00')).count()

        outstanding_invoices = invoices_with_balance(
            Invoice.objects.filter(school=school)
        ).filter(balance_annotated__gt=Decimal('0.00'))
        if selected_term:
            outstanding_invoices = outstanding_invoices.filter(term=selected_term)
        payments_qs = Payment.objects.filter(
            school=school,
            status=Payment.Status.CONFIRMED,
            invoice__in=outstanding_invoices,
        )
        total_collected = payments_qs.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

        # ── Breakdowns ──
        by_class = qs.values('student__enrollments__school_class__name').annotate(
            total=Sum('balance_annotated'),
            students=Count('student', distinct=True),
        ).order_by('-total')

        by_term = []
        if not selected_term:
            by_term = qs.values('term__name').annotate(
                total=Sum('balance_annotated'),
                invoices=Count('id'),
            ).order_by('-total')

        # ── Debtor rows (age buckets computed in Python — small result set) ──
        debtors = [self._debtor_row(inv) for inv in qs.order_by('-balance_annotated')]

        return render(request, 'school_admin/outstanding_fees.html', {
            'terms': terms,
            'classes': classes,
            'filter_term': term_id,
            'filter_class': class_id,
            'filter_status': status_filter,
            'q': q,
            'selected_term': selected_term,
            'total_outstanding': total_outstanding,
            'students_owing': students_owing,
            'unpaid_count': unpaid_count,
            'partial_count': partial_count,
            'total_collected': total_collected,
            'by_class': by_class,
            'by_term': by_term,
            'debtors': debtors,
        })

    def _debtor_row(self, invoice):
        """Build a display row for one outstanding invoice."""
        paid = invoice.amount_paid_annotated
        balance = invoice.balance_annotated
        status = 'PARTIAL' if paid > Decimal('0.00') else 'UNPAID'

        age_days = (timezone.localdate() - invoice.generated_on.date()).days
        if age_days > 60:
            age_bucket = '60+'
        elif age_days > 30:
            age_bucket = '31-60'
        else:
            age_bucket = '0-30'

        return {
            'invoice': invoice,
            'student': invoice.student.user.get_full_name() or invoice.student.user.username,
            'admission_number': invoice.student.admission_number,
            'class_name': invoice.current_class_name or '—',
            'term': invoice.term.name,
            'total': invoice.total_amount,
            'paid': paid,
            'balance': balance,
            'status': status,
            'age_days': age_days,
            'age_bucket': age_bucket,
        }

    def _csv_response(self, qs):
        """Serve the filtered debtor list as a CSV download."""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="outstanding_fees.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'Student', 'Admission No', 'Class', 'Term',
            'Total (NGN)', 'Paid (NGN)', 'Balance (NGN)', 'Status', 'Age Bucket',
        ])
        for inv in qs.order_by('-balance_annotated'):
            row = self._debtor_row(inv)
            writer.writerow([
                row['student'],
                row['admission_number'],
                row['class_name'],
                row['term'],
                str(row['total']),
                str(row['paid']),
                str(row['balance']),
                row['status'],
                row['age_bucket'],
            ])
        return response


class PendingTransfersView(RoleRequiredMixin, View):
    """List bank-transfer payments awaiting admin confirmation."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        payments = Payment.objects.filter(
            school=school,
            status=Payment.Status.PENDING,
            method=Payment.Method.BANK_TRANSFER,
        ).select_related(
            'student__user', 'invoice__student__user', 'invoice__term',
        ).prefetch_related('invoice__line_items__category').order_by('-paid_on')

        total_pending = payments.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

        return render(request, 'school_admin/pending_transfers.html', {
            'payments': payments,
            'total_pending': total_pending,
        })


class PendingTransferConfirmView(RoleRequiredMixin, View):
    """Confirm a pending bank-transfer payment and issue its receipt."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        payment = get_object_or_404(Payment, school=school, pk=pk)

        if payment.status != Payment.Status.PENDING:
            messages.info(request, 'This payment has already been processed.')
            return redirect('school_admin:pending_transfers')

        with transaction.atomic():
            payment.status = Payment.Status.CONFIRMED
            payment.paid_on = timezone.now()
            payment.recorded_by = request.user
            payment.webhook_processed = True
            payment.save(update_fields=[
                'status', 'paid_on', 'recorded_by', 'webhook_processed',
            ])
            from fees.paystack import issue_receipt
            issue_receipt(payment)
            from notifications.utils import notify_many
            from accounts.models import Roles, User

            recipients = []
            if payment.student_id:
                student_user = User.objects.filter(pk=payment.student.user_id).first()
                if student_user:
                    recipients.append(student_user)
                recipients += [
                    link.guardian
                    for link in payment.student.guardian_links.select_related('guardian').all()
                    if link.guardian_id
                ]
            notify_many(
                recipients=recipients,
                channel='IN_APP',
                subject=f'Bank transfer confirmed: ₦{payment.amount:,.2f}',
                message=(
                    f'Your bank transfer of ₦{payment.amount:,.2f} has been confirmed.'
                ),
                reference=f'transfer-confirm:{payment.id}',
                url=reverse('fees:payment-receipt', kwargs={'payment_id': payment.pk}),
            )

        messages.success(request, f'Payment of ₦{payment.amount:,.2f} confirmed.')
        return redirect('school_admin:pending_transfers')


class PendingTransferRejectView(RoleRequiredMixin, View):
    """Mark a pending bank-transfer payment as failed."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        payment = get_object_or_404(Payment, school=school, pk=pk)

        if payment.status != Payment.Status.PENDING:
            messages.info(request, 'This payment has already been processed.')
            return redirect('school_admin:pending_transfers')

        payment.status = Payment.Status.FAILED
        payment.save(update_fields=['status'])
        from notifications.utils import notify_many
        from accounts.models import User

        recipients = []
        if payment.student_id:
            student_user = User.objects.filter(pk=payment.student.user_id).first()
            if student_user:
                recipients.append(student_user)
            recipients += [
                link.guardian
                for link in payment.student.guardian_links.select_related('guardian').all()
                if link.guardian_id
            ]
        notify_many(
            recipients=recipients,
            channel='IN_APP',
            subject=f'Bank transfer rejected: ₦{payment.amount:,.2f}',
            message=(
                f'Your bank transfer of ₦{payment.amount:,.2f} was rejected. '
                f'Please contact the school.'
            ),
            reference=f'transfer-reject:{payment.id}',
            url=reverse('fees:payment-receipt', kwargs={'payment_id': payment.pk}),
        )

        messages.info(request, 'Payment marked failed.')
        return redirect('school_admin:pending_transfers')


class PaymentEditView(RoleRequiredMixin, View):
    """Edit a recorded payment (amount, method, payer, reference)."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        payment = get_object_or_404(Payment, school=school, pk=pk)
        return render(request, 'school_admin/payment_edit.html', {
            'payment': payment,
        })

    def post(self, request, pk):
        school = request.school
        payment = get_object_or_404(Payment, school=school, pk=pk)
        back = redirect('school_admin:invoice_detail', pk=payment.invoice_id) \
            if payment.invoice_id else redirect('school_admin:student_detail', pk=payment.student_id)

        try:
            amount = Decimal(request.POST.get('amount', '0'))
        except (ValueError, ArithmeticError):
            messages.error(request, 'Invalid amount.')
            return back
        if amount <= 0:
            messages.error(request, 'Amount must be positive.')
            return back

        method = request.POST.get('method', '')
        if method not in Payment.Method.values:
            messages.error(request, 'Invalid payment method.')
            return back

        payment.amount = amount
        payment.method = method
        payment.paid_by_name = request.POST.get('paid_by_name', '').strip()
        payment.paid_by_relation = request.POST.get('paid_by_relation', '').strip()
        payment.reference = request.POST.get('reference', '').strip() or None
        payment.save(update_fields=[
            'amount', 'method', 'paid_by_name', 'paid_by_relation', 'reference',
        ])
        messages.success(request, 'Payment updated.')
        return back


class PaymentDeleteView(RoleRequiredMixin, View):
    """Delete a wrongly recorded payment."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        payment = get_object_or_404(Payment, school=school, pk=pk)
        back = redirect('school_admin:invoice_detail', pk=payment.invoice_id) \
            if payment.invoice_id else redirect('school_admin:student_detail', pk=payment.student_id)

        amount = payment.amount
        payment.delete()
        messages.success(request, f'Payment of ₦{amount:,.2f} deleted.')
        return back


class StudentRecordPaymentView(RoleRequiredMixin, View):
    """Record a payment against a student, optionally linked to an invoice."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        student = get_object_or_404(Student, school=school, pk=pk)

        try:
            amount = Decimal(request.POST.get('amount', '0'))
        except (ValueError, ArithmeticError):
            messages.error(request, 'Invalid amount.')
            return redirect('school_admin:student_detail', pk=student.pk)
        if amount <= 0:
            messages.error(request, 'Amount must be positive.')
            return redirect('school_admin:student_detail', pk=student.pk)

        method = request.POST.get('method', '')
        if method not in Payment.Method.values:
            messages.error(request, 'Invalid payment method.')
            return redirect('school_admin:student_detail', pk=student.pk)

        invoice_id = request.POST.get('invoice_id', '')
        invoice = None
        if invoice_id:
            invoice = get_object_or_404(Invoice, school=school, pk=invoice_id)
            if invoice.student_id != student.pk:
                messages.error(request, 'That invoice belongs to a different student.')
                return redirect('school_admin:student_detail', pk=student.pk)

        payment = Payment.objects.create(
            school=school,
            invoice=invoice,
            student=student,
            amount=amount,
            method=method,
            reference=request.POST.get('reference', '').strip() or None,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            recorded_by=request.user,
            description=request.POST.get('description', '').strip(),
            paid_by_name=request.POST.get('paid_by_name', '').strip(),
            paid_by_relation=request.POST.get('paid_by_relation', '').strip(),
        )
        from fees.paystack import issue_receipt
        issue_receipt(payment)
        from notifications.utils import notify_many
        from accounts.models import User

        recipients = []
        student_user = User.objects.filter(pk=student.user_id).first()
        if student_user:
            recipients.append(student_user)
        recipients += [
            link.guardian
            for link in student.guardian_links.select_related('guardian').all()
            if link.guardian_id
        ]
        notify_many(
            recipients=recipients,
            channel='IN_APP',
            subject=f'Payment recorded: ₦{amount:,.2f}',
            message=f'Payment of ₦{amount:,.2f} has been recorded for {student}.',
            reference=f'payment-record:{payment.id}',
            url=reverse('fees:payment-receipt', kwargs={'payment_id': payment.pk}),
        )
        messages.success(request, f'Payment of ₦{amount:,.2f} recorded.')
        return redirect('school_admin:student_detail', pk=student.pk)
