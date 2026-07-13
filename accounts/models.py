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
    Role-specific profile data belongs in future modules.
    """
    objects = TenantScopedUserManager()
    role = models.CharField(
        max_length=20,
        choices=Roles.CHOICES,
        verbose_name=_('role'),
    )
    phone_number = models.CharField(
        max_length=30,
        blank=True,
        verbose_name=_('phone number'),
    )

    REQUIRED_FIELDS = ['email', 'school', 'role']

    class Meta:
        verbose_name = _('user')
        verbose_name_plural = _('users')

    def __str__(self):
        return self.get_full_name() or self.username
