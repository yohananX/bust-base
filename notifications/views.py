from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .models import NotificationLog


@login_required
def notification_bell_count(request):
    """Return the count of unread in-app notifications for the current user.

    Only IN_APP rows can be unread — EMAIL/SMS rows are outbound delivery
    records and never count toward the bell badge.
    """
    count = NotificationLog.objects.filter(
        recipient=request.user,
        channel=NotificationLog.Channel.IN_APP,
        status=NotificationLog.Status.QUEUED,
        dismissed=False,
    ).count()
    return JsonResponse({'unread_count': count})


@login_required
def notification_bell_dropdown(request):
    """Return the dropdown fragment with the last 10 in-app notifications.

    Opening the dropdown marks the user's in-app notifications as read
    (QUEUED -> SENT), so the badge reflects genuinely unread items.
    Dismissed notifications are hidden; outbound EMAIL/SMS records never
    appear here (the school admin log page is their home).
    """
    NotificationLog.objects.filter(
        recipient=request.user,
        channel=NotificationLog.Channel.IN_APP,
        status=NotificationLog.Status.QUEUED,
    ).update(status=NotificationLog.Status.SENT)

    notifications_qs = NotificationLog.objects.filter(
        recipient=request.user,
        channel=NotificationLog.Channel.IN_APP,
        dismissed=False,
    ).order_by('-created_at')[:10]
    return render(request, 'components/notification_bell_dropdown.html', {
        'notifications': notifications_qs,
    })


@login_required
@require_POST
def notification_dismiss(request, pk):
    """Hide a notification from the recipient's bell dropdown.

    The log row is kept untouched (status, message, timestamps) — only the
    per-recipient visibility flag flips, so the record remains for audit.
    """
    updated = NotificationLog.objects.filter(
        pk=pk,
        recipient=request.user,
    ).update(dismissed=True)
    if not updated:
        return JsonResponse({'ok': False, 'error': 'not found'}, status=404)
    return JsonResponse({'ok': True})