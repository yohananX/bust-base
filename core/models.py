from django.db import models
from django.utils.translation import gettext_lazy as _


class TenantScopedManager(models.Manager):
    """Manager that provides school-scoped filtering."""

    def for_school(self, school):
        """Return queryset filtered to a specific school."""
        return self.filter(school=school)


class TenantScopedModel(models.Model):
    """Abstract base class for all models that are scoped to a School tenant."""
    school = models.ForeignKey(
        'core.School',
        on_delete=models.CASCADE,
        verbose_name=_('school'),
    )

    objects = TenantScopedManager()

    class Meta:
        abstract = True


class School(models.Model):
    """Tenant model representing a school."""
    name = models.CharField(max_length=255, verbose_name=_('name'))
    short_code = models.SlugField(
        max_length=50,
        unique=True,
        verbose_name=_('short code'),
        help_text=_('Used for URLs and subdomains'),
    )
    address = models.CharField(max_length=500, blank=True, verbose_name=_('address'))
    phone = models.CharField(max_length=50, blank=True, verbose_name=_('phone'))
    email = models.EmailField(blank=True, verbose_name=_('email'))
    is_active = models.BooleanField(default=True, verbose_name=_('active'))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('created at'))

    class Meta:
        verbose_name = _('school')
        verbose_name_plural = _('schools')
        ordering = ['name']

    def __str__(self):
        return self.name


class AcademicSession(TenantScopedModel):
    """School year / academic session."""
    name = models.CharField(max_length=100, verbose_name=_('name'))
    start_date = models.DateField(verbose_name=_('start date'))
    end_date = models.DateField(verbose_name=_('end date'))
    is_current = models.BooleanField(default=False, verbose_name=_('current'))

    class Meta:
        verbose_name = _('academic session')
        verbose_name_plural = _('academic sessions')
        unique_together = ('school', 'name')
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.name} ({self.school.name})"

    def save(self, *args, **kwargs):
        if self.is_current:
            AcademicSession.objects.filter(
                school=self.school, is_current=True
            ).exclude(pk=self.pk).update(is_current=False)
        super().save(*args, **kwargs)


class Term(TenantScopedModel):
    """Term within an academic session."""
    session = models.ForeignKey(
        AcademicSession,
        on_delete=models.CASCADE,
        related_name='terms',
        verbose_name=_('session'),
    )
    name = models.CharField(max_length=100, verbose_name=_('name'))
    start_date = models.DateField(verbose_name=_('start date'))
    end_date = models.DateField(verbose_name=_('end date'))
    is_current = models.BooleanField(default=False, verbose_name=_('current'))

    class Meta:
        verbose_name = _('term')
        verbose_name_plural = _('terms')
        unique_together = ('school', 'session', 'name')
        ordering = ['start_date']

    def __str__(self):
        return f"{self.name} ({self.session.name} - {self.school.name})"

    def save(self, *args, **kwargs):
        if self.is_current:
            # Only one term can be current across all sessions for a school
            Term.objects.filter(
                school=self.school, is_current=True
            ).exclude(pk=self.pk).update(is_current=False)
        super().save(*args, **kwargs)
