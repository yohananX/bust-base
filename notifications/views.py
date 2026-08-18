from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .models import NotificationLog


@login_required
def notification_bell_count(request):
    """Return the count of unread in-app notifications for the current user.

    Only IN_APP rows can be unread — EMAIL/SMS rows are outbound delivery
    records and never count toward the bell badge. ``max_pk`` is the highest
    row pk the user has right now; the client seeds its poll cursor with it
    so that only rows arriving after page load ever toast.
    """
    qs = NotificationLog.objects.filter(
        recipient=request.user,
        channel=NotificationLog.Channel.IN_APP,
        dismissed=False,
    )
    max_pk = qs.order_by('-pk').values_list('pk', flat=True).first() or 0
    count = qs.filter(status=NotificationLog.Status.QUEUED).count()
    return JsonResponse({'unread_count': count, 'max_pk': max_pk})


@login_required
def notification_bell_poll(request):
    """Poll for notifications created after ``since`` (a row pk).

    Returns the unread count plus the new rows (max 5). The client only
    toasts rows it has not seen before — the backlog never toast-storms on
    login, it just sits in the bell and badge.
    """
    since = request.GET.get('since')
    try:
        since = int(since)
    except (TypeError, ValueError):
        since = 0

    qs = NotificationLog.objects.filter(
        recipient=request.user,
        channel=NotificationLog.Channel.IN_APP,
        dismissed=False,
    )
    new_rows = qs.filter(pk__gt=since).order_by('pk')[:5]
    unread_count = qs.filter(status=NotificationLog.Status.QUEUED).count()

    return JsonResponse({
        'unread_count': unread_count,
        'new_notifications': [
            {
                'pk': n.pk,
                'subject': n.subject or '',
                'message': n.message,
                'url': n.url or '',
                'action_label': n.action_label or '',
            }
            for n in new_rows
        ],
    })


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


@login_required
@require_POST
def notification_clear_all(request):
    """Dismiss every non-dismissed in-app notification of the current user.

    Rows are hidden, never deleted — the audit trail stays intact.
    """
    cleared = NotificationLog.objects.filter(
        recipient=request.user,
        channel=NotificationLog.Channel.IN_APP,
        dismissed=False,
    ).update(dismissed=True)
    return JsonResponse({'ok': True, 'cleared': cleared})
