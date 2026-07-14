import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_email(user, subject, message):
    """Send email to user.

    For now, uses Django's console backend (prints to stdout).
    In production, swap EMAIL_BACKEND and configure SMTP settings via env vars.
    """
    if not user.email:
        logger.warning(
            'Cannot send email to user %s (id=%s): no email address on record.',
            user.get_username(), user.pk,
        )
        raise ValueError(f'User {user.get_username()} has no email address.')
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


def send_sms(user, message):
    """Send SMS to user.

    For now, logs to console.
    In production, integrate with Termii or Africa's Talking via env vars.
    """
    phone = getattr(user, 'phone_number', None) or getattr(user, 'phone', None)
    if not phone:
        logger.warning(
            'Cannot send SMS to user %s (id=%s): no phone number on record.',
            user.get_username(), user.pk,
        )
        return
    logger.info('SMS to %s (%s): %s', user.get_username(), phone, message)


def notify(*, recipient, channel, subject='', message, reference=''):
    """Create a NotificationLog row and enqueue the send as a Django-Q2 task.

    Returns the NotificationLog instance.
    """
    from .models import NotificationLog
    from django_q.tasks import async_task

    log = NotificationLog.objects.create(
        school=recipient.school,
        recipient=recipient,
        channel=channel,
        subject=subject,
        message=message,
        reference=reference,
        status=NotificationLog.Status.QUEUED,
    )
    # Enqueue the send task — pass the log ID so the task can update it
    async_task('notifications.tasks.process_notification', log.id)
    return log
