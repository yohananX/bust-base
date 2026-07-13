from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Custom UserAdmin that exposes school and role fields."""

    list_display = [
        'username', 'email', 'school', 'role', 'is_staff', 'is_active'
    ]
    list_filter = ['role', 'is_staff', 'is_active', 'is_superuser', 'school']

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        (_('Personal info'), {
            'fields': ('first_name', 'last_name', 'email', 'phone_number')
        }),
        (_('School info'), {
            'fields': ('school', 'role')
        }),
        (
            _('Permissions'),
            {
                'fields': (
                    'is_active',
                    'is_staff',
                    'is_superuser',
                    'groups',
                    'user_permissions',
                ),
            },
        ),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'username', 'password1', 'password2', 'email',
                'school', 'role',
            ),
        }),
    )
    search_fields = ['username', 'email', 'first_name', 'last_name']
