from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from .models import GradeScale, Score, Subject, TeacherAssignment, TermResult


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
    actions = ['compute_positions', 'publish_results']

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
            return '\u2014'
        return '\u2705' if obj.passed else '\u274C'

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

    # ------------------------------------------------------------------
    # Publish results action (intermediate page)
    # ------------------------------------------------------------------

    @admin.action(description=_('Publish results for selected scores'))
    def publish_results(self, request, queryset):
        """Publish results for terms linked to selected scores.

        Shows an intermediate page listing the unique terms the selected
        scores belong to. On confirmation, sets results_published=True
        on the chosen term.
        """
        from django.contrib.admin import helpers
        from core.models import Term

        if 'apply' in request.POST:
            term_id = request.POST.get('term')
            if not term_id:
                self.message_user(
                    request,
                    _('Please select a term.'),
                    level=messages.ERROR,
                )
                return HttpResponseRedirect(request.get_full_path())

            try:
                term = Term.objects.get(pk=term_id)
            except Term.DoesNotExist:
                self.message_user(
                    request,
                    _('Selected term not found.'),
                    level=messages.ERROR,
                )
                return HttpResponseRedirect(request.get_full_path())

            term.results_published = True
            term.save(update_fields=['results_published'])

            # Notify primary-contact guardians of students who have scores
            from notifications.utils import notify
            from notifications.models import NotificationLog

            # Dedup guard: skip notifications if already sent for this term
            if NotificationLog.objects.filter(
                reference='term-results:{}'.format(term.id)
            ).exists():
                self.message_user(
                    request,
                    _('Notifications already sent for term "%(term)s". Skipping notification loop.') % {'term': term},
                    level=messages.WARNING,
                )
            else:
                student_ids = (
                    queryset.filter(term=term)
                    .values_list('student', flat=True)
                    .distinct()
                )
                from students.models import StudentGuardianLink

                guardian_ids = set(
                    StudentGuardianLink.objects.filter(
                        student__in=list(student_ids),
                        is_primary_contact=True,
                    ).values_list('guardian', flat=True)
                )

                for guardian in get_user_model().objects.filter(pk__in=guardian_ids):
                    notify(
                        recipient=guardian,
                        channel='EMAIL',
                        subject=_('Results available for {term}').format(term=term.name),
                        message=_(
                            'Results for {term} are now available.'
                        ).format(term=term.name),
                        reference='term-results:{}'.format(term.id),
                    )

                self.message_user(
                    request,
                    _('Results published for term "%(term)s".') % {'term': term},
                    level=messages.SUCCESS,
                )
            return HttpResponseRedirect(request.get_full_path())

        # Intermediate page: show terms that the selected scores belong to
        term_ids = queryset.values_list('term', flat=True).distinct()
        terms = Term.objects.filter(pk__in=term_ids)

        if not terms:
            self.message_user(
                request,
                _('No terms found for the selected scores.'),
                level=messages.WARNING,
            )
            return HttpResponseRedirect(request.get_full_path())

        context = {
            'title': _('Publish results for term'),
            'queryset': queryset,
            'terms': terms,
            'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
            'opts': self.model._meta,
            'media': self.media,
        }
        return render(request, 'admin/academics/publish_results.html', context)


# ---------------------------------------------------------------------------
# GradeScale Admin
# ---------------------------------------------------------------------------

@admin.register(GradeScale)
class GradeScaleAdmin(admin.ModelAdmin):
    list_display = ['label', 'min_score', 'max_score', 'remark', 'school']
    list_filter = ['school']


# ---------------------------------------------------------------------------
# TermResult Admin
# ---------------------------------------------------------------------------

@admin.register(TermResult)
class TermResultAdmin(admin.ModelAdmin):
    list_display = ['student', 'term', 'grand_total', 'average', 'overall_position']
    list_filter = ['term']
    readonly_fields = ['computed_at']
    actions = ['compute_term_summaries']

    @admin.display(description=_('average'))
    def average(self, obj):
        return f"{obj.average:.2f}"

    def compute_term_summaries(self, request, queryset):
        """Compute term summaries for selected term results."""
        from .ranking import compute_term_summary
        from students.models import SchoolClass

        # Get unique (school_class, term) pairs
        pairs = set()
        for tr in queryset.select_related('term', 'student__enrollments__school_class'):
            for enrollment in tr.student.enrollments.filter(is_current=True):
                pairs.add((enrollment.school_class, tr.term))

        total = 0
        for school_class, term in pairs:
            total += compute_term_summary(school_class, term)

        self.message_user(
            request,
            _('Updated %(count)d term result(s).') % {'count': total},
        )

    compute_term_summaries.short_description = _('Compute term summaries for selected results')
