from django.contrib import admin
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
    list_display = ['name', 'session', 'school', 'start_date', 'end_date', 'is_current']
    list_filter = ['is_current', 'school']
    search_fields = ['name', 'session__name']
