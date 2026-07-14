"""Notification log view for school admin portal."""
from django.shortcuts import render
from django.views.generic.base import View

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from notifications.models import NotificationLog


class NotificationLogView(RoleRequiredMixin, View):
    """Read-only list of notification logs with filters."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        logs = NotificationLog.objects.filter(
            school=school
        ).select_related('recipient').order_by('-created_at')

        # Filters
        status = request.GET.get('status', '')
        if status:
            logs = logs.filter(status=status)

        channel = request.GET.get('channel', '')
        if channel:
            logs = logs.filter(channel=channel)

        q = request.GET.get('q', '')
        if q:
            logs = logs.filter(
                subject__icontains=q
            ) | logs.filter(
                recipient__email__icontains=q
            )

        context = {
            'logs': logs,
            'filter_status': status,
            'filter_channel': channel,
            'q': q,
        }
        return render(request, 'school_admin/notification_log.html', context)
