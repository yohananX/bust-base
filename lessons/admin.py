from django.contrib import admin

from .models import (
    LessonClass,
    LessonEnrollment,
    LessonPeriod,
    LessonTeacherAssignment,
)


@admin.register(LessonPeriod)
class LessonPeriodAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_date', 'end_date', 'status', 'school')
    list_filter = ('status',)
    search_fields = ('name',)


@admin.register(LessonClass)
class LessonClassAdmin(admin.ModelAdmin):
    list_display = ('name', 'period', 'fee_amount', 'capacity', 'school')
    list_filter = ('period',)
    search_fields = ('name',)


@admin.register(LessonTeacherAssignment)
class LessonTeacherAssignmentAdmin(admin.ModelAdmin):
    list_display = ('lesson_class', 'teacher', 'school')
    autocomplete_fields = ('teacher',)


@admin.register(LessonEnrollment)
class LessonEnrollmentAdmin(admin.ModelAdmin):
    list_display = ('child_name', 'lesson_class', 'parent_name', 'status', 'registered_on', 'school')
    list_filter = ('status', 'source', 'lesson_class__period')
    search_fields = ('external_name', 'parent_name', 'parent_phones__0')