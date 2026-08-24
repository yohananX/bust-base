"""Extra Lessons / Summer School module.

Self-contained registration stream for holiday programmes. Admin-centric:
teachers get a read-only view of their assigned classes; students/parents
have no portal in v1. External (non-school) children are first-class via
the ``external_*`` fields on ``LessonEnrollment``.
"""
from decimal import Decimal

from django.db import models
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from core.models import TenantScopedModel
from accounts.models import Roles


class LessonPeriod(TenantScopedModel):
    """A holiday programme window, e.g. "Summer School 2026"."""

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', _('Draft')
        OPEN = 'OPEN', _('Open')
        CLOSED = 'CLOSED', _('Closed')

    name = models.CharField(max_length=200, verbose_name=_('name'))
    start_date = models.DateField(verbose_name=_('start date'))
    end_date = models.DateField(verbose_name=_('end date'))
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name=_('status'),
    )
    description = models.TextField(blank=True, verbose_name=_('description'))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('created at'))

    class Meta:
        verbose_name = _('lesson period')
        verbose_name_plural = _('lesson periods')
        ordering = ['-start_date']
        unique_together = ('school', 'name')

    def __str__(self):
        return self.name


class LessonClass(TenantScopedModel):
    """A class inside a period with a fixed, admin-editable fee."""

    period = models.ForeignKey(
        LessonPeriod,
        on_delete=models.CASCADE,
        related_name='lesson_classes',
        verbose_name=_('period'),
    )
    name = models.CharField(max_length=200, verbose_name=_('name'))
    level_hint = models.CharField(
        max_length=100, blank=True, verbose_name=_('level / grade hint'),
    )
    capacity = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_('capacity'),
    )
    fee_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        verbose_name=_('fee amount'),
    )
    notes = models.TextField(blank=True, verbose_name=_('notes'))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('created at'))

    class Meta:
        verbose_name = _('lesson class')
        verbose_name_plural = _('lesson classes')
        ordering = ['period', 'name']
        unique_together = ('school', 'period', 'name')

    def __str__(self):
        return f'{self.name} ({self.period.name})'

    @property
    def teachers(self):
        return [
            a.teacher for a in self.teacher_assignments.select_related('teacher').all()
        ]


class LessonTeacherAssignment(TenantScopedModel):
    """Assigns a teacher (an accounts.User with role TEACHER) to a LessonClass."""

    lesson_class = models.ForeignKey(
        LessonClass,
        on_delete=models.CASCADE,
        related_name='teacher_assignments',
        verbose_name=_('lesson class'),
    )
    teacher = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='lesson_assignments',
        verbose_name=_('teacher'),
        limit_choices_to={'role': Roles.TEACHER},
    )

    class Meta:
        verbose_name = _('lesson teacher assignment')
        verbose_name_plural = _('lesson teacher assignments')
        unique_together = ('school', 'lesson_class', 'teacher')

    def __str__(self):
        return f'{self.teacher.get_full_name() or self.teacher.username} → {self.lesson_class}'


class LessonEnrollment(TenantScopedModel):
    """One child's registration for a LessonClass.

    Mirrors the paper Summer School Registration Form. A child is either a
    linked existing Student or an external (walk-in) child via ``external_*``.
    """

    class Status(models.TextChoices):
        REGISTERED = 'REGISTERED', _('Registered')
        PAID = 'PAID', _('Paid')
        CANCELLED = 'CANCELLED', _('Cancelled')

    class Source(models.TextChoices):
        REFERRAL = 'REFERRAL', _('Referral')
        SOCIAL_MEDIA = 'SOCIAL_MEDIA', _('Social Media')
        CHURCH = 'CHURCH', _('Church / Community')
        SCHOOL_STAFF = 'SCHOOL_STAFF', _('School Staff')
        OTHER = 'OTHER', _('Other')

    class Relationship(models.TextChoices):
        FATHER = 'FATHER', _('Father')
        MOTHER = 'MOTHER', _('Mother')
        GUARDIAN = 'GUARDIAN', _('Guardian')
        OTHER = 'OTHER', _('Other')

    lesson_class = models.ForeignKey(
        LessonClass,
        on_delete=models.CASCADE,
        related_name='enrollments',
        verbose_name=_('lesson class'),
    )

    # Child: link an existing student OR capture an external child.
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lesson_enrollments',
        verbose_name=_('linked student'),
    )
    external_name = models.CharField(
        max_length=200, blank=True, verbose_name=_('external child full name'),
    )
    age = models.PositiveIntegerField(
        null=True, blank=True, verbose_name=_('age'),
    )
    current_class_text = models.CharField(
        max_length=100, blank=True, verbose_name=_('current class / grade'),
    )

    # Parent / guardian.
    parent_name = models.CharField(max_length=200, verbose_name=_('parent full name'))
    parent_phone = models.CharField(max_length=30, verbose_name=_('parent phone number'))
    emergency_contact = models.CharField(
        max_length=200, blank=True, verbose_name=_('emergency contact'),
    )
    relationship = models.CharField(
        max_length=20,
        choices=Relationship.choices,
        default=Relationship.GUARDIAN,
        verbose_name=_('relationship to child'),
    )

    # Learning goals / marketing.
    learning_goals = models.TextField(blank=True, verbose_name=_('learning goals / needs'))
    referral_notes = models.TextField(blank=True, verbose_name=_('referral notes'))
    source = models.CharField(
        max_length=30,
        choices=Source.choices,
        default=Source.OTHER,
        verbose_name=_('how did you hear about us?'),
    )

    # Consent.
    consent_given = models.BooleanField(default=False, verbose_name=_('parent consent given'))
    consent_date = models.DateField(null=True, blank=True, verbose_name=_('consent date'))

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.REGISTERED,
        verbose_name=_('status'),
    )
    registered_on = models.DateTimeField(auto_now_add=True, verbose_name=_('registered on'))

    class Meta:
        verbose_name = _('lesson enrollment')
        verbose_name_plural = _('lesson enrollments')
        ordering = ['-registered_on']

    def __str__(self):
        return self.child_name

    @property
    def child_name(self):
        if self.student:
            return self.student.user.get_full_name() or self.student.user.username
        return self.external_name or '(external child)'

    @property
    def fee_amount(self):
        return self.lesson_class.fee_amount

    @property
    def amount_paid(self):
        total = self.payments.filter(
            status='CONFIRMED',
        ).aggregate(total=Sum('amount'))['total']
        return total or Decimal('0.00')

    @property
    def payment_status(self):
        """One of PAID / PARTIAL / UNPAID based on confirmed payments."""
        paid = self.amount_paid
        if paid >= self.fee_amount:
            return 'PAID'
        if paid > 0:
            return 'PARTIAL'
        return 'UNPAID'