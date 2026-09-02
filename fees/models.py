from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from core.models import TenantScopedModel
from fees.validators import validate_proof_file


class FeeCategoryGroup(TenantScopedModel):
    GROUP_TYPES = [
        ('RECURRING', _('Recurring (per-term)')),
        ('ONE_OFF', _('One-off')),
    ]

    name = models.CharField(max_length=200, verbose_name=_('name'))
    group_type = models.CharField(
        max_length=20,
        choices=GROUP_TYPES,
        default='RECURRING',
        verbose_name=_('group type'),
    )
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='children',
        verbose_name=_('parent group'),
    )
    sort_order = models.PositiveIntegerField(default=0, verbose_name=_('sort order'))
    is_active = models.BooleanField(default=True, verbose_name=_('active'))

    class Meta:
        verbose_name = _('fee category group')
        verbose_name_plural = _('fee category groups')
        ordering = ['sort_order', 'name']
        unique_together = ('school', 'name')

    def __str__(self):
        return self.name

    def clean(self):
        if self.parent and self.parent.school_id != self.school_id:
            raise ValidationError(_('Parent group must belong to the same school.'))
        depth = 0
        parent = self.parent
        while parent:
            depth += 1
            if depth > 1:
                raise ValidationError(_('Groups may be nested at most 2 levels deep.'))
            parent = parent.parent


class FeeCategoryGroupAssignment(TenantScopedModel):
    group = models.ForeignKey(
        FeeCategoryGroup,
        on_delete=models.CASCADE,
        related_name='assignments',
        verbose_name=_('group'),
    )
    category = models.ForeignKey(
        'FeeCategory',
        on_delete=models.CASCADE,
        related_name='group_assignments',
        verbose_name=_('category'),
    )
    sort_order = models.PositiveIntegerField(default=0, verbose_name=_('sort order'))

    class Meta:
        verbose_name = _('fee category group assignment')
        verbose_name_plural = _('fee category group assignments')
        ordering = ['sort_order', 'category__name']
        unique_together = ('school', 'group', 'category')

    def __str__(self):
        return f'{self.category.name} → {self.group.name}'


class FeeCategory(TenantScopedModel):
    BILLING_CYCLE_CHOICES = [
        ('ONE_TIME', _('One-time')),
        ('PER_TERM', _('Per term')),
    ]
    STUDENT_TYPE_CHOICES = [
        ('NEW', _('New intake only')),
        ('RETURNING', _('Returning pupils only')),
        ('ALL', _('All students')),
    ]

    name = models.CharField(max_length=200, verbose_name=_('name'))
    is_compulsory = models.BooleanField(
        default=True,
        verbose_name=_('compulsory'),
        help_text=_(
            'Compulsory categories (e.g. school fees) are billed automatically on every '
            'term invoice. Optional categories (e.g. uniform) only appear as payable '
            'extras a parent chooses to pay.'
        ),
    )
    billing_cycle = models.CharField(
        max_length=20,
        choices=BILLING_CYCLE_CHOICES,
        default='PER_TERM',
        verbose_name=_('billing cycle'),
        help_text=_('One-time fees apply only once (e.g. registration). Per-term fees recur each term.'),
    )
    student_type = models.CharField(
        max_length=20,
        choices=STUDENT_TYPE_CHOICES,
        default='ALL',
        verbose_name=_('student type'),
        help_text=_('Which students this category applies to.'),
    )
    group = models.ForeignKey(
        FeeCategoryGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='categories',
        verbose_name=_('group'),
    )

    class Meta:
        verbose_name = _('fee category')
        verbose_name_plural = _('fee categories')
        ordering = ['name']

    def __str__(self):
        return self.name


class FeePrice(TenantScopedModel):
    SCOPE_SCHOOL_WIDE = 'SCHOOL_WIDE'
    SCOPE_LEVEL = 'LEVEL'
    SCOPE_CLASS = 'CLASS'
    SCOPE_CHOICES = [
        (SCOPE_SCHOOL_WIDE, _('School-wide')),
        (SCOPE_LEVEL, _('Level/Grade')),
        (SCOPE_CLASS, _('Class-specific')),
    ]
    SCOPE_SCHOOL_WIDE = 'SCHOOL_WIDE'
    SCOPE_LEVEL = 'LEVEL'
    SCOPE_CLASS = 'CLASS'
    SCOPE_CHOICES = [
        (SCOPE_SCHOOL_WIDE, _('School-wide')),
        (SCOPE_LEVEL, _('Level/Grade')),
        (SCOPE_CLASS, _('Class-specific')),
    ]

    category = models.ForeignKey(
        FeeCategory,
        on_delete=models.CASCADE,
        verbose_name=_('category'),
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_('amount'),
    )
    term = models.ForeignKey(
        'core.Term',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_('term'),
        help_text=_('Leave blank for one-time fees.'),
    )
    student_type = models.CharField(
        max_length=20,
        choices=FeeCategory.STUDENT_TYPE_CHOICES,
        default='ALL',
        verbose_name=_('student type'),
        help_text=_('Which students this price applies to.'),
    )
    scope = models.CharField(
        max_length=20,
        choices=SCOPE_CHOICES,
        default=SCOPE_CLASS,
        verbose_name=_('scope'),
    )
    school_class = models.ForeignKey(
        'students.SchoolClass',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_('school class'),
    )
    level = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_('level'),
        help_text=_('Level code for LEVEL-scoped prices, e.g. JSS, PRIMARY.'),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_('active'),
        help_text=_('Inactive prices are ignored during resolution.'),
    )
    effective_from = models.DateField(
        null=True,
        blank=True,
        verbose_name=_('effective from'),
        help_text=_('Leave blank to apply immediately.'),
    )
    effective_to = models.DateField(
        null=True,
        blank=True,
        verbose_name=_('effective to'),
        help_text=_('Leave blank for no expiry.'),
    )

    class Meta:
        verbose_name = _('fee price')
        verbose_name_plural = _('fee prices')
        unique_together = ('school', 'scope', 'school_class', 'level', 'term', 'category', 'student_type')
        ordering = ['scope', 'school_class', 'level', 'category']

    def __str__(self):
        if self.scope == self.SCOPE_SCHOOL_WIDE:
            scope_label = 'School-wide'
        elif self.scope == self.SCOPE_LEVEL:
            scope_label = f'Level {self.level}'
        else:
            scope_label = str(self.school_class)
        return f'{scope_label} - {self.term or "One-time"} - {self.category}: {self.amount}'

    def clean(self):
        if self.scope == self.SCOPE_CLASS and not self.school_class_id:
            raise ValidationError({'school_class': _('Class-specific prices require a class.')})
        if self.scope == self.SCOPE_LEVEL and not self.level:
            raise ValidationError({'level': _('Level-scoped prices require a level.')})
        if self.scope == self.SCOPE_SCHOOL_WIDE and (self.school_class_id or self.level):
            raise ValidationError(_('School-wide prices must not have a class or level.'))

        category = self.category
        if category.billing_cycle == 'PER_TERM' and not self.term_id:
            raise ValidationError({'term': _('Per-term categories require a term.')})
        if category.billing_cycle == 'ONE_TIME' and self.term_id:
            raise ValidationError({'term': _('One-time categories must not have a term.')})

        if self.amount <= Decimal('0.00'):
            raise ValidationError({'amount': _('Amount must be greater than 0.')})

        today = timezone.now().date()
        if self.effective_from and self.effective_to and self.effective_from > self.effective_to:
            raise ValidationError({'effective_from': _('Effective from must be before effective to.')})

        qs = FeePrice.objects.filter(
            school=self.school,
            scope=self.scope,
            school_class=self.school_class,
            level=self.level,
            term=self.term,
            category=category,
            student_type=self.student_type,
        )
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        if qs.exists():
            raise ValidationError(
                _('A fee price already exists for this school, scope, class/level, term, category, and student type.')
            )


class FeeStructure(TenantScopedModel):
    """DEPRECATED compatibility shim. Use FeePrice for new code.

    Phase 5: FeeStructure is kept as a thin wrapper around FeePrice for
    backward compatibility with existing tests, fixtures, and admin
    registrations. New code should use FeePrice directly. This model is
    not actively written to; the migration that copies data into FeePrice
    ran in phase 2 and the table is now effectively read-only legacy.
    """
    SCOPE_CLASS = 'CLASS'
    SCOPE_SCHOOL_WIDE = 'SCHOOL_WIDE'
    SCOPE_CHOICES = [
        (SCOPE_CLASS, _('Class-specific')),
        (SCOPE_SCHOOL_WIDE, _('School-wide (all classes)')),
    ]

    scope = models.CharField(
        max_length=20,
        choices=SCOPE_CHOICES,
        default=SCOPE_CLASS,
    )
    school_class = models.ForeignKey(
        'students.SchoolClass',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    term = models.ForeignKey(
        'core.Term',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    category = models.ForeignKey(
        FeeCategory,
        on_delete=models.CASCADE,
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    student_type = models.CharField(
        max_length=20,
        choices=FeeCategory.STUDENT_TYPE_CHOICES,
        default='ALL',
    )
    is_recurring_override = models.BooleanField(null=True, blank=True)
    deprecated = models.BooleanField(
        default=True,
        help_text='Always true: this model is the legacy compatibility shim for FeePrice.',
    )

    class Meta:
        verbose_name = 'fee structure (legacy)'
        verbose_name_plural = 'fee structures (legacy)'
        unique_together = ('school', 'scope', 'school_class', 'term', 'category', 'student_type')
        ordering = ['school_class', 'category']

    def __str__(self):
        scope_label = 'School-wide' if self.scope == self.SCOPE_SCHOOL_WIDE else str(self.school_class)
        return f'{scope_label} - {self.term or "One-time"} - {self.category}: {self.amount}'

    def save(self, *args, **kwargs):
        self.deprecated = True
        super().save(*args, **kwargs)


class FeePriceOverride(TenantScopedModel):
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        related_name='fee_price_overrides',
        verbose_name=_('student'),
    )
    category = models.ForeignKey(
        FeeCategory,
        on_delete=models.CASCADE,
        verbose_name=_('category'),
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_('amount'),
    )
    reason = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_('reason'),
        help_text=_('Optional reason for the override.'),
    )
    valid_from = models.DateField(
        verbose_name=_('valid from'),
        help_text=_('Override applies from this date.'),
    )
    valid_to = models.DateField(
        verbose_name=_('valid to'),
        help_text=_('Override applies until this date. Leave far future for permanent.'),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_('active'),
        help_text=_('Inactive overrides are ignored.'),
    )

    class Meta:
        verbose_name = _('fee price override')
        verbose_name_plural = _('fee price overrides')
        ordering = ['-valid_from', 'category__name']
        unique_together = ('school', 'student', 'category', 'valid_from', 'valid_to')

    def __str__(self):
        return f'{self.student} - {self.category}: {self.amount} ({self.valid_from} to {self.valid_to})'

    def clean(self):
        if self.amount <= Decimal('0.00'):
            raise ValidationError({'amount': _('Amount must be greater than 0.')})
        if self.valid_to < self.valid_from:
            raise ValidationError({'valid_to': _('Valid to must be after valid from.')})


class Invoice(TenantScopedModel):
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        related_name='invoices',
        verbose_name=_('student'),
    )
    term = models.ForeignKey(
        'core.Term',
        on_delete=models.CASCADE,
        verbose_name=_('term'),
    )
    generated_on = models.DateTimeField(auto_now_add=True, verbose_name=_('generated on'))
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name=_('total amount'),
    )

    class Meta:
        verbose_name = _('invoice')
        verbose_name_plural = _('invoices')
        unique_together = ('school', 'student', 'term')
        ordering = ['-generated_on']

    def __str__(self):
        return f'{self.student} - {self.term} ({self.total_amount})'

    @property
    def amount_paid(self) -> Decimal:
        """Sum of CONFIRMED payments only — PENDING/FAILED never count."""
        from django.db.models import Q, Sum
        result = self.payments.filter(
            Q(status=Payment.Status.CONFIRMED)
        ).aggregate(total=Sum('amount'))['total']
        return result or Decimal('0.00')

    @property
    def balance(self) -> Decimal:
        """Outstanding amount (total minus confirmed payments)."""
        return self.total_amount - self.amount_paid

    @property
    def status(self) -> str:
        """One of PAID / PARTIAL / UNPAID based on the confirmed balance."""
        if self.balance <= 0:
            return 'PAID'
        elif self.amount_paid > 0:
            return 'PARTIAL'
        return 'UNPAID'

    @classmethod
    def owes_for_term(cls, student, term) -> bool:
        """True when the student has any invoice for the term with a balance left.

        Students with no invoice at all for the term owe nothing, so they are
        not locked out. Used to gate result booklet access per term.
        Delegates to the central service so the rule lives in one place.
        """
        from .selectors import owed_term_ids
        return term.pk in owed_term_ids(student)


class InvoiceLineItem(models.Model):
    school = models.ForeignKey(
        'core.School',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_('school'),
    )
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name='line_items',
        verbose_name=_('invoice'),
    )
    category = models.ForeignKey(
        FeeCategory,
        on_delete=models.CASCADE,
        verbose_name=_('category'),
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_('amount'),
    )
    term = models.ForeignKey(
        'core.Term',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_('term'),
    )
    session = models.ForeignKey(
        'core.AcademicSession',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_('session'),
    )
    billing_cycle = models.CharField(
        max_length=20,
        choices=FeeCategory.BILLING_CYCLE_CHOICES,
        default='PER_TERM',
        verbose_name=_('billing cycle'),
    )

    class Meta:
        verbose_name = _('invoice line item')
        verbose_name_plural = _('invoice line items')
        ordering = ['id']

    def __str__(self):
        return f'{self.category}: {self.amount}'

    def clean(self):
        if self.amount <= Decimal('0.00'):
            raise ValidationError({'amount': _('Amount must be greater than 0.')})


class Payment(TenantScopedModel):
    class Method(models.TextChoices):
        CASH = 'CASH', _('Cash')
        BANK_TRANSFER = 'BANK_TRANSFER', _('Bank Transfer')
        POS = 'POS', _('POS / Card at school')
        CHEQUE = 'CHEQUE', _('Cheque')
        CARD = 'CARD', _('Card')
        USSD = 'USSD', _('USSD')
        PAYSTACK = 'PAYSTACK', _('Paystack')
        OTHER = 'OTHER', _('Other')

    class Status(models.TextChoices):
        PENDING = 'PENDING', _('Pending')
        CONFIRMED = 'CONFIRMED', _('Confirmed')
        FAILED = 'FAILED', _('Failed')

    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='payments',
        verbose_name=_('invoice'),
    )
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='payments',
        verbose_name=_('student'),
    )
    lesson_enrollment = models.ForeignKey(
        'lessons.LessonEnrollment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments',
        verbose_name=_('lesson enrollment'),
    )
    description = models.CharField(max_length=255, blank=True, default='', verbose_name=_('description'))
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
        blank=True,
        null=True,
        verbose_name=_('reference'),
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name=_('status'),
    )
    paid_on = models.DateTimeField(verbose_name=_('paid on'))
    recorded_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_('recorded by'),
    )
    authorization_url = models.URLField(blank=True, max_length=500, verbose_name=_('authorization url'))
    access_code = models.CharField(max_length=100, blank=True, default='', verbose_name=_('access code'))
    fees_charged = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name=_('fees charged'),
    )
    channel = models.CharField(max_length=30, blank=True, default='', verbose_name=_('channel'))
    currency = models.CharField(max_length=3, default='NGN', verbose_name=_('currency'))
    paid_by_email = models.EmailField(blank=True, default='', verbose_name=_('paid by email'))
    paid_by_name = models.CharField(max_length=200, blank=True, default='', verbose_name=_('paid by name'))
    paid_by_relation = models.CharField(max_length=100, blank=True, default='', verbose_name=_('paid by relation'))
    paid_by_phone = models.CharField(max_length=20, blank=True, default='', verbose_name=_('paid by phone'))
    proof_image = models.FileField(
        upload_to='fees/proofs/%Y/%m/',
        blank=True,
        null=True,
        verbose_name=_('transfer proof'),
        help_text=_('Screenshot or receipt image proving a bank transfer.'),
        validators=[validate_proof_file],
    )
    card_last4 = models.CharField(max_length=4, blank=True, default='', verbose_name=_('card last 4'))
    card_brand = models.CharField(max_length=50, blank=True, default='', verbose_name=_('card brand'))
    bank_name = models.CharField(max_length=100, blank=True, default='', verbose_name=_('bank name'))
    initiated_at = models.DateTimeField(null=True, blank=True, verbose_name=_('initiated at'))
    verified_at = models.DateTimeField(null=True, blank=True, verbose_name=_('verified at'))
    webhook_processed = models.BooleanField(default=False, verbose_name=_('webhook processed'))
    webhook_payload = models.JSONField(default=dict, blank=True, verbose_name=_('webhook payload'))
    confirmed_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name=_('confirmed by'),
    )
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name=_('confirmed at'))

    class Meta:
        verbose_name = _('payment')
        verbose_name_plural = _('payments')
        unique_together = ('school', 'reference')
        ordering = ['-paid_on']

    def __str__(self):
        return f'{self.invoice} - {self.amount} ({self.get_status_display()})'

    # Legal status transitions. A payment is created in its initial state
    # (PENDING, or CONFIRMED/FAILED for already-settled flows) and may only
    # move forward along these edges — never backwards, never sideways.
    ALLOWED_STATUS_TRANSITIONS = {
        Status.PENDING: {Status.CONFIRMED, Status.FAILED},
    }

    def clean(self):
        """Constraint: Paystack payments must carry their reference."""
        if self.method == self.Method.PAYSTACK and not self.reference:
            raise ValidationError({'reference': _('Reference is required for Paystack payments.')})

    def save(self, *args, **kwargs):
        # Constraint: legal status transitions only (PENDING -> CONFIRMED/FAILED).
        # Field validation is the job of forms/views via full_clean().
        if self.pk:
            previous = (
                Payment.objects.filter(pk=self.pk)
                .values_list('status', flat=True)
                .first()
            )
            if (
                previous is not None
                and previous != self.status
                and self.status not in self.ALLOWED_STATUS_TRANSITIONS.get(previous, set())
            ):
                raise ValidationError(
                    _('Invalid payment status transition: %(previous)s -> %(new)s')
                    % {'previous': previous, 'new': self.status}
                )
        super().save(*args, **kwargs)


class WebhookLog(TenantScopedModel):
    event = models.CharField(max_length=50, verbose_name=_('event'))
    payload = models.JSONField(verbose_name=_('payload'))
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name=_('ip address'))
    processed = models.BooleanField(default=False, verbose_name=_('processed'))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('created at'))

    class Meta:
        verbose_name = _('webhook log')
        verbose_name_plural = _('webhook logs')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.event} {self.created_at}'


class FeeReceipt(TenantScopedModel):
    receipt_number = models.CharField(max_length=50, verbose_name=_('receipt number'))
    payment = models.OneToOneField(
        'fees.Payment',
        on_delete=models.CASCADE,
        related_name='receipt',
        verbose_name=_('payment'),
    )
    issued_at = models.DateTimeField(auto_now_add=True, verbose_name=_('issued at'))

    class Meta:
        verbose_name = _('fee receipt')
        verbose_name_plural = _('fee receipts')
        unique_together = ('school', 'receipt_number')
        ordering = ['-issued_at']

    def __str__(self):
        return self.receipt_number


class InvoiceResetLog(TenantScopedModel):
    class ResetScope(models.TextChoices):
        TERM = 'TERM', _('Term')
        CLASS = 'CLASS', _('Class')
        STUDENT = 'STUDENT', _('Student')
        SCHOOL = 'SCHOOL', _('School-wide')

    scope_type = models.CharField(max_length=20, choices=ResetScope.choices, verbose_name=_('scope type'))
    scope_id = models.PositiveIntegerField(verbose_name=_('scope id'))
    scope_name = models.CharField(max_length=200, verbose_name=_('scope name'))
    reset_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_('reset by'),
    )
    reason = models.TextField(blank=True, verbose_name=_('reason'))
    invoices_deleted = models.PositiveIntegerField(default=0, verbose_name=_('invoices deleted'))
    payments_deleted = models.PositiveIntegerField(default=0, verbose_name=_('payments deleted'))
    line_items_deleted = models.PositiveIntegerField(default=0, verbose_name=_('line items deleted'))
    receipts_deleted = models.PositiveIntegerField(default=0, verbose_name=_('receipts deleted'))
    performed_at = models.DateTimeField(auto_now_add=True, verbose_name=_('performed at'))

    class Meta:
        verbose_name = _('invoice reset log')
        verbose_name_plural = _('invoice reset logs')
        ordering = ['-performed_at']

    def __str__(self):
        return f'{self.get_scope_type_display()} reset: {self.scope_name} ({self.performed_at:%Y-%m-%d %H:%M})'


class FeeValidationError(TenantScopedModel):
    class ErrorCode(models.TextChoices):
        NEGATIVE_AMOUNT = 'NEGATIVE_AMOUNT', _('Negative amount')
        DUPLICATE_STRUCTURE = 'DUPLICATE_STRUCTURE', _('Duplicate fee structure')
        MISMATCHED_TOTAL = 'MISMATCHED_TOTAL', _('Invoice total != sum of line items')
        MISSING_COMPULSORY = 'MISSING_COMPULSORY', _('Missing compulsory category')
        ONE_TIME_REBILL = 'ONE_TIME_REBILL', _('One-time fee rebilled to same student')
        INVALID_STUDENT_TYPE = 'INVALID_STUDENT_TYPE', _('Invalid student type for category')

    code = models.CharField(max_length=50, choices=ErrorCode.choices, verbose_name=_('code'))
    message = models.TextField(verbose_name=_('message'))
    related_object_type = models.CharField(max_length=50, blank=True, verbose_name=_('related object type'))
    related_object_id = models.PositiveIntegerField(null=True, blank=True, verbose_name=_('related object id'))
    is_resolved = models.BooleanField(default=False, verbose_name=_('resolved'))
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name=_('resolved at'))
    resolved_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_('resolved by'),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('created at'))

    class Meta:
        verbose_name = _('fee validation error')
        verbose_name_plural = _('fee validation errors')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.code}: {self.message[:80]}'


class PaymentLineItem(models.Model):
    KIND_OUTSTANDING = 'outstanding'
    KIND_EXTRA = 'extra'
    KIND_NEXT = 'next'
    KIND_CHOICES = [
        (KIND_OUTSTANDING, _('Outstanding')),
        (KIND_EXTRA, _('Extra')),
        (KIND_NEXT, _('Next term')),
    ]

    payment = models.ForeignKey(
        'fees.Payment',
        on_delete=models.CASCADE,
        related_name='line_items',
        verbose_name=_('payment'),
    )
    school = models.ForeignKey(
        'core.School',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_('school'),
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, verbose_name=_('kind'))
    label = models.CharField(max_length=255, verbose_name=_('label'))
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name=_('amount'))
    source_key = models.CharField(max_length=100, verbose_name=_('source key'))
    category = models.ForeignKey(
        'fees.FeeCategory',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_('category'),
    )
    term = models.ForeignKey(
        'core.Term',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_('term'),
    )
    session = models.ForeignKey(
        'core.AcademicSession',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_('session'),
    )
    invoice = models.ForeignKey(
        'fees.Invoice',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_('invoice'),
    )

    class Meta:
        verbose_name = _('payment line item')
        verbose_name_plural = _('payment line items')
        ordering = ['id']

    def __str__(self):
        return f'{self.kind}: {self.label} — ₦{self.amount:,.2f}'
