from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.views.generic.base import View

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from academics.models import Score, TeacherAssignment
from core.models import Term
from students.models import ClassEnrollment


VALID_SCORE_FIELDS = {'test_1', 'test_2', 'test_3', 'exam_score'}
FIELD_MAX_VALUES = {
    'test_1': 10,
    'test_2': 10,
    'test_3': 10,
    'exam_score': 70,
}


class TeacherAssignmentListView(RoleRequiredMixin, View):
    """Lists all current-term teaching assignments for the logged-in teacher."""

    allowed_roles = [Roles.TEACHER]

    def get(self, request):
        assignments = TeacherAssignment.objects.filter(
            teacher=request.user,
            session__is_current=True,
        ).select_related('subject', 'school_class', 'session')
        return render(request, 'academics/teacher/assignment_list.html', {
            'assignments': assignments,
        })


class TeacherScoreGridView(RoleRequiredMixin, View):
    """Displays a grid of scores for students in a given assignment."""

    allowed_roles = [Roles.TEACHER]

    def get(self, request, pk):
        assignment = get_object_or_404(TeacherAssignment, pk=pk)
        if assignment.teacher != request.user:
            return HttpResponseForbidden("Not your assignment")

        current_term = Term.objects.filter(
            school=request.school,
            is_current=True,
        ).first()

        enrollments = ClassEnrollment.objects.filter(
            school_class=assignment.school_class,
            session=assignment.session,
            is_current=True,
        ).select_related('student', 'student__user')

        scores = []
        for enrollment in enrollments:
            score, created = Score.objects.get_or_create(
                student=enrollment.student,
                subject=assignment.subject,
                term=current_term,
                defaults={
                    'school': request.school,
                    'entered_by': request.user,
                },
            )
            scores.append(score)

        scores.sort(key=lambda s: s.student.admission_number)

        return render(request, 'academics/teacher/score_grid.html', {
            'assignment': assignment,
            'scores': scores,
            'term': current_term,
        })


class TeacherScoreUpdateView(RoleRequiredMixin, View):
    """Handles AJAX-style updates to individual score fields."""

    allowed_roles = [Roles.TEACHER]

    def post(self, request, pk, score_pk):
        score = get_object_or_404(Score, pk=score_pk)

        # Verify teacher owns this score's assignment
        enrollment = ClassEnrollment.objects.filter(
            student=score.student,
            session=score.term.session,
            is_current=True,
        ).first()

        if not enrollment or not TeacherAssignment.objects.filter(
            teacher=request.user,
            subject=score.subject,
            school_class=enrollment.school_class,
            session=score.term.session,
        ).exists():
            return HttpResponseForbidden("Not your assignment")

        # htmx sends the field name as the POST key (e.g. test_1=8)
        field_name = None
        raw_value = None
        for key in request.POST:
            if key in VALID_SCORE_FIELDS:
                field_name = key
                raw_value = request.POST.get(key, '').strip()
                break

        if field_name is None:
            return HttpResponse("Invalid field", status=400)

        if raw_value == '':
            value = None
        else:
            try:
                value = int(raw_value)
            except (ValueError, TypeError):
                return HttpResponse("Value must be a whole number", status=400)

        max_value = FIELD_MAX_VALUES[field_name]
        if value is not None and (value < 0 or value > max_value):
            return HttpResponse(
                f"{field_name.replace('_', ' ').title()} must be between 0 and {max_value}",
                status=400,
            )

        setattr(score, field_name, value)
        score.entered_by = request.user
        score.save(update_fields=[field_name, 'entered_by', 'updated_at'])

        display_value = value if value is not None else ''

        # Build the primary response (the updated field cell)
        primary = f'<span class="tabular-nums">{display_value}</span>'

        # Build OOB swap for Total cell
        total = score.total_score
        total_content = f'<span>{total}</span>'

        # Build OOB swap for Status cell
        if not score.is_complete:
            status_html = '<span class="status-tag status-tag--pending">Pending</span>'
        elif score.passed:
            status_html = '<span class="status-stamp status-stamp--pass">Pass</span>'
        else:
            status_html = '<span class="status-tag status-tag--fail">Fail</span>'

        # Combine: primary response + OOB swaps
        response_html = (
            f'{primary}'
            f'<div id="total-{score.pk}" hx-swap-oob="innerHTML">{total_content}</div>'
            f'<div id="status-{score.pk}" hx-swap-oob="innerHTML">{status_html}</div>'
        )
        return HttpResponse(response_html)
