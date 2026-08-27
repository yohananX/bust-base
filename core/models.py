from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils.translation import gettext_lazy as _


class TenantScopedManager(models.Manager):
    """Manager that provides school-scoped filtering."""

    def for_school(self, school) -> models.QuerySet:
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
    logo = models.ImageField(upload_to='school_logos/', blank=True, verbose_name=_('logo'))
    principal_name = models.CharField(max_length=200, blank=True, verbose_name=_('principal name'))
    bank_name = models.CharField(max_length=100, blank=True, verbose_name=_('bank name'))
    account_name = models.CharField(max_length=200, blank=True, verbose_name=_('account name'))
    account_number = models.CharField(max_length=50, blank=True, verbose_name=_('account number'))
    test_max_scores = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_('test max scores'),
        help_text=_('Maximum marks per test, e.g. {"test_1": 10, "test_2": 10, "test_3": 10}'),
    )
    exam_max_score = models.PositiveSmallIntegerField(
        default=70, verbose_name=_('exam max score'),
        help_text=_('Maximum marks for the examination component'),
    )
    is_active = models.BooleanField(default=True, verbose_name=_('active'))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('created at'))

    class Meta:
        verbose_name = _('school')
        verbose_name_plural = _('schools')
        ordering = ['name']

    def __str__(self):
        return self.name

    def score_component_maxima(self) -> dict:
        """Per-component score caps for this school.

        Returns a dict mapping every configured test key plus ``exam_score``
        to its maximum, e.g.
        ``{'test_1': 10, 'test_2': 10, 'test_3': 10, 'test_4': 10, 'exam_score': 70}``.
        Falls back to the legacy ``test_max_score`` / ``exam_max_score`` fields
        when the JSON stores are empty, so existing schools keep working.
        """
        maxima = dict(self.test_max_scores or {})
        if not maxima:
            maxima = {
                'test_1': 10,
                'test_2': 10,
                'test_3': 10,
            }
        maxima.setdefault('exam_score', self.exam_max_score)
        return maxima

    def total_score_max(self) -> int:
        """Highest possible total for a complete score (tests + exam)."""
        maxima = self.score_component_maxima()
        return sum(v for k, v in maxima.items() if k != 'exam_score') + maxima.get('exam_score', 0)


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
    results_published = models.BooleanField(default=False, verbose_name=_('results published'))

    class Meta:
        verbose_name = _('term')
        verbose_name_plural = _('terms')
        unique_together = ('school', 'session', 'name')
        ordering = ['start_date']

    def __str__(self):
        return f"{self.name} ({self.session.name} - {self.school.name})"

    @classmethod
    def for_current_session(cls, school):
        """Terms of the school's current academic session (First/Second/Third).

        Term dropdowns across the site use this so only the active session's
        three terms are ever offered, regardless of how many sessions exist.
        """
        session = AcademicSession.objects.filter(
            school=school, is_current=True
        ).first()
        if not session:
            return cls.objects.none()
        return cls.objects.filter(school=school, session=session)

    def save(self, *args, **kwargs):
        if self.is_current:
            # Only one term can be current across all sessions for a school
            Term.objects.filter(
                school=self.school, is_current=True
            ).exclude(pk=self.pk).update(is_current=False)
        super().save(*args, **kwargs)


class AuditLog(TenantScopedModel):
    """Append-only record of who changed critical financial/academic records.

    Populated by signals in ``core.audit`` for payments, invoices, scores,
    payslips and disbursements. ``changes`` holds either a field diff for
    updates (``{field: [old, new]}``) or a full snapshot for deletes.
    """

    class Action(models.TextChoices):
        CREATE = 'CREATE', _('created')
        UPDATE = 'UPDATE', _('updated')
        DELETE = 'DELETE', _('deleted')

    actor = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
        verbose_name=_('actor'),
    )
    model_name = models.CharField(max_length=50, db_index=True, verbose_name=_('model'))
    object_id = models.CharField(max_length=50, db_index=True, verbose_name=_('object id'))
    action = models.CharField(max_length=10, choices=Action.choices, verbose_name=_('action'))
    summary = models.CharField(max_length=200, blank=True, verbose_name=_('summary'))
    changes = models.JSONField(
        default=dict,
        blank=True,
        encoder=DjangoJSONEncoder,
        verbose_name=_('changes'),
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name=_('created at'))

    class Meta:
        verbose_name = _('audit log')
        verbose_name_plural = _('audit logs')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.action} {self.model_name} #{self.object_id} by {self.actor or "system"}'
