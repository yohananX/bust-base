from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.generic.base import View
from django.contrib import messages

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
    """Dashboard for the teacher portal — status, alerts, scoring progress."""
    allowed_roles = [Roles.TEACHER]

    def get(self, request):
        assignments = TeacherAssignment.objects.filter(
            teacher=request.user,
            session__is_current=True,
        ).select_related('subject', 'school_class', 'session')

        subject_count = len(set(a.subject_id for a in assignments))
        class_count = len(set(a.school_class_id for a in assignments))

        class_ids = [a.school_class_id for a in assignments]

        current_term = Term.objects.filter(
            school=request.school, is_current=True,
        ).first()

        # Per-assignment progress + term-aware aggregates for the current term
        assignment_progress = []
        if current_term and assignments:
            subject_ids = list({a.subject_id for a in assignments})

            # Map each student to their class in the current session
            student_class = {}
            for student_id, class_id in ClassEnrollment.objects.filter(
                school_class_id__in=class_ids,
                session__is_current=True,
                is_current=True,
            ).values_list('student_id', 'school_class_id'):
                student_class.setdefault(student_id, class_id)

            term_scores = list(Score.objects.filter(
                subject_id__in=subject_ids, term=current_term,
            ).select_related('subject', 'student'))

            for a in assignments:
                total = ClassEnrollment.objects.filter(
                    school_class=a.school_class, session=a.session, is_current=True,
                ).count()
                complete = 0
                entered = 0
                for sc in term_scores:
                    if sc.subject_id != a.subject_id:
                        continue
                    if student_class.get(sc.student_id) != a.school_class_id:
                        continue
                    entered += 1
                    if sc.is_complete:
                        complete += 1
                assignment_progress.append({
                    'assignment': a,
                    'total': total,
                    'entered': entered,
                    'complete': complete,
                    'pct': round(complete / total * 100) if total else 0,
                    'needs_action': total > 0 and complete < total,
                })
            assignment_progress.sort(key=lambda p: (
                p['needs_action'] is False,
                p['assignment'].school_class.name,
                p['assignment'].subject.name,
            ))

            # "X of Y students fully graded this term": a student counts as
            # fully graded when every score for their class+subject this term
            # is complete.
            students_total = len(set(student_class.keys()))
            all_students_scored = 0
            if students_total:
                complete_per_student = {}
                for sc in term_scores:
                    if not sc.is_complete:
                        continue
                    sid = sc.student_id
                    if sid not in student_class:
                        continue
                    class_id = student_class[sid]
                    # Only count scores for subjects the teacher owns in this class
                    if not any(
                        a.school_class_id == class_id and a.subject_id == sc.subject_id
                        for a in assignments
                    ):
                        continue
                    complete_per_student.setdefault(sid, 0)
                    complete_per_student[sid] += 1
                # Expected score count per student = subjects taught in their class
                subjects_per_class = {}
                for a in assignments:
                    subjects_per_class.setdefault(a.school_class_id, set()).add(a.subject_id)
                for sid, class_id in student_class.items():
                    expected = len(subjects_per_class.get(class_id, set()))
                    if expected and complete_per_student.get(sid, 0) >= expected:
                        all_students_scored += 1
        else:
            students_total = 0
            all_students_scored = 0

        incomplete_assignments = sum(1 for p in assignment_progress if p['needs_action'])
        all_complete = bool(assignments) and incomplete_assignments == 0

        # One-time success toast when everything is fully graded (once per login)
        if all_complete and not request.session.get('_teacher_all_complete_toast'):
            request.session['_teacher_all_complete_toast'] = True
            messages.success(
                request,
                'All assignments fully graded — every student in your classes has '
                'complete marks for the current term.',
            )

        # Most recently entered scores
        recent_scores = []
        for sc in Score.objects.filter(
            entered_by=request.user,
        ).select_related('student', 'student__user', 'subject').order_by('-updated_at')[:5]:
            enrollment = ClassEnrollment.objects.filter(
                student=sc.student, session=sc.term.session, is_current=True,
            ).select_related('school_class').first()
            recent_scores.append({
                'student_name': sc.student.user.get_full_name() or sc.student.user.username,
                'subject': sc.subject.name,
                'class_name': enrollment.school_class.name if enrollment else '',
                'total': sc.total_score if sc.is_complete else None,
                'complete': sc.is_complete,
                'passed': sc.passed,
                'updated_at': sc.updated_at,
            })

        return render(request, 'academics/teacher/assignment_list.html', {
            'assignments': assignments,
            'subject_count': subject_count,
            'class_count': class_count,
            'students_total': students_total,
            'all_students_scored': all_students_scored,
            'current_term': current_term,
            'assignment_progress': assignment_progress,
            'incomplete_assignments': incomplete_assignments,
            'all_complete': all_complete,
            'recent_scores': recent_scores,
        })


class TeacherAssignmentsView(RoleRequiredMixin, View):
    """Focused list of the teacher's assignments (separate from the dashboard)."""

    allowed_roles = [Roles.TEACHER]

    def get(self, request):
        assignments = TeacherAssignment.objects.filter(
            teacher=request.user,
            session__is_current=True,
        ).select_related('subject', 'school_class', 'session').order_by('school_class__name', 'subject__name')
        return render(request, 'academics/teacher/assignments.html', {
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
            'rejected_count': sum(
                1 for s in scores
                if s.moderation_status == Score.MODERATION_REJECTED
            ),
        })


class TeacherScoreUpdateView(RoleRequiredMixin, View):
    """Handles AJAX-style updates to individual score fields."""

    allowed_roles = [Roles.TEACHER]

    def post(self, request, pk, score_pk):
        from core.toasts import attach_toast

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
            resp = HttpResponseForbidden("Not your assignment")
            return attach_toast(resp, "Not your assignment", "error")

        # htmx sends the field name as the POST key (e.g. test_1=8)
        field_name = None
        raw_value = None
        for key in request.POST:
            if key in VALID_SCORE_FIELDS:
                field_name = key
                raw_value = request.POST.get(key, '').strip()
                break

        if field_name is None:
            resp = HttpResponse("Invalid field", status=400)
            return attach_toast(resp, "Invalid field", "error")

        if raw_value == '':
            value = None
        else:
            try:
                value = int(raw_value)
            except (ValueError, TypeError):
                resp = HttpResponse("Value must be a whole number", status=400)
                return attach_toast(resp, "Value must be a whole number", "error")

        max_value = FIELD_MAX_VALUES[field_name]
        if value is not None and (value < 0 or value > max_value):
            msg = f"{field_name.replace('_', ' ').title()} must be between 0 and {max_value}"
            resp = HttpResponse(msg, status=400)
            return attach_toast(resp, msg, "error")

        setattr(score, field_name, value)
        score.entered_by = request.user
        score.save(update_fields=[field_name, 'entered_by', 'updated_at'])

        # Reset moderation if previously approved/rejected
        if score.moderation_status in (Score.MODERATION_APPROVED, Score.MODERATION_REJECTED):
            score.moderation_status = Score.MODERATION_PENDING
            score.moderated_by = None
            score.moderated_at = None
            score.save(update_fields=['moderation_status', 'moderated_by', 'moderated_at'])

        display_value = value if value is not None else ''

        # Build the primary response: return an <input> so the teacher can keep editing
        update_url = reverse('score_update', args=[pk, score.pk])
        input_classes = (
            'w-14 text-center border border-gray-300 rounded px-1 py-1 '
            'tabular-nums text-sm focus:border-[#B8863A] focus:ring-1 '
            'focus:ring-[#B8863A] outline-none'
        )
        primary = (
            f'<input type="number" min="0" max="{max_value}" value="{display_value}"'
            f' hx-post="{update_url}"'
            f' hx-trigger="blur" hx-target="closest td"'
            f' name="{field_name}"'
            f' class="{input_classes}">'
        )

        # Build OOB swap for Total cell
        total = score.total_score
        total_content = f'<span>{total}</span>'

        # Build OOB swap for Status cell (matches score_grid.html badges)
        def _status_badge(color, text):
            dot = f'<span class="w-1.5 h-1.5 rounded-full bg-{color} mr-1.5"></span>'
            return (
                f'<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs '
                f'font-medium bg-{color}-tint text-{color} border border-line">'
                f'{dot}{text}</span>'
            )

        if score.moderation_status == Score.MODERATION_REJECTED:
            status_html = _status_badge('danger', 'Rejected by Admin')
        elif score.moderation_status == Score.MODERATION_APPROVED:
            status_html = _status_badge('success', 'Approved')
        elif score.is_complete:
            status_html = _status_badge('warning', 'Awaiting Review')
        elif score.passed is None:
            status_html = _status_badge('info', 'Pending')
        elif score.passed:
            status_html = _status_badge('success', 'Pass')
        else:
            status_html = _status_badge('danger', 'Fail')

        # Combine: primary response + OOB swaps
        row_class = 'border-t border-gray-100 hover:bg-gray-50/70 transition-colors'
        if score.moderation_status == Score.MODERATION_REJECTED:
            row_class += ' row-rejected'
        response_html = (
            f'{primary}'
            f'<div id="total-{score.pk}" hx-swap-oob="innerHTML">{total_content}</div>'
            f'<div id="status-{score.pk}" hx-swap-oob="innerHTML">{status_html}</div>'
            f'<script id="row-script-{score.pk}" hx-swap-oob="outerHTML">'
            f'var el=document.getElementById("score-row-{score.pk}");'
            f'if(el)el.className="{row_class}";'
            f'</script>'
        )
        response = HttpResponse(response_html)
        return attach_toast(response, 'Score saved.', 'success')
