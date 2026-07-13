"""Payroll generation engine — pure functions for creating PayrollRun + Payslips.

Idempotent: uses get_or_create on Payslip with unique_together constraint.
Generation is always an explicit action (no signals).
"""

from decimal import Decimal

from django.db.models import Q

from .models import (
    StaffProfile,
    PayrollRun,
    Payslip,
    PayslipLineItem,
    AllowanceDefinition,
    DeductionDefinition,
)


def generate_payroll_run(school, label, period_start, period_end, pay_date,
                         generated_by, staff_filter=None):
    """Create a PayrollRun and generate payslips for eligible staff.

    Args:
        school: School instance for tenant scoping.
        label: Human-readable label for the run (e.g. "July 2026").
        period_start: Start date of the pay period.
        period_end: End date of the pay period.
        pay_date: Date when salary will be paid.
        generated_by: User who triggered generation.
        staff_filter: Optional QuerySet of StaffProfile to limit generation.

    Returns:
        tuple: (PayrollRun, dict with counts: generated, skipped, total)

    Idempotent: already-existing payslips for the same staff+run are skipped.
    """
    payroll_run = PayrollRun.objects.create(
        school=school,
        label=label,
        period_start=period_start,
        period_end=period_end,
        pay_date=pay_date,
        generated_by=generated_by,
    )

    # Determine staff to process
    if staff_filter is not None:
        staff_profiles = staff_filter.filter(school=school)
    else:
        staff_profiles = StaffProfile.objects.filter(
            school=school,
            status=StaffProfile.ACTIVE,
        )

    generated = 0
    skipped = 0

    for staff in staff_profiles:
        payslip = generate_payslip(staff, payroll_run)
        if payslip:
            generated += 1
        else:
            skipped += 1

    return payroll_run, {
        'generated': generated,
        'skipped': skipped,
        'total': generated + skipped,
    }


def generate_payslip(staff_profile, payroll_run):
    """Generate a single payslip for a staff member in a given payroll run.

    Idempotent: returns None if the payslip already exists for this staff+run
    or if the staff member is not active.

    Creates Payslip + PayslipLineItem records from current policy configuration.
    """
    # Only active staff get payslips
    if staff_profile.status != StaffProfile.ACTIVE:
        return None

    school = staff_profile.school
    pay_grade = staff_profile.pay_grade

    # Base salary
    base_salary = pay_grade.base_salary if pay_grade else Decimal('0.00')

    # Resolve allowances (grade-level + individual)
    allowance_qs = AllowanceDefinition.objects.filter(
        school=school,
        is_active=True,
    )
    if pay_grade:
        allowance_qs = allowance_qs.filter(
            Q(pay_grade=pay_grade) | Q(target_staff=staff_profile)
        )
    else:
        allowance_qs = allowance_qs.filter(target_staff=staff_profile)

    # Resolve deductions (grade-level + individual)
    deduction_qs = DeductionDefinition.objects.filter(
        school=school,
        is_active=True,
    )
    if pay_grade:
        deduction_qs = deduction_qs.filter(
            Q(pay_grade=pay_grade) | Q(target_staff=staff_profile)
        )
    else:
        deduction_qs = deduction_qs.filter(target_staff=staff_profile)

    # Compute totals BEFORE creating the payslip
    total_allowances = sum((a.amount for a in allowance_qs), Decimal('0.00'))
    total_deductions = sum((d.amount for d in deduction_qs), Decimal('0.00'))
    gross_pay = base_salary + total_allowances
    net_pay = gross_pay - total_deductions

    # Idempotent create: provide all values in defaults so the INSERT works
    payslip, created = Payslip.objects.get_or_create(
        school=school,
        staff=staff_profile,
        payroll_run=payroll_run,
        defaults={
            'base_salary': base_salary,
            'total_allowances': total_allowances,
            'total_deductions': total_deductions,
            'gross_pay': gross_pay,
            'net_pay': net_pay,
        },
    )

    if not created:
        # Already exists — skip
        return None

    # Create line items for base salary
    PayslipLineItem.objects.create(
        payslip=payslip,
        label='Base Salary',
        amount=base_salary,
        line_type=PayslipLineItem.LineType.ALLOWANCE,
    )

    # Create line items for each allowance
    for allowance in allowance_qs:
        PayslipLineItem.objects.create(
            payslip=payslip,
            label=allowance.name,
            amount=allowance.amount,
            line_type=PayslipLineItem.LineType.ALLOWANCE,
        )

    # Create line items for each deduction
    for deduction in deduction_qs:
        PayslipLineItem.objects.create(
            payslip=payslip,
            label=deduction.name,
            amount=deduction.amount,
            line_type=PayslipLineItem.LineType.DEDUCTION,
        )

    return payslip
