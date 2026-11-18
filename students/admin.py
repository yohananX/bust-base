from django.contrib import admin
from django import forms
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect
from django.utils.translation import gettext_lazy as _

from .models import (
    AcademicStage,
    SchoolClass,
    Student,
    ClassEnrollment,
    ClassOffering,
    SessionPreparation,
    StudentSessionMovement,
    StudentGuardianLink,
)


# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------

class ClassEnrollmentInline(admin.TabularInline):
    """Read-only inline showing enrollment history."""
    model = ClassEnrollment
    extra = 0
    readonly_fields = [
        'student', 'school_class', 'session', 'class_offering',
        'enrolled_on', 'is_current',
    ]
    can_delete = False
    max_num = 0  # prevent adding new ones from inline

    def has_add_permission(self, request, obj=None):
        return False


class StudentGuardianLinkInline(admin.TabularInline):
    model = StudentGuardianLink
    extra = 1
    autocomplete_fields = ['guardian']


# ---------------------------------------------------------------------------
# AcademicStage Admin
# ---------------------------------------------------------------------------

class AcademicStageAdminForm(forms.ModelForm):
    class Meta:
        model = AcademicStage
        fields = ['name', 'display_order', 'next_stage', 'is_active', 'school']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        school_id = self.instance.school_id or self.data.get('school') or self.initial.get('school')
        choices = AcademicStage.objects.none()
        if school_id:
            choices = AcademicStage.objects.filter(school_id=school_id)
            if self.instance.pk:
                choices = choices.exclude(pk=self.instance.pk)
        self.fields['next_stage'].queryset = choices.order_by('display_order', 'name')


@admin.register(AcademicStage)
class AcademicStageAdmin(admin.ModelAdmin):
    list_display = ['name', 'next_stage', 'display_order', 'is_active', 'school']
    list_filter = ['is_active', 'school']
    search_fields = ['name']
    ordering = ['display_order', 'name']
    form = AcademicStageAdminForm


# ---------------------------------------------------------------------------
# SchoolClass Admin
# ---------------------------------------------------------------------------

class SchoolClassAdminForm(forms.ModelForm):
    """Stage-only class form.

    The academic stage is the single classification field — there is no
    level input and no derived classification snapshot anywhere.
    """

    class Meta:
        model = SchoolClass
        fields = ['name', 'academic_stage', 'next_class', 'is_active', 'school']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        school_id = self.instance.school_id or self.data.get('school') or self.initial.get('school')
        stage_choices = AcademicStage.objects.none()
        class_choices = SchoolClass.objects.none()
        if school_id:
            stage_choices = AcademicStage.objects.filter(school_id=school_id)
            class_choices = SchoolClass.objects.filter(school_id=school_id)
            if self.instance.pk:
                class_choices = class_choices.exclude(pk=self.instance.pk)
        self.fields['academic_stage'].queryset = stage_choices.order_by('display_order', 'name')
        self.fields['next_class'].queryset = class_choices.select_related(
            'academic_stage'
        ).order_by('academic_stage__display_order', 'name')


@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ['name', 'academic_stage', 'next_class', 'is_active', 'school']
    list_filter = ['academic_stage', 'is_active', 'school']
    search_fields = ['name', 'academic_stage__name']
    autocomplete_fields = ['academic_stage']
    list_select_related = ['school', 'academic_stage']
    form = SchoolClassAdminForm


@admin.register(ClassOffering)
class ClassOfferingAdmin(admin.ModelAdmin):
    list_display = ['school_class', 'academic_session', 'school']
    list_filter = ['academic_session', 'school']
    search_fields = ['school_class__name', 'academic_session__name']
    autocomplete_fields = ['school_class', 'academic_session']
    list_select_related = ['school', 'school_class', 'academic_session']


@admin.register(SessionPreparation)
class SessionPreparationAdmin(admin.ModelAdmin):
    list_display = [
        'source_session', 'target_session', 'status',
        'proposals_generated_at', 'confirmed_at', 'school',
    ]
    list_filter = ['status', 'school']
    search_fields = ['source_session__name', 'target_session__name']
    list_select_related = ['school', 'source_session', 'target_session']
    readonly_fields = [
        'proposals_generated_at', 'confirmed_at', 'created_at', 'updated_at',
    ]


@admin.register(StudentSessionMovement)
class StudentSessionMovementAdmin(admin.ModelAdmin):
    list_display = [
        'student', 'preparation', 'action', 'proposed_class',
        'destination_class', 'is_override', 'school',
    ]
    list_filter = ['action', 'proposal_basis', 'is_override', 'school']
    search_fields = [
        'student__admission_number', 'student__user__first_name',
        'student__user__last_name',
    ]
    list_select_related = [
        'school', 'student__user', 'preparation',
        'proposed_class', 'destination_class',
    ]


# ---------------------------------------------------------------------------
# Student Admin
# ---------------------------------------------------------------------------

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ['user', 'admission_number', 'gender', 'status', 'state_of_origin', 'local_government_area', 'school']
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

        school_ids = set(queryset.values_list('school_id', flat=True))
        if len(school_ids) != 1:
            self.message_user(
                request,
                _('Select students from exactly one school.'),
                level='ERROR',
            )
            return redirect(request.get_full_path())
        school_id = school_ids.pop()

        if 'apply' in request.POST:
            # --- Intermediate form submission --------------------------------
            session_id = request.POST.get('session')
            if not session_id:
                self.message_user(request, _('Please select a target session.'), level='ERROR')
                return redirect(request.get_full_path())

            try:
                target_session = AcademicSession.objects.get(
                    pk=session_id, school_id=school_id
                )
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
                    target_class = SchoolClass.objects.get(
                        pk=class_id, school_id=school_id
                    )
                except SchoolClass.DoesNotExist:
                    skipped_count += 1
                    continue

                try:
                    student.promote_to(target_session, target_class)
                except ValidationError:
                    skipped_count += 1
                else:
                    promoted_count += 1

            parts = []
            if promoted_count:
                parts.append(_('%(count)d student(s) promoted.') % {'count': promoted_count})
            if skipped_count:
                parts.append(
                    _('%(count)d student(s) skipped (lifecycle status, missing class, or missing offering).')
                    % {'count': skipped_count}
                )
            msg = ' '.join(parts) if parts else _('No students were promoted.')
            self.message_user(request, msg)

            return redirect(request.get_full_path())

        # --- Initial action: show intermediate page -------------------------
        # Filter out withdrawn/graduated from the actionable list
        actionable = queryset.exclude(status__in=[Student.WITHDRAWN, Student.GRADUATED])
        sessions = AcademicSession.objects.filter(school_id=school_id)
        classes = SchoolClass.objects.filter(school_id=school_id)

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


# ---------------------------------------------------------------------------
# StudentGuardianLink Admin
# ---------------------------------------------------------------------------

@admin.register(StudentGuardianLink)
class StudentGuardianLinkAdmin(admin.ModelAdmin):
    list_display = ['student', 'guardian', 'relationship', 'occupation', 'address', 'authorized_pickup_person', 'is_primary_contact']
    list_filter = ['relationship', 'is_primary_contact']
    search_fields = [
        'student__user__username', 'student__user__first_name',
        'student__user__last_name',
        'guardian__username', 'guardian__first_name', 'guardian__last_name',
    ]
