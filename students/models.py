from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import TenantScopedModel
from accounts.models import Roles


class SchoolClass(TenantScopedModel):
    """A class as a stable entity (e.g. 'JSS1A'), independent of academic year."""

    name = models.CharField(max_length=100, verbose_name=_('name'))
    level = models.CharField(
        max_length=100,
        verbose_name=_('level'),
        help_text=_('e.g. "JSS1", "Primary 3" — used for grouping/reporting'),
    )
    is_active = models.BooleanField(default=True, verbose_name=_('active'))

    class Meta:
        verbose_name = _('school class')
        verbose_name_plural = _('school classes')
        unique_together = ('school', 'name')
        ordering = ['level', 'name']

    def __str__(self):
        return self.name


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

    def clean(self):
        """Validate that the linked user has role=STUDENT."""
        if self.user_id and self.user.role != Roles.STUDENT:
            raise ValidationError({
                'user': _('The selected user must have the role "Student".'),
            })

    def save(self, *args, **kwargs):
        self.clean()
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

    class Meta:
        verbose_name = _('student-guardian link')
        verbose_name_plural = _('student-guardian links')
        unique_together = ('student', 'guardian')

    def __str__(self):
        student_name = self.student.user.get_full_name() or self.student.user.username
        rel_display = self.get_relationship_display()
        return f"{student_name}'s {rel_display.lower()}"

    def clean(self):
        """Validate that the linked user has role=PARENT."""
        if self.guardian_id and self.guardian.role != Roles.PARENT:
            raise ValidationError({
                'guardian': _('The selected user must have the role "Parent".'),
            })

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
