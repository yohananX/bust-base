"""Academic management views for school admin portal."""
from django.shortcuts import render
from django.views.generic.base import View
from django.db.models import Q

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from academics.models import Subject, TeacherAssignment, Score
from students.models import SchoolClass


class SubjectListView(RoleRequiredMixin, View):
    """List all subjects with CRUD (read-only list for now)."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        subjects = Subject.objects.filter(school=school).order_by('name')

        q = request.GET.get('q', '')
        if q:
            subjects = subjects.filter(
                Q(name__icontains=q) | Q(code__icontains=q)
            )

        context = {
            'subjects': subjects,
            'q': q,
        }
        return render(request, 'school_admin/subject_list.html', context)


class TeacherAssignmentListView(RoleRequiredMixin, View):
    """List teacher assignments with filters."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        assignments = TeacherAssignment.objects.filter(
            school=school
        ).select_related('teacher', 'subject', 'school_class', 'session')

        # Filters
        teacher_id = request.GET.get('teacher_id', '')
        if teacher_id:
            assignments = assignments.filter(teacher_id=teacher_id)

        class_id = request.GET.get('class_id', '')
        if class_id:
            assignments = assignments.filter(school_class_id=class_id)

        session_id = request.GET.get('session_id', '')
        if session_id:
            assignments = assignments.filter(session_id=session_id)

        from core.models import AcademicSession
        from accounts.models import User

        teachers = User.objects.filter(school=school, role=Roles.TEACHER, is_active=True)
        classes = SchoolClass.objects.filter(school=school, is_active=True)
        sessions = AcademicSession.objects.filter(school=school)

        context = {
            'assignments': assignments,
            'teachers': teachers,
            'classes': classes,
            'sessions': sessions,
            'filter_teacher': teacher_id,
            'filter_class': class_id,
            'filter_session': session_id,
        }
        return render(request, 'school_admin/assignment_list.html', context)


class ScoreAdminView(RoleRequiredMixin, View):
    """Read-only grid of scores per class/subject/term."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        from core.models import Term, AcademicSession

        # Filters
        term_id = request.GET.get('term_id', '')
        class_id = request.GET.get('class_id', '')
        subject_id = request.GET.get('subject_id', '')

        scores = Score.objects.filter(school=school)

        if term_id:
            scores = scores.filter(term_id=term_id)
        if class_id:
            scores = scores.filter(
                student__enrollments__school_class_id=class_id,
                student__enrollments__is_current=True,
            )
        if subject_id:
            scores = scores.filter(subject_id=subject_id)

        scores = scores.select_related(
            'student', 'student__user', 'subject', 'term'
        ).order_by('student__admission_number')

        terms = Term.objects.filter(school=school).order_by('-start_date')
        classes = SchoolClass.objects.filter(school=school, is_active=True)
        subjects = Subject.objects.filter(school=school).order_by('name')

        context = {
            'scores': scores,
            'terms': terms,
            'classes': classes,
            'subjects': subjects,
            'filter_term': term_id,
            'filter_class': class_id,
            'filter_subject': subject_id,
        }
        return render(request, 'school_admin/score_list.html', context)
