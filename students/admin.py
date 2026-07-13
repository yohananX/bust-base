from django.contrib import admin, messages
from django.shortcuts import render, redirect
from django.urls import path
from django.utils.translation import gettext_lazy as _

from .models import SchoolClass, Student, ClassEnrollment, StudentGuardianLink


# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------

class ClassEnrollmentInline(admin.TabularInline):
    """Read-only inline showing enrollment history."""
    model = ClassEnrollment
    extra = 0
    readonly_fields = ['student', 'school_class', 'session', 'enrolled_on', 'is_current']
    can_delete = False
    max_num = 0  # prevent adding new ones from inline

    def has_add_permission(self, request, obj=None):
        return False


class StudentGuardianLinkInline(admin.TabularInline):
    model = StudentGuardianLink
    extra = 1
    autocomplete_fields = ['guardian']


# ---------------------------------------------------------------------------
# SchoolClass Admin
# ---------------------------------------------------------------------------

@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ['name', 'level', 'is_active', 'school']
    list_filter = ['level', 'is_active', 'school']
    search_fields = ['name', 'level']


# ---------------------------------------------------------------------------
# Student Admin
# ---------------------------------------------------------------------------

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ['user', 'admission_number', 'gender', 'status', 'school']
    list_filter = ['status', 'gender', 'school']
    search_fields = [
        'user__username', 'user__first_name', 'user__last_name',
        'admission_number',
    ]
    inlines = [ClassEnrollmentInline, StudentGuardianLinkInline]
    actions = ['promote_students']

    # ------------------------------------------------------------------
    # Promotion action
    # ------------------------------------------------------------------

    def promote_students(self, request, queryset):
        """Custom admin action to promote selected students to a new session/class."""
        from core.models import AcademicSession
        from .models import SchoolClass

        if 'apply' in request.POST:
            # --- Intermediate form submission --------------------------------
            session_id = request.POST.get('session')
            if not session_id:
                self.message_user(request, _('Please select a target session.'), level='ERROR')
                return redirect(request.get_full_path())

            try:
                target_session = AcademicSession.objects.get(pk=session_id)
            except AcademicSession.DoesNotExist:
                self.message_user(request, _('Selected session does not exist.'), level='ERROR')
                return redirect(request.get_full_path())

            promoted_count = 0
            skipped_count = 0

            for student in queryset:
                # Exclude withdrawn or graduated students
                if student.status in (Student.WITHDRAWN, Student.GRADUATED):
                    skipped_count += 1
                    continue

                # Determine target class: use per-student override or skip
                class_key = f'class_{student.pk}'
                class_id = request.POST.get(class_key)
                if not class_id:
                    skipped_count += 1
                    continue

                try:
                    target_class = SchoolClass.objects.get(pk=class_id)
                except SchoolClass.DoesNotExist:
                    skipped_count += 1
                    continue

                student.promote_to(target_session, target_class)
                promoted_count += 1

            parts = []
            if promoted_count:
                parts.append(_('%(count)d student(s) promoted.') % {'count': promoted_count})
            if skipped_count:
                parts.append(
                    _('%(count)d student(s) skipped (withdrawn/graduated or missing class).')
                    % {'count': skipped_count}
                )
            msg = ' '.join(parts) if parts else _('No students were promoted.')
            self.message_user(request, msg)

            return redirect(request.get_full_path())

        # --- Initial action: show intermediate page -------------------------
        # Filter out withdrawn/graduated from the actionable list
        actionable = queryset.exclude(status__in=[Student.WITHDRAWN, Student.GRADUATED])
        sessions = AcademicSession.objects.filter(school=request.school)
        classes = SchoolClass.objects.filter(school=request.school)

        return render(
            request,
            'admin/students/promote_students.html',
            {
                'students': actionable,
                'sessions': sessions,
                'classes': classes,
                'title': _('Promote Students'),
                'action': 'promote_students',
                'select_across': request.POST.get('select_across', 0),
                'action_checkbox_name': admin.helpers.ACTION_CHECKBOX_NAME,
            },
        )

    promote_students.short_description = _('Promote selected students to a new session')

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'promote-students/',
                self.admin_site.admin_view(self.promote_students_view),
                name='students_student_promote',
            ),
        ]
        return custom_urls + urls

    def promote_students_view(self, request):
        """Standalone view for promotion (optional, kept for future extensibility)."""
        # This is a placeholder — the main promotion flow uses the action pattern above.
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['GET'])


# ---------------------------------------------------------------------------
# StudentGuardianLink Admin
# ---------------------------------------------------------------------------

@admin.register(StudentGuardianLink)
class StudentGuardianLinkAdmin(admin.ModelAdmin):
    list_display = ['student', 'guardian', 'relationship', 'is_primary_contact']
    list_filter = ['relationship', 'is_primary_contact']
    search_fields = [
        'student__user__username', 'student__user__first_name',
        'student__user__last_name',
        'guardian__username', 'guardian__first_name', 'guardian__last_name',
    ]
