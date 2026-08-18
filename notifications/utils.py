import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

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


def notify(*, recipient, channel, subject='', message, reference='', url='',
           action_label=''):
    """Create a NotificationLog row and deliver it.

    IN_APP rows stay QUEUED — that is the unread state the bell badge counts
    and the dropdown shows as "Unread". Opening the bell marks them SENT
    (read); the recipient can dismiss them (hidden, row kept).

    EMAIL/SMS rows are delivered synchronously in-process — no background
    worker required. The row flips to SENT on success, or FAILED with the
    error message when delivery cannot happen (e.g. no SMTP, no address).

    ``url`` is the deep link the bell row and the toast navigate to;
    ``action_label`` is an optional short CTA (e.g. "Review") rendered on
    the toast for action items.

    Returns the NotificationLog instance, or None when the recipient has no
    school (notification cannot be recorded for them).
    """
    from .models import NotificationLog

    school = getattr(recipient, 'school', None)
    if school is None:
        logger.warning(
            'Cannot notify user %s (id=%s): no school on record.',
            recipient.get_username(), recipient.pk,
        )
        return None

    log = NotificationLog.objects.create(
        school=school,
        recipient=recipient,
        channel=channel,
        subject=subject,
        message=message,
        reference=reference,
        url=url,
        action_label=action_label,
        status=NotificationLog.Status.QUEUED,
    )

    if channel == NotificationLog.Channel.IN_APP:
        return log

    # Outbound channels are delivered inline — synchronous and failure-safe,
    # so nothing ever lingers QUEUED waiting for a worker that may not run.
    try:
        if channel == NotificationLog.Channel.EMAIL:
            send_email(recipient, subject, message)
        elif channel == NotificationLog.Channel.SMS:
            send_sms(recipient, message)
        else:
            logger.warning(
                'Unknown notification channel %r — log kept QUEUED.', channel
            )
            return log
    except Exception as exc:
        log.status = NotificationLog.Status.FAILED
        log.error_message = str(exc)
        log.save(update_fields=['status', 'error_message'])
        logger.error(
            'Failed to deliver %s notification %s: %s', channel, log.pk, exc
        )
        return log

    log.status = NotificationLog.Status.SENT
    log.sent_at = timezone.now()
    log.save(update_fields=['status', 'sent_at'])
    return log


def notify_many(*, recipients, channel, subject='', message, reference='',
                url='', action_label=''):
    """Notify several recipients of the same event (one row each).

    Handles per-recipient dedup: any recipient who already has a row with
    this reference is skipped.

    Returns the list of created NotificationLog instances.
    """
    from .models import NotificationLog

    recipients = [r for r in recipients if r is not None]
    if not recipients:
        return []

    existing = set(
        NotificationLog.objects.filter(
            reference=reference,
            recipient_id__in=[r.pk for r in recipients],
        ).values_list('recipient_id', flat=True)
    )
    logs = []
    for recipient in recipients:
        if recipient.pk in existing:
            continue
        log = notify(
            recipient=recipient,
            channel=channel,
            subject=subject,
            message=message,
            reference=reference,
            url=url,
            action_label=action_label,
        )
        if log is not None:
            logs.append(log)
    return logs


def notify_admins(*, school, subject, message, reference='', url='',
                  action_label=''):
    """Notify every active admin of the school in-app (one row per admin).

    Only used for action items and exceptions — never for routine
    confirmations (those are the actor's toast feedback).

    Returns the list of created NotificationLog instances.
    """
    from accounts.models import Roles, User
    from .models import NotificationLog

    admins = User.objects.filter(
        school=school, role=Roles.ADMIN, is_active=True,
    )
    return notify_many(
        recipients=list(admins),
        channel=NotificationLog.Channel.IN_APP,
        subject=subject,
        message=message,
        reference=reference,
        url=url,
        action_label=action_label,
    )