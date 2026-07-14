from django.utils import timezone


def process_notification(notification_id):
    """Process a queued notification — send it and update the log."""
    from .models import NotificationLog
    from .utils import send_email, send_sms

    try:
        log = NotificationLog.objects.get(id=notification_id)
    except NotificationLog.DoesNotExist:
        return

    try:
        if log.channel == NotificationLog.Channel.EMAIL:
            send_email(log.recipient, log.subject, log.message)
        elif log.channel == NotificationLog.Channel.SMS:
            send_sms(log.recipient, log.message)

        log.status = NotificationLog.Status.SENT
        log.sent_at = timezone.now()
        log.save(update_fields=['status', 'sent_at'])
    except Exception as e:
        log.status = NotificationLog.Status.FAILED
        log.error_message = str(e)
        log.save(update_fields=['status', 'error_message'])
