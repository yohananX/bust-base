"""Fee and invoice management views for school admin portal."""
from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic.base import View
from django.contrib import messages
from django.db import transaction
from django.utils import timezone

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from fees.models import FeeCategory, FeeStructure, Invoice, InvoiceLineItem, Payment
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
