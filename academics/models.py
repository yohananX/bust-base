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
