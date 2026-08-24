from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from core.models import TenantScopedModel
from fees.validators import validate_proof_file


class FeeCategory(TenantScopedModel):
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

    class Meta:
        verbose_name = _('fee category')
        verbose_name_plural = _('fee categories')
        ordering = ['name']

    def __str__(self):
        return self.name


class FeeStructure(TenantScopedModel):
    school_class = models.ForeignKey(
        'students.SchoolClass',
        on_delete=models.CASCADE,
        verbose_name=_('school class'),
    )
    term = models.ForeignKey(
        'core.Term',
        on_delete=models.CASCADE,
        verbose_name=_('term'),
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

    class Meta:
        verbose_name = _('fee structure')
        verbose_name_plural = _('fee structures')
        unique_together = ('school', 'school_class', 'term', 'category')
        ordering = ['school_class', 'category']

    def __str__(self):
        return f'{self.school_class} - {self.term} - {self.category}: {self.amount}'


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

    class Meta:
        verbose_name = _('invoice line item')
        verbose_name_plural = _('invoice line items')

    def __str__(self):
        return f'{self.category}: {self.amount}'


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
    description = models.CharField(
        max_length=255, blank=True, default='', verbose_name=_('description')
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
    authorization_url = models.URLField(
        blank=True, max_length=500, verbose_name=_('authorization url')
    )
    access_code = models.CharField(
        max_length=100, blank=True, default='', verbose_name=_('access code')
    )
    fees_charged = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name=_('fees charged'),
    )
    channel = models.CharField(
        max_length=30, blank=True, default='', verbose_name=_('channel')
    )
    currency = models.CharField(
        max_length=3, default='NGN', verbose_name=_('currency')
    )
    paid_by_email = models.EmailField(
        blank=True, default='', verbose_name=_('paid by email')
    )
    paid_by_name = models.CharField(
        max_length=200, blank=True, default='', verbose_name=_('paid by name')
    )
    paid_by_relation = models.CharField(
        max_length=100, blank=True, default='', verbose_name=_('paid by relation')
    )
    paid_by_phone = models.CharField(
        max_length=20, blank=True, default='', verbose_name=_('paid by phone')
    )
    proof_image = models.FileField(
        upload_to='fees/proofs/%Y/%m/',
        blank=True,
        null=True,
        verbose_name=_('transfer proof'),
        help_text=_('Screenshot or receipt image proving a bank transfer.'),
        validators=[validate_proof_file],
    )
    card_last4 = models.CharField(
        max_length=4, blank=True, default='', verbose_name=_('card last 4')
    )
    card_brand = models.CharField(
        max_length=50, blank=True, default='', verbose_name=_('card brand')
    )
    bank_name = models.CharField(
        max_length=100, blank=True, default='', verbose_name=_('bank name')
    )
    initiated_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_('initiated at')
    )
    verified_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_('verified at')
    )
    webhook_processed = models.BooleanField(
        default=False, verbose_name=_('webhook processed')
    )
    webhook_payload = models.JSONField(
        default=dict, blank=True, verbose_name=_('webhook payload')
    )
    confirmed_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name=_('confirmed by'),
    )
    confirmed_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_('confirmed at')
    )

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
    ip_address = models.GenericIPAddressField(
        null=True, blank=True, verbose_name=_('ip address')
    )
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
