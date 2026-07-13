from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import Score, Subject, TeacherAssignment


# ---------------------------------------------------------------------------
# Subject Admin
# ---------------------------------------------------------------------------

@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'pass_mark', 'school']
    list_filter = ['school']
    search_fields = ['name', 'code']


# ---------------------------------------------------------------------------
# TeacherAssignment Admin
# ---------------------------------------------------------------------------

@admin.register(TeacherAssignment)
class TeacherAssignmentAdmin(admin.ModelAdmin):
    list_display = ['teacher', 'subject', 'school_class', 'session', 'school']
    list_filter = ['session', 'subject', 'school_class', 'school']
    search_fields = [
        'teacher__username',
        'teacher__first_name',
        'teacher__last_name',
        'subject__name',
    ]


# ---------------------------------------------------------------------------
# Score Admin
# ---------------------------------------------------------------------------

@admin.register(Score)
class ScoreAdmin(admin.ModelAdmin):
    list_display = [
        'student', 'subject', 'term', 'test_1', 'test_2', 'test_3',
        'exam_score', 'total_score', 'passed', 'position', 'school',
    ]
    list_filter = ['term', 'subject', 'student__enrollments__school_class', 'school']
    search_fields = [
        'student__user__username', 'student__user__first_name',
        'student__user__last_name', 'student__admission_number',
    ]
    readonly_fields = ['position', 'entered_by', 'updated_at']
    actions = ['compute_positions']

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    @admin.display(description=_('total score'))
    def total_score(self, obj):
        """Return the computed total (tests + exam)."""
        return obj.total_score

    @admin.display(description=_('passed'))
    def passed(self, obj):
        """Colored pass/fail indicator."""
        if obj.passed is None:
            return '—'
        return '✅' if obj.passed else '❌'

    # ------------------------------------------------------------------
    # Compute positions action
    # ------------------------------------------------------------------

    def compute_positions(self, request, queryset):
        """Compute Olympic/dense ranking for selected scores."""
        from .ranking import compute_positions

        updated = 0
        processed = set()
        for score in queryset.select_related('student', 'subject', 'term'):
            # Get the student's current school class
            current_enrollment = score.student.enrollments.filter(is_current=True).first()
            if not current_enrollment:
                continue
            key = (current_enrollment.school_class_id, score.subject_id, score.term_id)
            if key in processed:
                continue
            processed.add(key)
            updated += compute_positions(
                current_enrollment.school_class,
                score.subject,
                score.term,
            )

        self.message_user(
            request,
            _('Positions computed for %(count)d score(s).') % {'count': updated},
        )

    compute_positions.short_description = _('Compute ranking positions for selected scores')
