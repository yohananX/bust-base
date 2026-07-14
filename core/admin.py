from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from .models import School, AcademicSession, Term


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ['name', 'short_code', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'short_code']
    prepopulated_fields = {'short_code': ('name',)}


@admin.register(AcademicSession)
class AcademicSessionAdmin(admin.ModelAdmin):
    list_display = ['name', 'school', 'start_date', 'end_date', 'is_current']
    list_filter = ['is_current', 'school']
    search_fields = ['name', 'school__name']


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ['name', 'session', 'school', 'start_date', 'end_date', 'is_current', 'results_published']
    list_filter = ['is_current', 'results_published', 'school']
    search_fields = ['name', 'session__name']
    actions = ['publish_results', 'unpublish_results']

    @admin.action(description=_('Publish results for selected terms'))
    def publish_results(self, request, queryset):
        """Set results_published=True for selected terms."""
        updated = queryset.update(results_published=True)
        self.message_user(
            request,
            _('Results published for %(count)d term(s).') % {'count': updated},
            level=messages.SUCCESS,
        )

    @admin.action(description=_('Unpublish results for selected terms'))
    def unpublish_results(self, request, queryset):
        """Set results_published=False for selected terms."""
        updated = queryset.update(results_published=False)
        self.message_user(
            request,
            _('Results unpublished for %(count)d term(s).') % {'count': updated},
            level=messages.SUCCESS,
        )
