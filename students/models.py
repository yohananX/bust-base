from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower, Trim
from django.utils.translation import gettext_lazy as _

from core.models import TenantScopedModel
from accounts.models import Roles


class AcademicStage(TenantScopedModel):
    """School-defined academic stage (e.g. 'Pre-Nursery', 'Primary', 'JSS', 'SSS')."""

    name = models.CharField(max_length=100, verbose_name=_('name'))
    display_order = models.PositiveIntegerField(default=0, verbose_name=_('display order'))
    is_active = models.BooleanField(default=True, verbose_name=_('active'))

    class Meta:
        verbose_name = _('academic stage')
        verbose_name_plural = _('academic stages')
        unique_together = ('school', 'name')
        ordering = ['display_order', 'name']
        constraints = [
            # School-scoped, case-insensitive uniqueness after trimming outer
            # whitespace. ``unique_together`` alone only catches exact matches.
            models.UniqueConstraint(
                Lower(Trim('name')),
                'school',
                name='uniq_academicstage_school_normalized_name',
            ),
        ]

    def __str__(self):
        return self.name

    @staticmethod
    def normalize_name(name):
        """Canonical display form: trim outer and collapse internal whitespace.

        Case is preserved for display; uniqueness is case-insensitive.
        """
        return ' '.join((name or '').split())

    def clean(self):
        super().clean()
        self.name = self.normalize_name(self.name)
        if AcademicStage.objects.filter(
            school=self.school,
            name__iexact=self.name,
        ).exclude(pk=self.pk).exists():
            raise ValidationError({'name': _('An academic stage with this name already exists for this school.')})

    def save(self, *args, **kwargs):
        # Normalize on every write path, including ``objects.create()``.
        self.name = self.normalize_name(self.name)
        super().save(*args, **kwargs)


class SchoolClass(TenantScopedModel):
    """A class as a stable entity (e.g. 'JSS1A'), independent of academic year."""

    name = models.CharField(max_length=100, verbose_name=_('name'))
    level = models.CharField(
        max_length=100,
        verbose_name=_('level'),
        help_text=_('e.g. "JSS1", "Primary 3" — used for grouping/reporting (legacy field, will be replaced by academic_stage)'),
    )
    academic_stage = models.ForeignKey(
        'AcademicStage',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='classes',
        verbose_name=_('academic stage'),
        help_text=_('The academic stage this class belongs to. Required after migration backfill.'),
    )
    is_active = models.BooleanField(default=True, verbose_name=_('active'))

    class Meta:
        verbose_name = _('school class')
        verbose_name_plural = _('school classes')
        unique_together = ('school', 'name')
        ordering = ['academic_stage__display_order', 'level', 'name']

    def __str__(self):
        return self.name

    def _validate_academic_stage_school(self):
        """Reject a stage from another tenant.

        ``clean()`` is not called by ``objects.create()``/``save()``, so the
        same guard is applied on write. Bulk operations (``bulk_create``,
        ``QuerySet.update``) still bypass it; cross-table tenant consistency
        cannot be expressed as a single-table database constraint.
        """
        if not self.academic_stage_id:
            return
        try:
            stage_school_id = self.academic_stage.school_id
        except AcademicStage.DoesNotExist:
            raise ValidationError(
                {'academic_stage': _('Select a valid academic stage.')}
            )
        if stage_school_id != self.school_id:
            raise ValidationError({'academic_stage': _('Academic stage must belong to the same school as the class.')})

    def clean(self):
        super().clean()
        self._validate_academic_stage_school()

    def save(self, *args, **kwargs):
        self._validate_academic_stage_school()
        super().save(*args, **kwargs)


class Student(TenantScopedModel):
    """Profile record for a student user."""

    MALE = 'MALE'
    FEMALE = 'FEMALE'
    GENDER_CHOICES = [
        (MALE, _('Male')),
        (FEMALE, _('Female')),
    ]

    ACTIVE = 'ACTIVE'
    GRADUATED = 'GRADUATED'
    WITHDRAWN = 'WITHDRAWN'
    SUSPENDED = 'SUSPENDED'
    STATUS_CHOICES = [
        (ACTIVE, _('Active')),
        (GRADUATED, _('Graduated')),
        (WITHDRAWN, _('Withdrawn')),
        (SUSPENDED, _('Suspended')),
    ]

    user = models.OneToOneField(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='student_profile',
        limit_choices_to={'role': Roles.STUDENT},
        verbose_name=_('user'),
    )
    admission_number = models.CharField(max_length=50, verbose_name=_('admission number'))
    date_of_birth = models.DateField(verbose_name=_('date of birth'))
    gender = models.CharField(
        max_length=10,
        choices=GENDER_CHOICES,
        verbose_name=_('gender'),
    )
    admission_date = models.DateField(verbose_name=_('admission date'))
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=ACTIVE,
        verbose_name=_('status'),
    )
    passport = models.ImageField(
        upload_to='passports/',
        blank=True,
        verbose_name=_('passport'),
    )
    state_of_origin = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_('state of origin'),
    )
    local_government_area = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_('local government area (L.G.A.)'),
    )
    registration_paid_term = models.ForeignKey(
        'core.Term',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='registration_paid_students',
        verbose_name=_('registration paid term'),
        help_text=_('The term in which the student paid the one-time Registration Form fee. '
                     'Once set, the student is treated as RETURNING for subsequent terms even '
                     'if their first ClassEnrollment is in the current session.'),
    )
    student_type = models.CharField(
        max_length=20,
        choices=[
            ('NEW', _('New')),
            ('RETURNING', _('Returning')),
        ],
        default='NEW',
        verbose_name=_('student type'),
        help_text=_('NEW = first year onboarding applies (Registration, Uniforms, PTA, etc.). '
                     'Auto-flips to RETURNING after the Registration Form fee is paid.'),
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        db_index=True,
        verbose_name=_('updated at'),
    )

    class Meta:
        verbose_name = _('student')
        verbose_name_plural = _('students')
        unique_together = ('school', 'admission_number')

    def __str__(self):
        name = self.user.get_full_name() or self.user.username
        try:
            current_enrollment = self.enrollments.filter(is_current=True).first()
            if current_enrollment:
                return f"{name} ({current_enrollment.school_class.name})"
        except Exception:
            pass
        return name

    def display_name_with_class(self):
        """Full name plus current class, when available.

        Falls back to just the name when no current enrollment exists or the
        relation has not been prefetched. Callers that need the class should
        prefetch ``enrollments__school_class`` to avoid N+1 queries.
        """
        name = self.user.get_full_name() or self.user.username
        try:
            current_enrollment = self.enrollments.filter(is_current=True).first()
            if current_enrollment:
                return f"{name} ({current_enrollment.school_class.name})"
        except Exception:
            pass
        return name

    @property
    def middle_name(self):
        """Delegate to linked User's middle_name."""
        return self.user.middle_name

    def clean(self):
        """Constraint: the linked user must have role=STUDENT."""
        if self.user_id and self.user.role != Roles.STUDENT:
            raise ValidationError({
                'user': _('The selected user must have the role "Student".'),
            })

    def save(self, *args, **kwargs):
        # Constraint validation happens via full_clean() at the form/view boundary.
        super().save(*args, **kwargs)

    def promote_to(self, session, school_class):
        """Create a new ClassEnrollment for this student in the given session and class.

        Returns the new ClassEnrollment instance.
        """
        enrollment = ClassEnrollment.objects.create(
            school=self.school,
            student=self,
            school_class=school_class,
            session=session,
            is_current=True,
        )
        return enrollment


class ClassEnrollment(TenantScopedModel):
    """Records which class a student was in during a given academic session."""

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='enrollments',
        verbose_name=_('student'),
    )
    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.CASCADE,
        related_name='enrollments',
        verbose_name=_('class'),
    )
    session = models.ForeignKey(
        'core.AcademicSession',
        on_delete=models.CASCADE,
        verbose_name=_('academic session'),
    )
    enrolled_on = models.DateField(auto_now_add=True, verbose_name=_('enrolled on'))
    is_current = models.BooleanField(default=True, verbose_name=_('current'))

    class Meta:
        verbose_name = _('class enrollment')
        verbose_name_plural = _('class enrollments')
        unique_together = ('student', 'session')
        ordering = ['-session__start_date']

    def __str__(self):
        return f"{self.student} → {self.school_class.name} ({self.session.name})"

    def save(self, *args, **kwargs):
        if self.is_current:
            ClassEnrollment.objects.filter(
                student=self.student, is_current=True
            ).exclude(pk=self.pk).update(is_current=False)
        super().save(*args, **kwargs)


class StudentGuardianLink(TenantScopedModel):
    """Links a parent/guardian user to a student with relationship metadata."""

    FATHER = 'FATHER'
    MOTHER = 'MOTHER'
    GUARDIAN = 'GUARDIAN'
    OTHER = 'OTHER'
    RELATIONSHIP_CHOICES = [
        (FATHER, _('Father')),
        (MOTHER, _('Mother')),
        (GUARDIAN, _('Guardian')),
        (OTHER, _('Other')),
    ]

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='guardian_links',
        verbose_name=_('student'),
    )
    guardian = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='student_links',
        limit_choices_to={'role': Roles.PARENT},
        verbose_name=_('guardian'),
    )
    relationship = models.CharField(
        max_length=20,
        choices=RELATIONSHIP_CHOICES,
        verbose_name=_('relationship'),
    )
    is_primary_contact = models.BooleanField(default=False, verbose_name=_('primary contact'))
    occupation = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_('guardian occupation'),
    )
    address = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_('guardian address'),
    )
    authorized_pickup_person = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_('authorized person for after-school pick-up'),
    )
    other_phones = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_('other phone numbers'),
        help_text=_('Additional contact numbers as a JSON list of strings.'),
    )

    class Meta:
        verbose_name = _('student-guardian link')
        verbose_name_plural = _('student-guardian links')
        unique_together = ('student', 'guardian')

    def __str__(self):
        student_name = self.student.user.get_full_name() or self.student.user.username
        rel_display = self.get_relationship_display()
        return f"{student_name}'s {rel_display.lower()}"

    @property
    def middle_name(self):
        """Delegate to linked guardian User's middle_name."""
        return self.guardian.middle_name

    def clean(self):
        """Constraint: the linked user must have role=PARENT."""
        if self.guardian_id and self.guardian.role != Roles.PARENT:
            raise ValidationError({
                'guardian': _('The selected user must have the role "Parent".'),
            })

    def save(self, *args, **kwargs):
        # Constraint validation happens via full_clean() at the form/view boundary.
        super().save(*args, **kwargs)
