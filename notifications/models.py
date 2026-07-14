from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import TenantScopedModel


class NotificationLog(TenantScopedModel):
    """Records a notification sent (or queued to be sent) to a recipient."""

    class Channel(models.TextChoices):
        EMAIL = 'EMAIL', _('Email')
        SMS = 'SMS', _('SMS')

    class Status(models.TextChoices):
        QUEUED = 'QUEUED', _('Queued')
        SENT = 'SENT', _('Sent')
        FAILED = 'FAILED', _('Failed')

    recipient = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name=_('recipient'),
    )
    channel = models.CharField(
        max_length=10,
        choices=Channel.choices,
        verbose_name=_('channel'),
    )
    subject = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_('subject'),
    )
    message = models.TextField(verbose_name=_('message'))
    reference = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        verbose_name=_('reference'),
        help_text=_('e.g. "invoice:42", "term-results:7"'),
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.QUEUED,
        verbose_name=_('status'),
    )
    error_message = models.TextField(
        blank=True,
        verbose_name=_('error message'),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('created at'),
    )
    sent_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('sent at'),
    )

    class Meta:
        verbose_name = _('notification log')
        verbose_name_plural = _('notification logs')
        ordering = ['-created_at']

    def __str__(self):
        return (
            f'{self.get_channel_display()} to {self.recipient} '
            f'[{self.get_status_display()}]'
        )
