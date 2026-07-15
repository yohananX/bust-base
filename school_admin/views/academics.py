"""Academic management views for school admin portal."""
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic.base import View
from django.db.models import Q
from django.contrib import messages
from django.db import transaction

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles, User
from academics.models import Subject, TeacherAssignment, Score
from students.models import SchoolClass
from core.models import AcademicSession


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


class SubjectCreateView(RoleRequiredMixin, View):
    """Create a new subject."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        context = {'is_edit': False}
        return render(request, 'school_admin/subject_form.html', context)

    def post(self, request):
        school = request.school
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip()
        pass_mark = request.POST.get('pass_mark', 40)

        if not name or not code:
            messages.error(request, 'Name and code are required.')
            return redirect('school_admin:subject_create')

        # Validate unique code per school
        if Subject.objects.filter(school=school, code__iexact=code).exists():
            messages.error(request, f'A subject with code "{code}" already exists.')
            return redirect('school_admin:subject_create')

        try:
            pass_mark = int(pass_mark)
        except (ValueError, TypeError):
            pass_mark = 40

        with transaction.atomic():
            Subject.objects.create(
                school=school,
                name=name,
                code=code,
                pass_mark=pass_mark,
            )

        messages.success(request, f'Subject "{name}" created successfully.')
        return redirect('school_admin:subject_list')


class SubjectEditView(RoleRequiredMixin, View):
    """Edit an existing subject."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        subject_obj = get_object_or_404(Subject, pk=pk, school=school)

        context = {
            'is_edit': True,
            'subject': subject_obj,
        }
        return render(request, 'school_admin/subject_form.html', context)

    def post(self, request, pk):
        school = request.school
        subject_obj = get_object_or_404(Subject, pk=pk, school=school)

        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip()
        pass_mark = request.POST.get('pass_mark', 40)

        if not name or not code:
            messages.error(request, 'Name and code are required.')
            return redirect('school_admin:subject_edit', pk=pk)

        # Validate unique code per school (exclude current subject)
        if Subject.objects.filter(school=school, code__iexact=code).exclude(pk=pk).exists():
            messages.error(request, f'A subject with code "{code}" already exists.')
            return redirect('school_admin:subject_edit', pk=pk)

        try:
            pass_mark = int(pass_mark)
        except (ValueError, TypeError):
            pass_mark = 40

        with transaction.atomic():
            subject_obj.name = name
            subject_obj.code = code
            subject_obj.pass_mark = pass_mark
            subject_obj.save()

        messages.success(request, f'Subject "{name}" updated successfully.')
        return redirect('school_admin:subject_list')


class SubjectDeleteView(RoleRequiredMixin, View):
    """Delete a subject with warnings if related records exist."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        subject_obj = get_object_or_404(Subject, pk=pk, school=school)

        has_assignments = TeacherAssignment.objects.filter(subject=subject_obj).exists()
        has_scores = Score.objects.filter(subject=subject_obj).exists()

        context = {
            'subject': subject_obj,
            'has_assignments': has_assignments,
            'has_scores': has_scores,
        }
        return render(request, 'school_admin/subject_confirm_delete.html', context)

    def post(self, request, pk):
        school = request.school
        subject_obj = get_object_or_404(Subject, pk=pk, school=school)
        name = subject_obj.name

        # Related records are cascaded; warn but proceed
        assignment_count = TeacherAssignment.objects.filter(subject=subject_obj).count()
        score_count = Score.objects.filter(subject=subject_obj).count()

        with transaction.atomic():
            subject_obj.delete()

        msg = f'Subject "{name}" deleted successfully.'
        if assignment_count or score_count:
            parts = []
            if assignment_count:
                parts.append(f'{assignment_count} assignment(s)')
            if score_count:
                parts.append(f'{score_count} score record(s)')
            msg += f' Also removed {", ".join(parts)}.'
        messages.success(request, msg)
        return redirect('school_admin:subject_list')


class TeacherAssignmentListView(RoleRequiredMixin, View):
    """Two-column teacher assignment management — teacher list + per-teacher assignments."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        teachers = User.objects.filter(
            school=school, role=Roles.TEACHER, is_active=True
        ).order_by('first_name', 'last_name')
        classes = SchoolClass.objects.filter(school=school, is_active=True).order_by('name')
        subjects = Subject.objects.filter(school=school).order_by('name')
        sessions = AcademicSession.objects.filter(school=school).order_by('-start_date')

        teacher_id = request.GET.get('teacher_id', '')
        selected_teacher = None
        assignments = []
        if teacher_id:
            selected_teacher = get_object_or_404(
                User, school=school, pk=teacher_id, role=Roles.TEACHER
            )
            assignments = TeacherAssignment.objects.filter(
                school=school, teacher=selected_teacher
            ).select_related('subject', 'school_class', 'session')

        context = {
            'teachers': teachers,
            'selected_teacher': selected_teacher,
            'assignments': assignments,
            'classes': classes,
            'subjects': subjects,
            'sessions': sessions,
        }
        return render(request, 'school_admin/assignment_list.html', context)


class AssignmentDeleteView(RoleRequiredMixin, View):
    """Delete a teacher assignment via HTMX."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        assignment = get_object_or_404(TeacherAssignment, school=school, pk=pk)
        teacher_pk = assignment.teacher_id
        assignment.delete()
        messages.success(request, 'Assignment removed.')
        if request.headers.get('HX-Request'):
            assignments = TeacherAssignment.objects.filter(
                school=school, teacher_id=teacher_pk
            ).select_related('subject', 'school_class', 'session')
            return render(request, 'school_admin/_assignment_rows.html', {'assignments': assignments})
        return redirect('school_admin:assignment_list')


class AssignmentAddView(RoleRequiredMixin, View):
    """Add one or more teacher assignments via HTMX."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request):
        school = request.school
        teacher_id = request.POST.get('teacher_id')
        class_id = request.POST.get('class_id')
        session_id = request.POST.get('session_id')
        subject_ids = request.POST.getlist('subject_ids')

        if not all([teacher_id, class_id, session_id, subject_ids]):
            messages.error(request, 'Teacher, class, session, and at least one subject are required.')
            if request.headers.get('HX-Request'):
                from django.http import HttpResponse
                return HttpResponse('')
            return redirect('school_admin:assignment_list')

        teacher = get_object_or_404(User, school=school, pk=teacher_id, role=Roles.TEACHER)
        school_class = get_object_or_404(SchoolClass, school=school, pk=class_id)
        session = get_object_or_404(AcademicSession, school=school, pk=session_id)

        created_count = 0
        skipped_count = 0
        for subject_id in subject_ids:
            subject = get_object_or_404(Subject, school=school, pk=subject_id)
            _, created = TeacherAssignment.objects.get_or_create(
                school=school,
                teacher=teacher,
                subject=subject,
                school_class=school_class,
                session=session,
            )
            if created:
                created_count += 1
            else:
                skipped_count += 1

        msg = f'{created_count} assignment(s) created.'
        if skipped_count:
            msg += f' {skipped_count} already existed (skipped).'
        messages.success(request, msg)

        if request.headers.get('HX-Request'):
            assignments = TeacherAssignment.objects.filter(
                school=school, teacher=teacher
            ).select_related('subject', 'school_class', 'session')
            return render(request, 'school_admin/_assignment_rows.html', {'assignments': assignments})
        return redirect('school_admin:assignment_list')


class AssignmentSubjectsPartialView(RoleRequiredMixin, View):
    """Return subject pills for a given class (HTMX partial)."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        class_id = request.GET.get('class_id', '')
        teacher_id = request.GET.get('teacher_id', '')

        subjects = Subject.objects.filter(school=school).order_by('name')

        assigned_subject_ids = set()
        if teacher_id and class_id:
            assigned_subject_ids = set(
                TeacherAssignment.objects.filter(
                    school=school, teacher_id=teacher_id, school_class_id=class_id
                ).values_list('subject_id', flat=True)
            )

        context = {
            'subjects': subjects,
            'assigned_subject_ids': assigned_subject_ids,
        }
        return render(request, 'school_admin/_subject_pills.html', context)


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



