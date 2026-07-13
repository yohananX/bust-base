"""REST-like JSON endpoints for payroll status and self-service."""
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import Payslip, SalaryDisbursement, StaffProfile


@login_required
@require_GET
def payslip_detail(request, payslip_id):
    """Return payslip details as JSON.

    Staff see their own payslips; admins see all.
    """
    payslip = get_object_or_404(Payslip, pk=payslip_id)

    user = request.user
    if user.role != 'ADMIN':
        staff_profile = getattr(user, 'staff_profile', None)
        if not staff_profile or payslip.staff != staff_profile:
            return JsonResponse({'error': 'Forbidden'}, status=403)

    line_items = list(payslip.line_items.all().values('label', 'amount', 'line_type'))
    disbursements = list(
        payslip.disbursements.all().values('amount', 'method', 'reference', 'status', 'disbursed_on')
    )

    return JsonResponse({
        'id': payslip.id,
        'staff': str(payslip.staff),
        'payroll_run': str(payslip.payroll_run),
        'base_salary': str(payslip.base_salary),
        'total_allowances': str(payslip.total_allowances),
        'total_deductions': str(payslip.total_deductions),
        'gross_pay': str(payslip.gross_pay),
        'net_pay': str(payslip.net_pay),
        'amount_disbursed': str(payslip.amount_disbursed),
        'balance': str(payslip.balance),
        'disbursement_status': payslip.disbursement_status,
        'line_items': line_items,
        'disbursements': disbursements,
    })


@login_required
@require_GET
def my_payslips(request):
    """Return all payslips for the current user's staff profile."""
    user = request.user
    staff_profile = getattr(user, 'staff_profile', None)
    if not staff_profile:
        return JsonResponse({'error': 'No staff profile found'}, status=404)

    payslips = Payslip.objects.filter(staff=staff_profile).select_related('payroll_run')
    data = []
    for p in payslips:
        data.append({
            'id': p.id,
            'payroll_run': str(p.payroll_run),
            'gross_pay': str(p.gross_pay),
            'net_pay': str(p.net_pay),
            'disbursement_status': p.disbursement_status,
            'balance': str(p.balance),
        })

    return JsonResponse({'payslips': data})


@login_required
@require_GET
def payroll_run_detail(request, run_id):
    """Return payroll run summary with all constituent payslips (admin only)."""
    if request.user.role != 'ADMIN':
        return JsonResponse({'error': 'Forbidden'}, status=403)

    from .models import PayrollRun
    run = get_object_or_404(PayrollRun, pk=run_id, school=request.user.school)

    payslips_data = []
    for ps in run.payslips.select_related('staff__user').all():
        payslips_data.append({
            'id': ps.id,
            'staff': str(ps.staff),
            'gross_pay': str(ps.gross_pay),
            'net_pay': str(ps.net_pay),
            'disbursement_status': ps.disbursement_status,
            'balance': str(ps.balance),
        })

    return JsonResponse({
        'id': run.id,
        'label': run.label,
        'period_start': run.period_start.isoformat(),
        'period_end': run.period_end.isoformat(),
        'pay_date': run.pay_date.isoformat(),
        'total_gross_pay': str(run.total_gross_pay),
        'total_net_pay': str(run.total_net_pay),
        'total_disbursed': str(run.total_disbursed),
        'staff_count': run.staff_count,
        'payslips': payslips_data,
    })
