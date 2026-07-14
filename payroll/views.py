"""HTML views for payroll — payslip list, detail, and run overview."""
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, get_object_or_404
from django.utils.decorators import method_decorator
from django.views.generic import ListView, DetailView

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from .models import Payslip, PayrollRun, PayslipLineItem


class PayslipListView(RoleRequiredMixin, ListView):
    """List payslips — staff see their own, admins see all."""
    model = Payslip
    template_name = 'payroll/payslip_list.html'
    context_object_name = 'payslips'
    allowed_roles = [Roles.TEACHER, Roles.ADMIN]

    def get_queryset(self):
        qs = Payslip.objects.select_related(
            'payroll_run', 'staff__user'
        ).filter(school=self.request.user.school)

        if self.request.user.role != Roles.ADMIN:
            qs = qs.filter(staff__user=self.request.user)

        return qs


@login_required
def payslip_detail(request, payslip_id):
    """Full payslip breakdown — staff see own, admins see all."""
    payslip = get_object_or_404(Payslip, pk=payslip_id)

    user = request.user
    if user.role != 'ADMIN':
        staff_profile = getattr(user, 'staff_profile', None)
        if not staff_profile or payslip.staff != staff_profile:
            raise PermissionDenied('You do not have access to this payslip.')

    line_items = payslip.line_items.all()
    allowances = line_items.filter(line_type=PayslipLineItem.LineType.ALLOWANCE)
    deductions = line_items.filter(line_type=PayslipLineItem.LineType.DEDUCTION)
    disbursements = payslip.disbursements.select_related('recorded_by').all()

    return render(request, 'payroll/payslip_detail.html', {
        'payslip': payslip,
        'allowances': allowances,
        'deductions': deductions,
        'disbursements': disbursements,
    })


class PayrollRunDetailView(RoleRequiredMixin, DetailView):
    """Payroll run summary with all payslips (admin only)."""
    model = PayrollRun
    template_name = 'payroll/run_detail.html'
    context_object_name = 'run'
    allowed_roles = [Roles.ADMIN]

    def get_queryset(self):
        return PayrollRun.objects.filter(school=self.request.user.school)
