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
    pass_mark = models.PositiveSmallIntegerField(default=40, verbose_name=_('pass mark'))

    class Meta:
        verbose_name = _('subject')
        verbose_name_plural = _('subjects')
        unique_together = ('school', 'code')
        ordering = ['name']

    def __str__(self):
        return self.name


class TeacherAssignment(TenantScopedModel):
    """Assigns a teacher to a subject in a specific class and session."""

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': Roles.TEACHER},
        related_name='teacher_assignments',
        verbose_name=_('teacher'),
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name='teacher_assignments',
        verbose_name=_('subject'),
    )
    school_class = models.ForeignKey(
        'students.SchoolClass',
        on_delete=models.CASCADE,
        related_name='teacher_assignments',
        verbose_name=_('class'),
    )
    session = models.ForeignKey(
        'core.AcademicSession',
        on_delete=models.CASCADE,
        related_name='teacher_assignments',
        verbose_name=_('academic session'),
    )

    class Meta:
        verbose_name = _('teacher assignment')
        verbose_name_plural = _('teacher assignments')
        unique_together = ('teacher', 'subject', 'school_class', 'session')

    def __str__(self):
        return f"{self.teacher} - {self.subject} ({self.school_class}, {self.session})"

    def clean(self):
        """Validate that the linked user has role=TEACHER."""
        if self.teacher_id and self.teacher.role != Roles.TEACHER:
            raise ValidationError({
                'teacher': _('The selected user must have the role "Teacher".'),
            })

    def save(self, *args, **kwargs):
        self.clean()
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
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name='scores',
        verbose_name=_('subject'),
    )
    term = models.ForeignKey(
        'core.Term',
        on_delete=models.CASCADE,
        related_name='scores',
        verbose_name=_('term'),
    )
    test_1 = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        verbose_name=_('test 1'),
    )
    test_2 = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        verbose_name=_('test 2'),
    )
    test_3 = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        verbose_name=_('test 3'),
    )
    exam_score = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(70)],
        verbose_name=_('exam score'),
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
        unique_together = ('student', 'subject', 'term')
        ordering = ['student__admission_number']

    def __str__(self):
        return f"{self.student} - {self.subject} ({self.term})"

    @property
    def total_score(self):
        return (self.test_1 or 0) + (self.test_2 or 0) + (self.test_3 or 0) + (self.exam_score or 0)

    @property
    def is_complete(self):
        return all([
            self.test_1 is not None,
            self.test_2 is not None,
            self.test_3 is not None,
            self.exam_score is not None,
        ])

    @property
    def passed(self):
        if not self.is_complete:
            return None
        return self.total_score >= self.subject.pass_mark


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
