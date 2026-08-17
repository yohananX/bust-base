from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render

from .models import NotificationLog


@login_required
def notification_bell_count(request):
    """Return the count of QUEUED (unread) notifications for the current user."""
    count = NotificationLog.objects.filter(
        recipient=request.user,
        status=NotificationLog.Status.QUEUED,
    ).count()
    return JsonResponse({'unread_count': count})


@login_required
def notification_bell_dropdown(request):
    """Return the dropdown fragment with the last 10 notifications for the current user."""
    notifications_qs = NotificationLog.objects.filter(
        recipient=request.user,
    ).select_related('recipient').order_by('-created_at')[:10]
    return render(request, 'components/notification_bell_dropdown.html', {
        'notifications': notifications_qs,
    })
