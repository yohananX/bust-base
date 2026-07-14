from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import NotificationLog


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = [
        'recipient', 'channel', 'reference', 'status',
        'created_at', 'sent_at',
    ]
    list_filter = ['channel', 'status', 'school']
    search_fields = ['recipient__email', 'recipient__username', 'reference']
    readonly_fields = [
        'recipient', 'channel', 'subject', 'message', 'reference',
        'status', 'error_message', 'created_at', 'sent_at', 'school',
    ]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
