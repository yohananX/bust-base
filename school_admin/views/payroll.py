"""Payroll management views for school admin portal."""
from decimal import Decimal
from datetime import datetime

from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic.base import View
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from payroll.models import (
    PayGrade, AllowanceDefinition, DeductionDefinition,
    PayrollRun, Payslip, SalaryDisbursement, StaffProfile,
)


class PayGradeListView(RoleRequiredMixin, View):
    """List pay grades."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        grades = PayGrade.objects.filter(school=school).order_by('name')
        return render(request, 'school_admin/payroll_list.html', {
            'pay_grades': grades,
            'section': 'pay_grades',
        })


class AllowanceDeductionListView(RoleRequiredMixin, View):
    """List allowance and deduction definitions."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        allowances = AllowanceDefinition.objects.filter(school=school).select_related('pay_grade', 'target_staff')
        deductions = DeductionDefinition.objects.filter(school=school).select_related('pay_grade', 'target_staff')
        return render(request, 'school_admin/payroll_list.html', {
            'allowances': allowances,
            'deductions': deductions,
            'section': 'allowances',
        })


class PayrollRunListView(RoleRequiredMixin, View):
    """List payroll runs."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        runs = PayrollRun.objects.filter(
            school=school
        ).select_related('generated_by').order_by('-generated_on')

        status = request.GET.get('status', '')
        if status == 'cancelled':
            runs = runs.filter(cancelled_at__isnull=False)
        else:
            runs = runs.filter(cancelled_at__isnull=True)

        return render(request, 'school_admin/payroll_list.html', {
            'runs': runs,
            'section': 'runs',
            'filter_status': status,
        })


class PayrollRunDetailView(RoleRequiredMixin, View):
    """Payroll run detail with all payslips."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        run = get_object_or_404(PayrollRun, school=school, pk=pk)
        payslips = Payslip.objects.filter(
            payroll_run=run
        ).select_related('staff', 'staff__user')

        return render(request, 'school_admin/payroll_detail.html', {
            'run': run,
            'payslips': payslips,
        })


class GeneratePayrollView(RoleRequiredMixin, View):
    """Generate a new payroll run."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        return render(request, 'school_admin/payroll_list.html', {
            'section': 'generate',
        })

    def post(self, request):
        school = request.school
        label = request.POST.get('label', '')
        period_start = request.POST.get('period_start', '')
        period_end = request.POST.get('period_end', '')
        pay_date = request.POST.get('pay_date', '')

        if not all([label, period_start, period_end, pay_date]):
            messages.error(request, 'Please fill in all fields.')
            return redirect('school_admin:payroll_run_list')

        from payroll.utils import generate_payroll_run as run_generation

        result = run_generation(
            school=school,
            label=label,
            period_start=parse_date(period_start),
            period_end=parse_date(period_end),
            pay_date=parse_date(pay_date),
            generated_by=request.user,
        )

        payroll_run, counts = result
        messages.success(
            request,
            f'Payroll run "{label}" created. Generated {counts["generated"]} payslip(s).'
        )
        return redirect('school_admin:payroll_run_detail', pk=payroll_run.pk)


class RecordDisbursementView(RoleRequiredMixin, View):
    """Record salary disbursement for a payslip."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, payslip_id):
        school = request.school
        payslip = get_object_or_404(Payslip, school=school, pk=payslip_id)
        return render(request, 'school_admin/disburse.html', {
            'payslip': payslip,
        })

    def post(self, request, payslip_id):
        school = request.school
        payslip = get_object_or_404(Payslip, school=school, pk=payslip_id)

        amount = Decimal(request.POST.get('amount', '0'))
        method = request.POST.get('method', '')
        reference = request.POST.get('reference', '')
        disbursed_on_str = request.POST.get('disbursed_on', '')

        if not all([amount > 0, method, reference, disbursed_on_str]):
            messages.error(request, 'Please fill in all fields.')
            return redirect('school_admin:record_disbursement', payslip_id=payslip_id)

        from django.utils.dateparse import parse_datetime
        disbursed_on = parse_datetime(disbursed_on_str)
        if not disbursed_on:
            messages.error(request, 'Invalid date format.')
            return redirect('school_admin:record_disbursement', payslip_id=payslip_id)

        if timezone.is_naive(disbursed_on):
            disbursed_on = timezone.make_aware(disbursed_on)

        SalaryDisbursement.objects.create(
            school=school,
            payslip=payslip,
            amount=amount,
            method=method,
            reference=reference,
            status=SalaryDisbursement.Status.CONFIRMED,
            disbursed_on=disbursed_on,
            recorded_by=request.user,
        )

        messages.success(request, f'Disbursement of NGN{amount} recorded.')
        return redirect('school_admin:payroll_run_detail', pk=payslip.payroll_run.pk)
