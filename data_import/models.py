from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import TenantScopedModel


class ImportLog(TenantScopedModel):
    """Records each bulk CSV import operation."""

    IMPORT_TYPES = [
        ('classes', 'Classes'),
        ('subjects', 'Subjects'),
        ('students', 'Students'),
        ('staff', 'Staff'),
    ]

    import_type = models.CharField(max_length=20, choices=IMPORT_TYPES, verbose_name=_('import type'))
    filename = models.CharField(max_length=255, verbose_name=_('filename'))
    total_rows = models.PositiveIntegerField(default=0, verbose_name=_('total rows'))
    created_count = models.PositiveIntegerField(default=0, verbose_name=_('created count'))
    skipped_count = models.PositiveIntegerField(default=0, verbose_name=_('skipped count'))
    error_count = models.PositiveIntegerField(default=0, verbose_name=_('error count'))
    errors = models.JSONField(default=list, blank=True, verbose_name=_('errors'))
    dry_run = models.BooleanField(default=False, verbose_name=_('dry run'))
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name=_('imported by'),
    )
    imported_at = models.DateTimeField(auto_now_add=True, verbose_name=_('imported at'))

    class Meta:
        verbose_name = _('import log')
        verbose_name_plural = _('import logs')
        ordering = ['-imported_at']

    def __str__(self):
        return f"{self.get_import_type_display()} import — {self.filename} ({self.imported_at:%Y-%m-%d %H:%M})"
