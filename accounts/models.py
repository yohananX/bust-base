from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


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


class User(AbstractUser):
    """Custom user model with school tenancy and role.

    This is the single user model for the entire system.
    Role-specific profile data belongs in future modules.
    """
    school = models.ForeignKey(
        'core.School',
        on_delete=models.CASCADE,
        verbose_name=_('school'),
    )
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
