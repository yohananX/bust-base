"""Academic management views for school admin portal."""
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic.base import View
from django.db.models import Q
from django.contrib import messages
from django.db.models.deletion import ProtectedError

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles, User
from academics.models import ClassSubject, Subject, TeacherAssignment, Score
from students.models import ClassOffering, SchoolClass


class SubjectListView(RoleRequiredMixin, View):
    """List all subjects with search, filter, and inline CRUD actions."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        subjects = Subject.objects.filter(school=school).prefetch_related(
            'class_offerings__school_class',
            'class_offerings__academic_session',
        ).order_by('name')

        q = request.GET.get('q', '')
        offering_id = request.GET.get('offering_id', '')
        if q:
            subjects = subjects.filter(
                Q(name__icontains=q) | Q(code__icontains=q)
            )
        if offering_id:
            subjects = subjects.filter(class_offerings__id=offering_id)

        offerings = ClassOffering.objects.filter(school=school).select_related(
            'school_class', 'academic_session'
        ).order_by('-academic_session__start_date', 'school_class__name')

        context = {
            'subjects': subjects,
            'q': q,
            'offerings': offerings,
            'filter_offering': offering_id,
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
        pass_mark = request.POST.get('pass_mark', '').strip()

        if not name or not code:
            messages.error(request, 'Name and code are required.')
            return redirect('school_admin:subject_create')

        if Subject.objects.filter(school=school, code__iexact=code).exists():
            messages.error(request, f'A subject with code "{code}" already exists.')
            return redirect('school_admin:subject_create')

        try:
            pass_mark = int(pass_mark) if pass_mark else None
        except (ValueError, TypeError):
            messages.error(request, 'Default pass mark must be a whole number.')
            return redirect('school_admin:subject_create')
        if pass_mark is not None and not 0 <= pass_mark <= 32767:
            messages.error(request, 'Default pass mark must be between 0 and 32767.')
            return redirect('school_admin:subject_create')

        Subject.objects.create(
            school=school,
            name=name,
            code=code,
            pass_mark=pass_mark,
        )

        messages.success(
            request,
            f'Subject "{name}" created. Configure it from a specific class offering.',
        )
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
        pass_mark = request.POST.get('pass_mark', '').strip()

        if not name or not code:
            messages.error(request, 'Name and code are required.')
            return redirect('school_admin:subject_edit', pk=pk)

        if Subject.objects.filter(school=school, code__iexact=code).exclude(pk=pk).exists():
            messages.error(request, f'A subject with code "{code}" already exists.')
            return redirect('school_admin:subject_edit', pk=pk)

        try:
            pass_mark = int(pass_mark) if pass_mark else None
        except (ValueError, TypeError):
            messages.error(request, 'Default pass mark must be a whole number.')
            return redirect('school_admin:subject_edit', pk=pk)
        if pass_mark is not None and not 0 <= pass_mark <= 32767:
            messages.error(request, 'Default pass mark must be between 0 and 32767.')
            return redirect('school_admin:subject_edit', pk=pk)

        subject_obj.name = name
        subject_obj.code = code
        subject_obj.pass_mark = pass_mark
        subject_obj.save(update_fields=['name', 'code', 'pass_mark'])

        messages.success(
            request,
            f'Subject "{name}" updated. Existing offering configurations were unchanged.',
        )
        return redirect('school_admin:subject_list')


class SubjectDeleteView(RoleRequiredMixin, View):
    """Delete a subject with warnings if related records exist."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        subject_obj = get_object_or_404(Subject, pk=pk, school=school)

        has_assignments = TeacherAssignment.objects.filter(
            class_subject__subject=subject_obj
        ).exists()
        has_scores = Score.objects.filter(
            class_subject__subject=subject_obj
        ).exists()
        has_configurations = ClassSubject.objects.filter(subject=subject_obj).exists()

        context = {
            'subject': subject_obj,
            'has_assignments': has_assignments,
            'has_scores': has_scores,
            'has_configurations': has_configurations,
        }
        return render(request, 'school_admin/subject_confirm_delete.html', context)

    def post(self, request, pk):
        school = request.school
        subject_obj = get_object_or_404(Subject, pk=pk, school=school)
        name = subject_obj.name

        if ClassSubject.objects.filter(subject=subject_obj).exists():
            messages.error(
                request,
                'This subject has class-offering configurations. Remove only '
                'unused configurations; historical configurations are protected.',
            )
            return redirect('school_admin:subject_list')
        try:
            subject_obj.delete()
        except ProtectedError:
            messages.error(request, 'This subject is protected by academic history.')
        else:
            messages.success(request, f'Subject "{name}" deleted successfully.')
        return redirect('school_admin:subject_list')


class TeacherAssignmentListView(RoleRequiredMixin, View):
    """Two-column teacher assignment management — teacher list + per-teacher assignments."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        teachers = User.objects.filter(
            school=school, role=Roles.TEACHER, is_active=True
        ).order_by('first_name', 'last_name')
        offerings = ClassOffering.objects.filter(school=school).select_related(
            'school_class', 'academic_session'
        ).order_by('-academic_session__start_date', 'school_class__name')

        teacher_id = request.GET.get('teacher_id', '')
        selected_teacher = None
        assignments = []
        if teacher_id:
            selected_teacher = get_object_or_404(
                User, school=school, pk=teacher_id, role=Roles.TEACHER
            )
            assignments = TeacherAssignment.objects.filter(
                school=school, teacher=selected_teacher
            ).select_related(
                'class_subject__subject',
                'class_subject__class_offering__school_class',
                'class_subject__class_offering__academic_session',
            )

        context = {
            'teachers': teachers,
            'selected_teacher': selected_teacher,
            'assignments': assignments,
            'offerings': offerings,
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
        msg = 'Assignment removed.'
        messages.success(request, msg)
        if request.headers.get('HX-Request'):
            from core.toasts import attach_toast
            assignments = TeacherAssignment.objects.filter(
                school=school, teacher_id=teacher_pk
            ).select_related(
                'class_subject__subject',
                'class_subject__class_offering__school_class',
                'class_subject__class_offering__academic_session',
            )
            return attach_toast(
                render(request, 'school_admin/_assignment_rows.html', {'assignments': assignments}),
                msg,
            )
        return redirect('school_admin:assignment_list')


class AssignmentAddView(RoleRequiredMixin, View):
    """Add one or more teacher assignments via HTMX."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request):
        school = request.school
        teacher_id = request.POST.get('teacher_id')
        offering_id = request.POST.get('offering_id')
        class_subject_ids = request.POST.getlist('class_subject_ids')

        if not all([teacher_id, offering_id, class_subject_ids]):
            msg = 'Teacher, class offering, and at least one configured subject are required.'
            messages.error(request, msg)
            if request.headers.get('HX-Request'):
                from core.toasts import attach_toast
                from django.http import HttpResponse
                return attach_toast(HttpResponse(''), msg, 'error')
            return redirect('school_admin:assignment_list')

        teacher = get_object_or_404(User, school=school, pk=teacher_id, role=Roles.TEACHER)
        offering = get_object_or_404(
            ClassOffering, school=school, pk=offering_id
        )

        created_count = 0
        skipped_count = 0
        for class_subject_id in class_subject_ids:
            class_subject = get_object_or_404(
                ClassSubject,
                school=school,
                pk=class_subject_id,
                class_offering=offering,
            )
            _, created = TeacherAssignment.objects.get_or_create(
                school=school,
                teacher=teacher,
                class_subject=class_subject,
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
            from core.toasts import attach_toast
            assignments = TeacherAssignment.objects.filter(
                school=school, teacher=teacher
            ).select_related(
                'class_subject__subject',
                'class_subject__class_offering__school_class',
                'class_subject__class_offering__academic_session',
            )
            return attach_toast(
                render(request, 'school_admin/_assignment_rows.html', {'assignments': assignments}),
                msg,
            )
        return redirect('school_admin:assignment_list')


class AssignmentSubjectsPartialView(RoleRequiredMixin, View):
    """Return configured subject pills for one explicit class offering."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        offering_id = request.GET.get('offering_id', '')
        teacher_id = request.GET.get('teacher_id', '')

        class_subjects = ClassSubject.objects.none()
        if offering_id:
            class_subjects = ClassSubject.objects.filter(
                school=school,
                class_offering_id=offering_id,
                class_offering__school=school,
            ).select_related('subject').order_by('subject__name')

        assigned_class_subject_ids = set()
        if teacher_id and offering_id:
            assigned_class_subject_ids = set(
                TeacherAssignment.objects.filter(
                    school=school,
                    teacher_id=teacher_id,
                    class_subject__class_offering_id=offering_id,
                ).values_list('class_subject_id', flat=True)
            )

        context = {
            'class_subjects': class_subjects,
            'assigned_class_subject_ids': assigned_class_subject_ids,
        }
        return render(request, 'school_admin/_subject_pills.html', context)


class ScoreAdminView(RoleRequiredMixin, View):
    """Read-only grid of scores per class/subject/term."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        from core.models import Term

        # Filters
        term_id = request.GET.get('term_id', '')
        class_id = request.GET.get('class_id', '')
        subject_id = request.GET.get('subject_id', '')

        scores = Score.objects.filter(school=school)

        if term_id:
            scores = scores.filter(term_id=term_id)
        if class_id and term_id:
            scores = scores.filter(class_subject__class_offering__school_class_id=class_id)
        elif class_id:
            # A stable class alone spans sessions; require the term to select
            # the exact offering rather than guessing a current session.
            scores = scores.none()
        if subject_id:
            scores = scores.filter(class_subject__subject_id=subject_id)

        scores = scores.select_related(
            'student', 'student__user', 'class_subject__subject',
            'class_subject__class_offering', 'term'
        ).order_by('student__admission_number')

        terms = Term.objects.filter(school=school).select_related(
            'session'
        ).order_by('-session__start_date', 'start_date')
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



