from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from core.models import TenantScopedModel
from accounts.models import Roles


# ─── Staff Profile ─────────────────────────────────────────────────────────────


class StaffProfile(TenantScopedModel):
    """Payroll profile for any User who draws a salary.

    Role-agnostic — any User (ADMIN, TEACHER, etc.) can have a StaffProfile.
    This is deliberately NOT restricted with limit_choices_to on the User FK.
    """

    ACTIVE = 'ACTIVE'
    SUSPENDED = 'SUSPENDED'
    RESIGNED = 'RESIGNED'
    TERMINATED = 'TERMINATED'
    STATUS_CHOICES = [
        (ACTIVE, _('Active')),
        (SUSPENDED, _('Suspended')),
        (RESIGNED, _('Resigned')),
        (TERMINATED, _('Terminated')),
    ]

    user = models.OneToOneField(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='staff_profile',
        verbose_name=_('user'),
    )
    employee_id = models.CharField(
        max_length=50,
        verbose_name=_('employee ID'),
    )
    bank_name = models.CharField(
        max_length=200,
        verbose_name=_('bank name'),
    )
    bank_account_number = models.CharField(
        max_length=50,
        verbose_name=_('bank account number'),
    )
    bank_account_name = models.CharField(
        max_length=200,
        verbose_name=_('bank account name'),
    )
    hire_date = models.DateField(verbose_name=_('hire date'))
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=ACTIVE,
        verbose_name=_('status'),
    )
    pay_grade = models.ForeignKey(
        'PayGrade',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='staff_profiles',
        verbose_name=_('pay grade'),
    )

    class Meta:
        verbose_name = _('staff profile')
        verbose_name_plural = _('staff profiles')
        unique_together = ('school', 'employee_id')

    def __str__(self):
        name = self.user.get_full_name() or self.user.username
        return f'{name} ({self.employee_id})'


# ─── Policy Models ─────────────────────────────────────────────────────────────


class PayGrade(TenantScopedModel):
    """Defines base salary for a role/level combination (policy model)."""

    name = models.CharField(max_length=200, verbose_name=_('name'))
    role_filter = models.CharField(
        max_length=20,
        choices=Roles.CHOICES,
        null=True,
        blank=True,
        verbose_name=_('role filter'),
        help_text=_('Optional: restrict this grade to a specific user role'),
    )
    base_salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_('base salary'),
    )
    description = models.TextField(
        blank=True,
        verbose_name=_('description'),
    )

    class Meta:
        verbose_name = _('pay grade')
        verbose_name_plural = _('pay grades')
        ordering = ['name']

    def __str__(self):
        return self.name


class AllowanceDefinition(TenantScopedModel):
    """Defines a recurring addition to salary (policy model).

    Scope: linked to a PayGrade (all staff on that grade) XOR a specific StaffProfile.
    """

    name = models.CharField(max_length=200, verbose_name=_('name'))
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_('amount'),
    )
    is_active = models.BooleanField(default=True, verbose_name=_('active'))
    pay_grade = models.ForeignKey(
        PayGrade,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='allowance_definitions',
        verbose_name=_('pay grade'),
    )
    target_staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='allowance_definitions',
        verbose_name=_('target staff'),
    )

    class Meta:
        verbose_name = _('allowance definition')
        verbose_name_plural = _('allowance definitions')

    def clean(self):
        """Validate XOR: exactly one of pay_grade or target_staff must be set."""
        if bool(self.pay_grade_id) == bool(self.target_staff_id):
            raise ValidationError(
                _('Exactly one of "pay grade" or "target staff" must be set, not both or neither.')
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        scope = self.pay_grade or self.target_staff
        return f'{self.name} ({self.amount}) — {scope}'


class DeductionDefinition(TenantScopedModel):
    """Defines a recurring subtraction from salary (policy model).

    Same XOR-scoping pattern as AllowanceDefinition.
    """

    name = models.CharField(max_length=200, verbose_name=_('name'))
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_('amount'),
    )
    is_active = models.BooleanField(default=True, verbose_name=_('active'))
    pay_grade = models.ForeignKey(
        PayGrade,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='deduction_definitions',
        verbose_name=_('pay grade'),
    )
    target_staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='deduction_definitions',
        verbose_name=_('target staff'),
    )

    class Meta:
        verbose_name = _('deduction definition')
        verbose_name_plural = _('deduction definitions')

    def clean(self):
        """Validate XOR: exactly one of pay_grade or target_staff must be set."""
        if bool(self.pay_grade_id) == bool(self.target_staff_id):
            raise ValidationError(
                _('Exactly one of "pay grade" or "target staff" must be set, not both or neither.')
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        scope = self.pay_grade or self.target_staff
        return f'{self.name} ({self.amount}) — {scope}'


# ─── Execution Models ──────────────────────────────────────────────────────────


class PayrollRun(TenantScopedModel):
    """Represents a specific pay period — groups payslips generated in one batch.

    No status field — lifecycle is computed from constituent payslips.
    """

    label = models.CharField(max_length=200, verbose_name=_('label'))
    period_start = models.DateField(verbose_name=_('period start'))
    period_end = models.DateField(verbose_name=_('period end'))
    pay_date = models.DateField(verbose_name=_('pay date'))
    generated_on = models.DateTimeField(auto_now_add=True, verbose_name=_('generated on'))
    generated_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        verbose_name=_('generated by'),
    )
    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('cancelled at'),
    )

    class Meta:
        verbose_name = _('payroll run')
        verbose_name_plural = _('payroll runs')
        ordering = ['-generated_on']

    def __str__(self):
        return f'{self.label} ({self.period_start} — {self.period_end})'

    @property
    def total_gross_pay(self):
        result = self.payslips.aggregate(total=Sum('gross_pay'))['total']
        return result or Decimal('0.00')

    @property
    def total_net_pay(self):
        result = self.payslips.aggregate(total=Sum('net_pay'))['total']
        return result or Decimal('0.00')

    @property
    def total_disbursed(self):
        from django.db.models import Sum, Subquery, OuterRef
        # Sum of all CONFIRMED SalaryDisbursement for all payslips in this run
        confirmed = SalaryDisbursement.objects.filter(
            payslip__in=self.payslips.all(),
            status=SalaryDisbursement.Status.CONFIRMED,
        ).aggregate(total=Sum('amount'))['total']
        return confirmed or Decimal('0.00')

    @property
    def staff_count(self):
        return self.payslips.count()


class Payslip(TenantScopedModel):
    """Snapshot of one staff's earnings for one payroll run.

    Stores computed totals at generation time. Only disbursement_status
    is computed dynamically from SalaryDisbursement records.
    """

    staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE,
        related_name='payslips',
        verbose_name=_('staff'),
    )
    payroll_run = models.ForeignKey(
        PayrollRun,
        on_delete=models.CASCADE,
        related_name='payslips',
        verbose_name=_('payroll run'),
    )
    base_salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_('base salary'),
    )
    total_allowances = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_('total allowances'),
    )
    total_deductions = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_('total deductions'),
    )
    gross_pay = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name=_('gross pay'),
    )
    net_pay = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name=_('net pay'),
    )

    class Meta:
        verbose_name = _('payslip')
        verbose_name_plural = _('payslips')
        unique_together = ('school', 'staff', 'payroll_run')

    def __str__(self):
        return f'{self.staff} — {self.payroll_run.label} ({self.net_pay})'

    @property
    def amount_disbursed(self):
        """Sum of CONFIRMED SalaryDisbursement amounts for this payslip."""
        result = self.disbursements.filter(
            status=SalaryDisbursement.Status.CONFIRMED,
        ).aggregate(total=Sum('amount'))['total']
        return result or Decimal('0.00')

    @property
    def balance(self):
        """Remaining amount to be disbursed."""
        return self.net_pay - self.amount_disbursed

    @property
    def disbursement_status(self):
        """Computed from SalaryDisbursement records.

        Returns UNPAID if no CONFIRMED disbursements, PARTIAL if
        partially paid, PAID if fully paid.
        """
        paid = self.amount_disbursed
        if paid <= 0:
            return 'UNPAID'
        elif paid < self.net_pay:
            return 'PARTIAL'
        return 'PAID'


class PayslipLineItem(models.Model):
    """Individual component of a payslip (allowance or deduction).

    Uses plain models.Model (NOT TenantScopedModel) since it's always
    accessed through its parent Payslip, which is already school-scoped.
    Follows the InvoiceLineItem pattern from fees.
    """

    class LineType(models.TextChoices):
        ALLOWANCE = 'ALLOWANCE', _('Allowance')
        DEDUCTION = 'DEDUCTION', _('Deduction')

    payslip = models.ForeignKey(
        Payslip,
        on_delete=models.CASCADE,
        related_name='line_items',
        verbose_name=_('payslip'),
    )
    label = models.CharField(max_length=255, verbose_name=_('label'))
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_('amount'),
    )
    line_type = models.CharField(
        max_length=20,
        choices=LineType.choices,
        verbose_name=_('line type'),
    )

    class Meta:
        verbose_name = _('payslip line item')
        verbose_name_plural = _('payslip line items')

    def __str__(self):
        return f'{self.label}: {self.amount} ({self.get_line_type_display()})'


class SalaryDisbursement(TenantScopedModel):
    """Records actual disbursement of salary to a staff member.

    Mirrors fees.Payment but for money OUT (salary payments).
    Follows same status lifecycle: PENDING → CONFIRMED, or FAILED.
    """

    class Method(models.TextChoices):
        BANK_TRANSFER = 'BANK_TRANSFER', _('Bank Transfer')
        CASH = 'CASH', _('Cash')
        CHEQUE = 'CHEQUE', _('Cheque')

    class Status(models.TextChoices):
        PENDING = 'PENDING', _('Pending')
        CONFIRMED = 'CONFIRMED', _('Confirmed')
        FAILED = 'FAILED', _('Failed')

    payslip = models.ForeignKey(
        Payslip,
        on_delete=models.CASCADE,
        related_name='disbursements',
        verbose_name=_('payslip'),
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_('amount'),
    )
    method = models.CharField(
        max_length=20,
        choices=Method.choices,
        verbose_name=_('method'),
    )
    reference = models.CharField(
        max_length=255,
        verbose_name=_('reference'),
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name=_('status'),
    )
    disbursed_on = models.DateTimeField(verbose_name=_('disbursed on'))
    recorded_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        verbose_name=_('recorded by'),
    )

    class Meta:
        verbose_name = _('salary disbursement')
        verbose_name_plural = _('salary disbursements')
        unique_together = ('school', 'reference')
        ordering = ['-disbursed_on']

    def __str__(self):
        return f'{self.payslip} — {self.amount} ({self.get_status_display()})'
