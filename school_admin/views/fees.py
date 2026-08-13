"""Fee and invoice management views for school admin portal."""
import csv
from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
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
        return render(request, 'school_admin/fee_list.html', {
            'categories': categories,
            'section': 'categories',
        })


class FeeStructureListView(RoleRequiredMixin, View):
    """List fee structures with filters."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        structures = FeeStructure.objects.filter(
            school=school
        ).select_related('school_class', 'term', 'category')

        class_id = request.GET.get('class_id', '')
        if class_id:
            structures = structures.filter(school_class_id=class_id)

        term_id = request.GET.get('term_id', '')
        if term_id:
            structures = structures.filter(term_id=term_id)

        from core.models import Term
        classes = SchoolClass.objects.filter(school=school, is_active=True)
        terms = Term.objects.filter(school=school).order_by('-start_date')

        return render(request, 'school_admin/fee_list.html', {
            'structures': structures,
            'classes': classes,
            'terms': terms,
            'filter_class': class_id,
            'filter_term': term_id,
            'section': 'structures',
        })


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

        status = request.GET.get('status', '')
        if status == 'PAID':
            invoices = [inv for inv in invoices if inv.status == 'PAID']
        elif status == 'PARTIAL':
            invoices = [inv for inv in invoices if inv.status == 'PARTIAL']
        elif status == 'UNPAID':
            invoices = [inv for inv in invoices if inv.status == 'UNPAID']

        student_q = request.GET.get('q', '')
        if student_q:
            invoices = invoices.filter(
                student__user__first_name__icontains=student_q
            ) | invoices.filter(
                student__user__last_name__icontains=student_q
            )

        from core.models import Term
        terms = Term.objects.filter(school=school).order_by('-start_date')

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
        Payment.objects.create(
            school=school,
            invoice=invoice,
            amount=amount,
            method=Payment.Method.CASH,
            reference=reference,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            recorded_by=request.user,
        )
        messages.success(request, f'Payment of NGN{amount} recorded.')
        return redirect('school_admin:invoice_detail', pk=pk)


class GenerateInvoicesView(RoleRequiredMixin, View):
    """Generate invoices for all active students in a term."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        from core.models import Term
        school = request.school
        terms = Term.objects.filter(school=school, is_current=True)
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

            enrollment = ClassEnrollment.objects.filter(
                student=student, session=term.session, is_current=True
            ).first()
            if not enrollment:
                skipped += 1
                continue

            fee_structures = FeeStructure.objects.filter(
                school=school,
                school_class=enrollment.school_class,
                term=term,
            )
            if not fee_structures.exists():
                continue

            line_items_data = []
            total = Decimal('0.00')
            for fs in fee_structures:
                line_items_data.append({'category': fs.category, 'amount': fs.amount})
                total += fs.amount

            invoice = Invoice.objects.create(
                school=school, student=student, term=term, total_amount=total,
            )
            for li in line_items_data:
                InvoiceLineItem.objects.create(
                    invoice=invoice, category=li['category'], amount=li['amount'],
                )
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

        terms = Term.objects.filter(school=school).order_by('-start_date')
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

        messages.info(request, 'Payment marked failed.')
        return redirect('school_admin:pending_transfers')
