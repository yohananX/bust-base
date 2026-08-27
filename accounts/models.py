from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import TenantScopedModel, TenantScopedManager


class Roles:
    """Constants for user roles within the school system."""
    ADMIN = 'ADMIN'
    TEACHER = 'TEACHER'
    STUDENT = 'STUDENT'
    PARENT = 'PARENT'

    CHOICES = [
        (ADMIN, _('Admin')),
        (TEACHER, _('Teacher')),
        (STUDENT, _('Student')),
        (PARENT, _('Parent')),
    ]


class TenantScopedUserManager(DjangoUserManager, TenantScopedManager):
    """Combines Django's UserManager (create_user, create_superuser) 
    with TenantScopedManager (for_school) for consistent tenant scoping."""
    pass


class User(AbstractUser, TenantScopedModel):
    """Custom user model with school tenancy and role.

    Inherits school FK from TenantScopedModel (abstract base).
    Superadmins are cross-school and have school=None.
    Role-specific profile data belongs in future modules.
    """
    objects = TenantScopedUserManager()

    # Override school to be nullable (superadmins don't belong to a school)
    school = models.ForeignKey(
        'core.School',
        on_delete=models.CASCADE,
        verbose_name=_('school'),
        null=True,
        blank=True,
    )

    role = models.CharField(
        max_length=20,
        choices=Roles.CHOICES,
        blank=True,
        verbose_name=_('role'),
    )
    middle_name = models.CharField(
        max_length=150,
        blank=True,
        verbose_name=_('middle name'),
    )
    phone_number = models.CharField(
        max_length=30,
        blank=True,
        verbose_name=_('phone number'),
    )
    other_phones = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_('other phone numbers'),
        help_text=_('Additional contact numbers as a JSON list of strings.'),
    )
    passport = models.ImageField(
        upload_to='passports/',
        blank=True,
        verbose_name=_('passport'),
    )
    must_change_password = models.BooleanField(
        default=False,
        verbose_name=_('must change password'),
        help_text=_(
            'Set for accounts whose password was generated for them (bulk '
            'credential runs, resets, new student/parent creation). The user '
            'is forced to pick their own password on first login.'
        ),
    )

    REQUIRED_FIELDS = ['email']

    class Meta:
        verbose_name = _('user')
        verbose_name_plural = _('users')

    def __str__(self):
        return self.get_full_name() or self.username

    def get_full_name(self):
        """Full name as First [Middle] Last, omitting middle when blank."""
        parts = [p for p in (self.first_name, self.middle_name, self.last_name) if p]
        return ' '.join(parts)
