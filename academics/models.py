from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import TenantScopedModel
from accounts.models import Roles


class Subject(TenantScopedModel):
    """A subject taught in the school."""

    name = models.CharField(max_length=200, verbose_name=_('name'))
    code = models.CharField(max_length=20, verbose_name=_('code'))
    pass_mark = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        default=None,
        verbose_name=_('pass mark'),
        help_text=_(
            'Default copied into new class-offering configurations. Changing '
            'this value does not alter existing or historical configurations.'
        ),
    )
    class_offerings = models.ManyToManyField(
        'students.ClassOffering',
        through='ClassSubject',
        related_name='subjects',
        verbose_name=_('class offerings'),
    )

    class Meta:
        verbose_name = _('subject')
        verbose_name_plural = _('subjects')
        unique_together = ('school', 'code')
        ordering = ['name']

    def __str__(self):
        return self.name


class ClassSubject(TenantScopedModel):
    """A subject configured for one class offering (class + session)."""

    class_offering = models.ForeignKey(
        'students.ClassOffering',
        on_delete=models.PROTECT,
        related_name='class_subjects',
        verbose_name=_('class offering'),
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.PROTECT,
        related_name='class_subjects',
        verbose_name=_('subject'),
    )
    pass_mark = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        default=None,
        verbose_name=_('pass mark'),
        help_text=_(
            'Pass mark for this subject in this class offering. The subject '
            'default is copied here when a new configuration is created.'
        ),
    )

    class Meta:
        verbose_name = _('class subject')
        verbose_name_plural = _('class subjects')
        unique_together = ('class_offering', 'subject')
        ordering = [
            'class_offering__school_class__name',
            '-class_offering__academic_session__start_date',
            'subject__name',
        ]

    def __str__(self):
        return f"{self.subject.name} - {self.class_offering}"

    @property
    def school_class(self):
        """Stable class represented by this session-specific configuration."""
        return self.class_offering.school_class

    @property
    def academic_session(self):
        return self.class_offering.academic_session

    def _validate_academic_context(self):
        """Enforce tenant consistency between the offering and subject."""
        from students.models import ClassOffering

        errors = {}
        offering_school_id = None
        subject_school_id = None

        if self.class_offering_id:
            try:
                offering_school_id = ClassOffering.objects.values_list(
                    'school_id', flat=True
                ).get(pk=self.class_offering_id)
            except ClassOffering.DoesNotExist:
                pass

        if self.subject_id:
            try:
                subject_school_id = Subject.objects.values_list(
                    'school_id', flat=True
                ).get(pk=self.subject_id)
            except Subject.DoesNotExist:
                pass

        if (
            offering_school_id is not None
            and subject_school_id is not None
            and offering_school_id != subject_school_id
        ):
            errors['subject'] = _(
                'Subject must belong to the same school as the class offering.'
            )
        if self.school_id:
            if offering_school_id is not None and self.school_id != offering_school_id:
                errors['class_offering'] = _(
                    'Class offering must belong to the same school as the configuration.'
                )
            if subject_school_id is not None and self.school_id != subject_school_id:
                errors['subject'] = _(
                    'Subject must belong to the same school as the configuration.'
                )

        if errors:
            raise ValidationError(errors)

    def clean(self):
        super().clean()
        self._validate_academic_context()

    def save(self, *args, **kwargs):
        self._validate_academic_context()
        # Snapshot the catalogue default at creation time. Existing rows never
        # consult the mutable Subject default when pass/fail is calculated.
        if self._state.adding and self.pass_mark is None and self.subject_id:
            self.pass_mark = Subject.objects.filter(pk=self.subject_id).values_list(
                'pass_mark', flat=True
            ).first()
        super().save(*args, **kwargs)

    def effective_pass_mark(self):
        """Return this offering's snapshotted pass mark."""
        return self.pass_mark


class TeacherAssignment(TenantScopedModel):
    """Assigns a teacher to one session-specific subject configuration."""

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': Roles.TEACHER},
        related_name='teacher_assignments',
        verbose_name=_('teacher'),
    )
    class_subject = models.ForeignKey(
        ClassSubject,
        on_delete=models.PROTECT,
        related_name='teacher_assignments',
        verbose_name=_('class subject'),
    )

    class Meta:
        verbose_name = _('teacher assignment')
        verbose_name_plural = _('teacher assignments')
        unique_together = ('teacher', 'class_subject')

    def __str__(self):
        return f"{self.teacher} - {self.subject} ({self.class_offering})"

    @property
    def subject(self):
        return self.class_subject.subject

    @property
    def subject_id(self):
        return self.class_subject.subject_id

    @property
    def class_offering(self):
        return self.class_subject.class_offering

    @property
    def class_offering_id(self):
        return self.class_subject.class_offering_id

    @property
    def school_class(self):
        return self.class_subject.class_offering.school_class

    @property
    def school_class_id(self):
        return self.class_subject.class_offering.school_class_id

    @property
    def session(self):
        return self.class_subject.class_offering.academic_session

    @property
    def session_id(self):
        return self.class_subject.class_offering.academic_session_id

    def clean(self):
        super().clean()
        self._validate_assignment()

    def _validate_assignment(self):
        """Validate role, tenant, and offering-subject consistency."""
        errors = {}
        teacher_school_id = None
        teacher_role = None
        class_subject_school_id = None
        offering_school_id = None
        subject_school_id = None

        if self.teacher_id:
            teacher_model = self._meta.get_field('teacher').remote_field.model
            try:
                teacher_school_id, teacher_role = teacher_model.objects.values_list(
                    'school_id', 'role'
                ).get(pk=self.teacher_id)
            except teacher_model.DoesNotExist:
                pass

        if teacher_role is not None and teacher_role != Roles.TEACHER:
            errors['teacher'] = _('The selected user must have the role "Teacher".')

        if self.class_subject_id:
            try:
                (
                    class_subject_school_id,
                    offering_school_id,
                    subject_school_id,
                ) = ClassSubject.objects.values_list(
                    'school_id',
                    'class_offering__school_id',
                    'subject__school_id',
                ).get(pk=self.class_subject_id)
            except ClassSubject.DoesNotExist:
                pass

        if len({
            value for value in (
                class_subject_school_id,
                offering_school_id,
                subject_school_id,
            ) if value is not None
        }) > 1:
            errors['class_subject'] = _(
                'Subject configuration, subject, and class offering must belong '
                'to the same school.'
            )

        if self.school_id:
            if teacher_school_id is not None and teacher_school_id != self.school_id:
                errors['teacher'] = _(
                    'Teacher must belong to the same school as the assignment.'
                )
            if (
                class_subject_school_id is not None
                and class_subject_school_id != self.school_id
            ):
                errors['class_subject'] = _(
                    'Subject configuration must belong to the same school as the assignment.'
                )
        if (
            teacher_school_id is not None
            and class_subject_school_id is not None
            and teacher_school_id != class_subject_school_id
        ):
            errors['class_subject'] = _(
                'Teacher and subject configuration must belong to the same school.'
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # Validate cross-table invariants on direct ``objects.create`` writes.
        self._validate_assignment()
        super().save(*args, **kwargs)


class ScoreQuerySet(models.QuerySet):
    """Custom queryset with tenant scoping and results-published filtering."""

    def for_school(self, school):
        """Return queryset filtered to a specific school."""
        return self.filter(school=school)

    def visible_to_user(self, user):
        """Filter scores based on user role and term publication status.

        Admins/teachers: all scores
        Students/parents: only scores for terms with results_published=True
        """
        if user.is_staff or getattr(user, 'role', None) in [Roles.ADMIN, Roles.TEACHER]:
            return self
        return self.filter(term__results_published=True)


class Score(TenantScopedModel):
    """Stores assessment scores for a student in a subject within a term."""

    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        related_name='scores',
        verbose_name=_('student'),
    )
    class_subject = models.ForeignKey(
        ClassSubject,
        on_delete=models.PROTECT,
        related_name='scores',
        verbose_name=_('class subject'),
    )
    term = models.ForeignKey(
        'core.Term',
        on_delete=models.CASCADE,
        related_name='scores',
        verbose_name=_('term'),
    )
    test_1 = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_('test 1'),
    )
    test_2 = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_('test 2'),
    )
    test_3 = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_('test 3'),
    )
    exam_score = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_('exam score'),
    )
    extra_tests = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_('extra tests'),
        help_text=_('Additional test scores, e.g. {"test_4": 8, "test_5": 9}'),
    )
    position = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_('position'),
    )
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        verbose_name=_('entered by'),
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_('updated at'))

    MODERATION_PENDING = 'PENDING'
    MODERATION_APPROVED = 'APPROVED'
    MODERATION_REJECTED = 'REJECTED'
    MODERATION_CHOICES = [
        (MODERATION_PENDING, _('Pending')),
        (MODERATION_APPROVED, _('Approved')),
        (MODERATION_REJECTED, _('Rejected')),
    ]

    moderation_status = models.CharField(
        max_length=20,
        choices=MODERATION_CHOICES,
        default=MODERATION_PENDING,
        verbose_name=_('moderation status'),
    )
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='moderated_scores',
        verbose_name=_('moderated by'),
    )
    moderated_at = models.DateTimeField(null=True, blank=True, verbose_name=_('moderated at'))

    objects = ScoreQuerySet.as_manager()

    class Meta:
        verbose_name = _('score')
        verbose_name_plural = _('scores')
        unique_together = ('student', 'class_subject', 'term')
        ordering = ['student__admission_number']

    def __str__(self):
        return f"{self.student} - {self.subject} ({self.term})"

    @property
    def subject(self):
        return self.class_subject.subject

    @property
    def subject_id(self):
        return self.class_subject.subject_id

    @property
    def total_score(self):
        base = (self.test_1 or 0) + (self.test_2 or 0) + (self.test_3 or 0) + (self.exam_score or 0)
        extra = sum((v or 0) for v in (self.extra_tests or {}).values())
        return base + extra

    @property
    def is_complete(self):
        base_complete = all([
            self.test_1 is not None,
            self.test_2 is not None,
            self.test_3 is not None,
            self.exam_score is not None,
        ])
        if not base_complete:
            return False
        extra = self.extra_tests or {}
        return all(v is not None for v in extra.values())

    @property
    def passed(self):
        if not self.is_complete:
            return None
        pass_mark = self.class_subject.effective_pass_mark()
        if pass_mark is None:
            return None
        return self.total_score >= pass_mark

    def _validate_academic_context(self):
        """Ensure score, student, term, and configuration share one offering."""
        from students.models import ClassEnrollment

        errors = {}
        if not all((self.school_id, self.student_id, self.term_id, self.class_subject_id)):
            return

        student_school_id = self.student.school_id
        term_school_id = self.term.school_id
        class_subject = self.class_subject
        offering = class_subject.class_offering

        if student_school_id != self.school_id:
            errors['student'] = _('Student must belong to the score school.')
        if term_school_id != self.school_id:
            errors['term'] = _('Term must belong to the score school.')
        if class_subject.school_id != self.school_id or offering.school_id != self.school_id:
            errors['class_subject'] = _(
                'Subject configuration must belong to the score school.'
            )
        if offering.academic_session_id != self.term.session_id:
            errors['class_subject'] = _(
                'Subject configuration must belong to the term academic session.'
            )

        enrollment = ClassEnrollment.objects.filter(
            school_id=self.school_id,
            student_id=self.student_id,
            session_id=self.term.session_id,
        ).only('class_offering_id').first()
        if enrollment is None:
            errors['student'] = _(
                'Student must have an enrolment in the term academic session.'
            )
        elif enrollment.class_offering_id != offering.pk:
            errors['class_subject'] = _(
                'Subject configuration must belong to the student enrolment offering.'
            )

        if errors:
            raise ValidationError(errors)

    def clean(self):
        """Enforce the school's configured score maxima.

        The per-component caps live on ``School.test_max_scores`` /
        ``School.exam_max_score``. Extra tests are validated dynamically
        against the same store.
        """
        super().clean()
        self._validate_academic_context()
        maxima = self.school.score_component_maxima()
        for field, max_value in maxima.items():
            value = getattr(self, field, None)
            if value is not None and value > max_value:
                raise ValidationError({
                    field: _(
                        '%(label)s must be at most %(max)d for this school.'
                    ) % {'label': self._meta.get_field(field).verbose_name, 'max': max_value},
                })
        extra = self.extra_tests or {}
        for key, value in extra.items():
            max_value = maxima.get(key)
            if max_value is not None and value is not None and value > max_value:
                raise ValidationError({
                    key: _('%(label)s must be at most %(max)d for this school.') % {'label': key, 'max': max_value},
                })

    def save(self, *args, **kwargs):
        self._validate_academic_context()
        super().save(*args, **kwargs)


class GradeScale(TenantScopedModel):
    """Grading scale bands — e.g. 75-100 = A/Excellent."""

    min_score = models.PositiveSmallIntegerField(verbose_name=_('min score'))
    max_score = models.PositiveSmallIntegerField(verbose_name=_('max score'))
    label = models.CharField(max_length=5, verbose_name=_('label'))  # A, B, C, D, F
    remark = models.CharField(max_length=50, verbose_name=_('remark'))  # Excellent, Very Good, etc.

    class Meta:
        verbose_name = _('grade scale')
        verbose_name_plural = _('grade scales')
        unique_together = ('school', 'label')
        ordering = ['-min_score']

    def __str__(self):
        return f"{self.label} ({self.min_score}-{self.max_score})"

    @classmethod
    def get_grade(cls, school, score):
        """Return the GradeScale label for a given score, or None."""
        grade = cls.objects.filter(
            school=school, min_score__lte=score, max_score__gte=score
        ).first()
        return grade.label if grade else None


class TermResult(TenantScopedModel):
    """Cross-subject aggregate for one student, one term."""

    student = models.ForeignKey(
        'students.Student', on_delete=models.CASCADE,
        related_name='term_results', verbose_name=_('student'),
    )
    term = models.ForeignKey(
        'core.Term', on_delete=models.CASCADE,
        related_name='term_results', verbose_name=_('term'),
    )
    # Computed academic fields
    grand_total = models.PositiveIntegerField(default=0, verbose_name=_('grand total'))
    average = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name=_('average'))
    overall_position = models.PositiveIntegerField(null=True, blank=True, verbose_name=_('overall position'))
    total_subjects = models.PositiveSmallIntegerField(default=0, verbose_name=_('total subjects'))

    # Manually entered fields
    days_present = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name=_('days present'))
    days_absent = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name=_('days absent'))
    total_days = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name=_('total school days'))

    # Affective ratings (1-5)
    punctuality = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name=_('punctuality'),
    )
    neatness = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name=_('neatness'),
    )
    honesty = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name=_('honesty'),
    )
    attentiveness = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name=_('attentiveness'),
    )

    # Remarks
    class_teacher_remark = models.TextField(blank=True, verbose_name=_('class teacher remark'))
    principal_remark = models.TextField(blank=True, verbose_name=_('principal remark'))

    computed_at = models.DateTimeField(auto_now=True, verbose_name=_('computed at'))

    class Meta:
        verbose_name = _('term result')
        verbose_name_plural = _('term results')
        unique_together = ('student', 'term')

    def __str__(self):
        return f"{self.student} - {self.term}"
