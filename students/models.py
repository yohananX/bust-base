from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower, Trim
from django.utils.translation import gettext_lazy as _

from core.models import AcademicSession, TenantScopedModel
from accounts.models import Roles


def _validate_progression_edge(instance, field_name, label):
    """Validate one tenant-scoped self-referencing progression edge.

    Self references and longer cycles cannot be expressed completely with a
    database constraint.  This guard is shared by stages and classes and runs
    from both ``clean()`` and ``save()`` so normal ORM writes cannot bypass it.
    Controlled bulk configuration updates validate the complete proposed graph
    in ``students.progression`` before writing it.
    """
    target_id = getattr(instance, f'{field_name}_id')
    if not target_id:
        return

    if instance.pk and target_id == instance.pk:
        raise ValidationError({field_name: _(f'A {label} cannot progress to itself.')})

    model = type(instance)
    visited = set()
    current_id = target_id
    while current_id:
        if instance.pk and current_id == instance.pk:
            raise ValidationError({field_name: _(f'This {label} progression would create a cycle.')})
        if current_id in visited:
            raise ValidationError({field_name: _(f'The selected {label} progression already contains a cycle.')})
        visited.add(current_id)

        row = model.objects.filter(
            pk=current_id, school_id=instance.school_id
        ).values(
            'school_id', f'{field_name}_id'
        ).first()
        if row is None:
            raise ValidationError({field_name: _(f'Select a valid next {label}.')})
        if instance.school_id and row['school_id'] != instance.school_id:
            raise ValidationError({field_name: _(f'The next {label} must belong to the same school.')})
        current_id = row[f'{field_name}_id']


class AcademicStage(TenantScopedModel):
    """School-defined academic stage (e.g. 'Pre-Nursery', 'Primary', 'JSS', 'SSS')."""

    name = models.CharField(max_length=100, verbose_name=_('name'))
    display_order = models.PositiveIntegerField(default=0, verbose_name=_('display order'))
    is_active = models.BooleanField(default=True, verbose_name=_('active'))
    next_stage = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='previous_stages',
        verbose_name=_('next stage'),
        help_text=_('Permanent destination stage used when a class progression crosses stages.'),
    )

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
            models.CheckConstraint(
                condition=~Q(next_stage=F('pk')),
                name='academicstage_next_stage_not_self',
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
        self._validate_progression()

    def _validate_progression(self):
        _validate_progression_edge(self, 'next_stage', 'academic stage')

        # Changing a stage edge must not leave existing class progressions in
        # disagreement with it. Same-stage class progressions remain valid.
        if self.pk:
            cross_stage_links = SchoolClass.objects.filter(
                school_id=self.school_id,
                academic_stage_id=self.pk,
                next_class__isnull=False,
            ).exclude(next_class__academic_stage_id=self.pk).select_related(
                'next_class__academic_stage'
            )
            for school_class in cross_stage_links:
                if school_class.next_class.academic_stage_id != self.next_stage_id:
                    raise ValidationError({
                        'next_stage': _(
                            'This stage progression conflicts with the configured '
                            f'class progression for {school_class.name}.'
                        )
                    })

    def save(self, *args, **kwargs):
        # Normalize on every write path, including ``objects.create()``.
        self.name = self.normalize_name(self.name)
        self._validate_progression()
        super().save(*args, **kwargs)


class SchoolClass(TenantScopedModel):
    """A class as a stable entity (e.g. 'JSS1A'), independent of academic year."""

    name = models.CharField(max_length=100, verbose_name=_('name'))
    academic_stage = models.ForeignKey(
        'AcademicStage',
        on_delete=models.PROTECT,
        related_name='classes',
        verbose_name=_('academic stage'),
        help_text=_('The permanent academic stage this class belongs to.'),
    )
    next_class = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='previous_classes',
        verbose_name=_('next class'),
        help_text=_('Permanent destination used when preparing the next academic session.'),
    )
    is_active = models.BooleanField(default=True, verbose_name=_('active'))

    class Meta:
        verbose_name = _('school class')
        verbose_name_plural = _('school classes')
        unique_together = ('school', 'name')
        ordering = ['academic_stage__display_order', 'name']
        constraints = [
            models.CheckConstraint(
                condition=~Q(next_class=F('pk')),
                name='schoolclass_next_class_not_self',
            ),
        ]

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
            raise ValidationError({'academic_stage': _('Every class must belong to an academic stage.')})
        stage_school_id = AcademicStage.objects.filter(
            pk=self.academic_stage_id,
            school_id=self.school_id,
        ).values_list('school_id', flat=True).first()
        if stage_school_id is None:
            raise ValidationError(
                {'academic_stage': _('Select a valid academic stage.')}
            )
        if stage_school_id != self.school_id:
            raise ValidationError({'academic_stage': _('Academic stage must belong to the same school as the class.')})

    def _ensure_academic_stage(self):
        """Backwards-compatible assignment for legacy programmatic class writes.

        Phase 3 makes the stage mandatory. Existing integrations and fixtures
        that create a class before configuring stages receive an explicit
        ``Unclassified`` stage rather than having a stage inferred from the
        class name or display order.
        """
        if self.academic_stage_id:
            return
        if not self.school_id:
            raise ValidationError({'school': _('Select a school before creating a class.')})
        stage = next(
            (
                candidate
                for candidate in AcademicStage.objects.filter(school_id=self.school_id)
                if AcademicStage.normalize_name(candidate.name).casefold() == 'unclassified'
            ),
            None,
        )
        if stage is None:
            stage, _ = AcademicStage.objects.get_or_create(
                school_id=self.school_id,
                name='Unclassified',
                defaults={
                    'display_order': 9999,
                    'is_active': False,
                },
            )
        self.academic_stage = stage

    @staticmethod
    def _cross_stage_error(school_id, source_stage_id, destination_stage_id):
        if source_stage_id == destination_stage_id:
            return None
        source_next_stage_id = AcademicStage.objects.filter(
            pk=source_stage_id, school_id=school_id
        ).values_list('next_stage_id', flat=True).first()
        if source_next_stage_id is None:
            return _('A class cannot progress across stages until its source stage has a next stage.')
        if source_next_stage_id != destination_stage_id:
            return _('The destination class stage must match the source stage’s configured next stage.')
        return None

    def _validate_progression(self):
        _validate_progression_edge(self, 'next_class', 'class')

        if self.next_class_id:
            destination = SchoolClass.objects.filter(
                pk=self.next_class_id, school_id=self.school_id
            ).values(
                'school_id', 'academic_stage_id'
            ).first()
            if destination is None:
                raise ValidationError({'next_class': _('Select a valid next class.')})
            if destination['school_id'] != self.school_id:
                raise ValidationError({'next_class': _('The next class must belong to the same school.')})
            error = self._cross_stage_error(
                self.school_id,
                self.academic_stage_id,
                destination['academic_stage_id'],
            )
            if error:
                raise ValidationError({'next_class': error})

        # A stage change on this class can also invalidate classes that point
        # to it, so validate incoming edges against the proposed stage value.
        if self.pk:
            incoming = SchoolClass.objects.filter(
                school_id=self.school_id, next_class_id=self.pk
            ).exclude(pk=self.pk).values('name', 'academic_stage_id')
            for source in incoming:
                error = self._cross_stage_error(
                    self.school_id,
                    source['academic_stage_id'],
                    self.academic_stage_id,
                )
                if error:
                    raise ValidationError({
                        'academic_stage': _(
                            f'This stage would invalidate the progression into this class from {source["name"]}.'
                        )
                    })

    def clean(self):
        super().clean()
        self._ensure_academic_stage()
        self._validate_academic_stage_school()
        self._validate_progression()

    def save(self, *args, **kwargs):
        self._ensure_academic_stage()
        self._validate_academic_stage_school()
        self._validate_progression()
        super().save(*args, **kwargs)


class ClassOffering(TenantScopedModel):
    """A class offered in a particular academic session.

    An offering exists when a class is offered in a particular session.
    Historical offerings remain available; there is no ``is_active`` or status
    field. Both the class and the session must belong to the same school as the
    offering itself.
    """

    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.PROTECT,
        related_name='offerings',
        verbose_name=_('class'),
    )
    academic_session = models.ForeignKey(
        'core.AcademicSession',
        on_delete=models.PROTECT,
        related_name='offerings',
        verbose_name=_('academic session'),
    )

    class Meta:
        verbose_name = _('class offering')
        verbose_name_plural = _('class offerings')
        unique_together = ('school_class', 'academic_session')
        ordering = ['-academic_session__start_date', 'school_class__name']

    def __str__(self):
        return f"{self.school_class.name} – {self.academic_session.name}"

    def _validate_same_school(self):
        """Ensure the class, session and offering all belong to one school."""
        errors = {}
        class_school_id = None
        session_school_id = None

        if self.school_class_id:
            try:
                class_school_id = SchoolClass.objects.values_list(
                    'school_id', flat=True
                ).get(pk=self.school_class_id)
            except SchoolClass.DoesNotExist:
                pass

        if self.academic_session_id:
            try:
                session_school_id = AcademicSession.objects.values_list(
                    'school_id', flat=True
                ).get(pk=self.academic_session_id)
            except AcademicSession.DoesNotExist:
                pass

        if class_school_id is not None and session_school_id is not None:
            if class_school_id != session_school_id:
                errors['school_class'] = _(
                    'Class and academic session must belong to the same school.'
                )
                errors['academic_session'] = _(
                    'Class and academic session must belong to the same school.'
                )

        if self.school_id:
            if class_school_id is not None and self.school_id != class_school_id:
                errors['school_class'] = _(
                    'Class must belong to the same school as the offering.'
                )
            if session_school_id is not None and self.school_id != session_school_id:
                errors['academic_session'] = _(
                    'Academic session must belong to the same school as the offering.'
                )

        if errors:
            raise ValidationError(errors)

    def clean(self):
        super().clean()
        self._validate_same_school()

    def save(self, *args, **kwargs):
        # Validate tenant consistency on every write path. ``objects.create()``
        # and ``save()`` do not invoke ``full_clean()`` automatically.
        self._validate_same_school()
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

        Routes through :meth:`students.services.confirm_enrolment` so the
        enrolment is backed by an existing ClassOffering and the single current
        enrolment invariant is honoured transactionally.

        Returns the new ClassEnrollment instance.
        """
        from .services import confirm_enrolment

        return confirm_enrolment(student=self, school_class=school_class, session=session)


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
    class_offering = models.ForeignKey(
        'ClassOffering',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='enrollments',
        verbose_name=_('class offering'),
        help_text=(
            'The class offering this enrolment belongs to. Nullable during the '
            'transition period; new enrolments created via the enrolment service '
            'always resolve an existing offering.'
        ),
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

    def _validate_enrolment_invariants(self):
        """Enforce cross-field tenant/session/class consistency.

        These invariants cannot be expressed as single-table database
        constraints (offering/session and tenant equality span multiple tables),
        so they are validated here on every write path. ``bulk_create`` and
        ``QuerySet.update`` still bypass this validation; callers must use the
        enrolment service or ``full_clean()``.
        """
        errors = {}

        if self.student_id and self.school_id:
            try:
                student_school_id = Student.objects.values_list(
                    'school_id', flat=True
                ).get(pk=self.student_id)
            except Student.DoesNotExist:
                student_school_id = None
            if student_school_id is not None and student_school_id != self.school_id:
                errors['student'] = _(
                    'Student must belong to the same school as the enrolment.'
                )

        if self.school_class_id and self.school_id:
            try:
                class_school_id = SchoolClass.objects.values_list(
                    'school_id', flat=True
                ).get(pk=self.school_class_id)
            except SchoolClass.DoesNotExist:
                class_school_id = None
            if class_school_id is not None and class_school_id != self.school_id:
                errors['school_class'] = _(
                    'Class must belong to the same school as the enrolment.'
                )

        if self.session_id and self.school_id:
            try:
                session_school_id = AcademicSession.objects.values_list(
                    'school_id', flat=True
                ).get(pk=self.session_id)
            except AcademicSession.DoesNotExist:
                session_school_id = None
            if session_school_id is not None and session_school_id != self.school_id:
                errors['session'] = _(
                    'Session must belong to the same school as the enrolment.'
                )

        # Offering invariants (only enforced when an offering is assigned).
        if self.class_offering_id:
            offering = self.class_offering
            if self.student_id and offering.school_id != self.student.school_id:
                errors['class_offering'] = _(
                    'Offering must belong to the same school as the student.'
                )
            if offering.academic_session_id != self.session_id:
                errors['class_offering'] = _(
                    'Offering must belong to the same session as the enrolment.'
                )
            if offering.school_class_id != self.school_class_id:
                errors['class_offering'] = _(
                    'Offering class must match the enrolment class.'
                )

        if errors:
            raise ValidationError(errors)

    def clean(self):
        super().clean()
        self._validate_enrolment_invariants()

    def save(self, *args, **kwargs):
        # Constraint validation happens on every write path because
        # ``objects.create()``/``save()`` do not invoke ``full_clean()``.
        self._validate_enrolment_invariants()
        super().save(*args, **kwargs)
        if self.is_current:
            ClassEnrollment.objects.filter(
                student=self.student, is_current=True
            ).exclude(pk=self.pk).update(is_current=False)


class SessionPreparation(TenantScopedModel):
    """Persisted administrative plan for preparing one future session.

    Progression configuration itself remains on ``AcademicStage`` and
    ``SchoolClass``. This model records only the review/confirmation workflow
    for a specific target session.
    """

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', _('Draft')
        CONFIRMED = 'CONFIRMED', _('Confirmed')

    source_session = models.ForeignKey(
        'core.AcademicSession',
        on_delete=models.PROTECT,
        related_name='outgoing_student_preparations',
        verbose_name=_('source session'),
    )
    target_session = models.OneToOneField(
        'core.AcademicSession',
        on_delete=models.PROTECT,
        related_name='student_preparation',
        verbose_name=_('target session'),
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        verbose_name=_('status'),
    )
    proposals_generated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('proposals generated at'),
    )
    confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('confirmed at'),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_session_preparations',
        verbose_name=_('created by'),
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='confirmed_session_preparations',
        verbose_name=_('confirmed by'),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('created at'))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_('updated at'))

    class Meta:
        verbose_name = _('session preparation')
        verbose_name_plural = _('session preparations')
        ordering = ['-target_session__start_date']

    def __str__(self):
        return f'{self.source_session.name} → {self.target_session.name}'

    def _validate_context(self):
        errors = {}
        source = AcademicSession.objects.filter(
            pk=self.source_session_id, school_id=self.school_id
        ).values(
            'school_id', 'start_date', 'end_date'
        ).first()
        target = AcademicSession.objects.filter(
            pk=self.target_session_id, school_id=self.school_id
        ).values(
            'school_id', 'start_date'
        ).first()
        if source is None:
            errors['source_session'] = _('Select a valid source session.')
        if target is None:
            errors['target_session'] = _('Select a valid target session.')
        if source and source['school_id'] != self.school_id:
            errors['source_session'] = _('Source session must belong to this school.')
        if target and target['school_id'] != self.school_id:
            errors['target_session'] = _('Target session must belong to this school.')
        if self.source_session_id and self.source_session_id == self.target_session_id:
            errors['target_session'] = _('Source and target sessions must be different.')
        if source and target and target['start_date'] <= source['end_date']:
            errors['target_session'] = _('Target session must start after the source session ends.')
        for field_name in ('created_by', 'confirmed_by'):
            user_id = getattr(self, f'{field_name}_id')
            if user_id:
                from accounts.models import User

                user_school_id = User.objects.filter(
                    pk=user_id, school_id=self.school_id
                ).values_list(
                    'school_id', flat=True
                ).first()
                if user_school_id != self.school_id:
                    errors[field_name] = _('Administrator must belong to this school.')
        if errors:
            raise ValidationError(errors)

    def clean(self):
        super().clean()
        self._validate_context()

    def save(self, *args, **kwargs):
        self._validate_context()
        super().save(*args, **kwargs)


class StudentSessionMovement(TenantScopedModel):
    """One student's reviewed destination within a session preparation."""

    class Action(models.TextChoices):
        PROGRESS = 'PROGRESS', _('Progress')
        REPEAT = 'REPEAT', _('Repeat current class')
        EXCLUDE = 'EXCLUDE', _('Exclude from this session')
        WITHDRAW = 'WITHDRAW', _('Mark withdrawn')

    class ProposalBasis(models.TextChoices):
        NEXT_CLASS = 'NEXT_CLASS', _('Configured next class')
        SAME_CLASS = 'SAME_CLASS', _('Same class (no next class configured)')
        LIFECYCLE_EXCLUSION = 'LIFECYCLE_EXCLUSION', _('Student lifecycle status')

    preparation = models.ForeignKey(
        SessionPreparation,
        on_delete=models.CASCADE,
        related_name='movements',
        verbose_name=_('session preparation'),
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.PROTECT,
        related_name='session_movements',
        verbose_name=_('student'),
    )
    source_enrollment = models.ForeignKey(
        ClassEnrollment,
        on_delete=models.PROTECT,
        related_name='session_movements',
        verbose_name=_('source enrolment'),
    )
    proposed_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='proposed_session_movements',
        verbose_name=_('proposed class'),
    )
    destination_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='destination_session_movements',
        verbose_name=_('destination class'),
    )
    proposal_basis = models.CharField(
        max_length=30,
        choices=ProposalBasis.choices,
        verbose_name=_('proposal basis'),
    )
    action = models.CharField(
        max_length=20,
        choices=Action.choices,
        default=Action.PROGRESS,
        verbose_name=_('action'),
    )
    is_override = models.BooleanField(default=False, verbose_name=_('administrative override'))
    note = models.CharField(max_length=255, blank=True, verbose_name=_('note'))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('created at'))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_('updated at'))

    class Meta:
        verbose_name = _('student session movement')
        verbose_name_plural = _('student session movements')
        ordering = ['student__user__last_name', 'student__user__first_name', 'student__admission_number']
        constraints = [
            models.UniqueConstraint(
                fields=['preparation', 'student'],
                name='uniq_preparation_student_movement',
            ),
        ]

    def __str__(self):
        destination = self.destination_class.name if self.destination_class_id else self.get_action_display()
        return f'{self.student} → {destination}'

    def _validate_context(self):
        errors = {}
        preparation = SessionPreparation.objects.filter(
            pk=self.preparation_id, school_id=self.school_id
        ).values(
            'school_id', 'source_session_id'
        ).first()
        student = Student.objects.filter(
            pk=self.student_id, school_id=self.school_id
        ).values('school_id').first()
        source = ClassEnrollment.objects.filter(
            pk=self.source_enrollment_id, school_id=self.school_id
        ).values(
            'school_id', 'student_id', 'session_id', 'school_class_id'
        ).first()

        if preparation is None:
            errors['preparation'] = _('Select a valid session preparation.')
        elif preparation['school_id'] != self.school_id:
            errors['preparation'] = _('Session preparation must belong to this school.')
        if student is None:
            errors['student'] = _('Select a valid student.')
        elif student['school_id'] != self.school_id:
            errors['student'] = _('Student must belong to this school.')
        if source is None:
            errors['source_enrollment'] = _('Select a valid source enrolment.')
        else:
            if source['school_id'] != self.school_id:
                errors['source_enrollment'] = _('Source enrolment must belong to this school.')
            if self.student_id and source['student_id'] != self.student_id:
                errors['source_enrollment'] = _('Source enrolment must belong to this student.')
            if preparation and source['session_id'] != preparation['source_session_id']:
                errors['source_enrollment'] = _('Source enrolment must belong to the preparation source session.')

        for field_name in ('proposed_class', 'destination_class'):
            class_id = getattr(self, f'{field_name}_id')
            if class_id:
                class_school_id = SchoolClass.objects.filter(
                    pk=class_id, school_id=self.school_id
                ).values_list(
                    'school_id', flat=True
                ).first()
                if class_school_id != self.school_id:
                    errors[field_name] = _('Class must belong to this school.')

        included = self.action in (self.Action.PROGRESS, self.Action.REPEAT)
        if included and not self.destination_class_id:
            errors['destination_class'] = _('Included students require a destination class.')
        if not included and self.destination_class_id:
            errors['destination_class'] = _('Excluded or withdrawn students cannot have a destination class.')
        if self.action == self.Action.REPEAT and source:
            if self.destination_class_id != source['school_class_id']:
                errors['destination_class'] = _('A repeater must remain in the source class.')
        if errors:
            raise ValidationError(errors)

    def clean(self):
        super().clean()
        self._validate_context()

    def save(self, *args, **kwargs):
        self._validate_context()
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
