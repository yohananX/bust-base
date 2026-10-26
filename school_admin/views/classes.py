"""Class management views for school admin portal."""
from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic.base import View
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.http import JsonResponse

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from academics.models import Subject, ClassSubject
from students.models import AcademicStage, SchoolClass, ClassEnrollment
from django.db.models import Q, Count


def _stage_options(school, current_stage_id=None):
    """Active stages for a school, plus the current stage if it is inactive.

    Keeping the currently assigned stage in the queryset means editing a class
    never silently drops an archived stage assignment.
    """
    stages = AcademicStage.objects.filter(school=school)
    if current_stage_id:
        stages = stages.filter(Q(is_active=True) | Q(pk=current_stage_id))
    else:
        stages = stages.filter(is_active=True)
    return stages.order_by('display_order', 'name')


def _resolve_academic_stage(request, school, current_stage_id=None):
    """Return ``(stage, error)`` for the submitted stage.

    An empty value means "unclassified" and returns ``(None, None)``.
    A non-empty value must reference an active stage in the current school;
    an already-assigned inactive stage may be kept on edit.
    """
    raw = (request.POST.get('academic_stage') or '').strip()
    if not raw:
        return None, None
    try:
        stage_id = int(raw)
    except (TypeError, ValueError):
        return None, 'Select a valid academic stage.'
    stage = AcademicStage.objects.filter(school=school, pk=stage_id).first()
    if stage is None:
        return None, 'Select an academic stage that belongs to this school.'
    if not stage.is_active and stage.pk != current_stage_id:
        return None, 'Select an active academic stage.'
    return stage, None


def _class_form_context(school, class_obj=None):
    return {
        'class_obj': class_obj,
        'is_edit': class_obj is not None,
        'stages': _stage_options(
            school,
            class_obj.academic_stage_id if class_obj else None,
        ),
    }


class ClassListView(RoleRequiredMixin, View):
    """List all classes with search, status filter, and student count."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        classes = SchoolClass.objects.filter(school=school).select_related('academic_stage')

        # Search by name, level, or stage
        q = request.GET.get('q', '').strip()
        if q:
            classes = classes.filter(
                Q(name__icontains=q)
                | Q(level__icontains=q)
                | Q(academic_stage__name__icontains=q)
            )

        # Filter by active status (active / inactive / all)
        status = request.GET.get('status', '')
        if status == 'active':
            classes = classes.filter(is_active=True)
        elif status == 'inactive':
            classes = classes.filter(is_active=False)

        # Annotate with count of currently enrolled students
        classes = classes.annotate(
            student_count=Count(
                'enrollments',
                filter=Q(enrollments__is_current=True),
            ),
        ).order_by('level', 'name')

        context = {
            'classes': classes,
            'q': q,
            'filter_status': status,
        }
        return render(request, 'school_admin/class_list.html', context)


class ClassCreateView(RoleRequiredMixin, View):
    """Create a new class."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        return render(
            request,
            'school_admin/class_form.html',
            _class_form_context(school),
        )

    def post(self, request):
        school = request.school
        name = request.POST.get('name', '').strip()
        level = request.POST.get('level', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        if not name or not level:
            messages.error(request, 'Both name and level are required.')
            return redirect('school_admin:class_create')

        stage, stage_error = _resolve_academic_stage(request, school)
        if stage_error:
            messages.error(request, stage_error)
            return redirect('school_admin:class_create')

        if SchoolClass.objects.filter(school=school, name=name).exists():
            messages.error(
                request,
                f'A class named "{name}" already exists in this school.',
            )
            return redirect('school_admin:class_create')

        try:
            with transaction.atomic():
                SchoolClass.objects.create(
                    school=school,
                    name=name,
                    level=level,
                    academic_stage=stage,
                    is_active=is_active,
                )
            messages.success(request, f'Class "{name}" created successfully.')
            return redirect('school_admin:class_list')
        except IntegrityError:
            messages.error(
                request,
                f'A class named "{name}" already exists in this school.',
            )
            return redirect('school_admin:class_create')


class ClassEditView(RoleRequiredMixin, View):
    """Edit an existing class."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        class_obj = get_object_or_404(SchoolClass, school=school, pk=pk)
        return render(
            request,
            'school_admin/class_form.html',
            _class_form_context(school, class_obj),
        )

    def post(self, request, pk):
        school = request.school
        class_obj = get_object_or_404(SchoolClass, school=school, pk=pk)

        name = request.POST.get('name', '').strip()
        level = request.POST.get('level', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        if not name or not level:
            messages.error(request, 'Both name and level are required.')
            return render(
                request,
                'school_admin/class_form.html',
                _class_form_context(school, class_obj),
            )

        stage, stage_error = _resolve_academic_stage(
            request, school, class_obj.academic_stage_id,
        )
        if stage_error:
            messages.error(request, stage_error)
            return render(
                request,
                'school_admin/class_form.html',
                _class_form_context(school, class_obj),
            )

        # If the name changed, check uniqueness against other classes
        if name != class_obj.name:
            if SchoolClass.objects.filter(school=school, name=name).exists():
                messages.error(
                    request,
                    f'A class named "{name}" already exists in this school.',
                )
                return render(
                    request,
                    'school_admin/class_form.html',
                    _class_form_context(school, class_obj),
                )

        try:
            with transaction.atomic():
                class_obj.name = name
                class_obj.level = level
                class_obj.academic_stage = stage
                class_obj.is_active = is_active
                class_obj.save()
            messages.success(
                request,
                f'Class "{name}" updated successfully.',
            )
            return redirect('school_admin:class_list')
        except IntegrityError:
            messages.error(
                request,
                f'A class named "{name}" already exists in this school.',
            )
            return render(
                request,
                'school_admin/class_form.html',
                _class_form_context(school, class_obj),
            )


class ClassDeleteView(RoleRequiredMixin, View):
    """Delete a class with confirmation."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        class_obj = get_object_or_404(SchoolClass, school=school, pk=pk)
        student_count = ClassEnrollment.objects.filter(
            school_class=class_obj, is_current=True,
        ).count()

        context = {
            'class_obj': class_obj,
            'student_count': student_count,
        }
        return render(request, 'school_admin/class_confirm_delete.html', context)

    def post(self, request, pk):
        school = request.school
        class_obj = get_object_or_404(SchoolClass, school=school, pk=pk)
        class_name = str(class_obj)

        student_count = ClassEnrollment.objects.filter(
            school_class=class_obj,
        ).count()

        if student_count > 0:
            messages.warning(
                request,
                f'Class "{class_name}" had {student_count} enrolled student(s) '
                f'who will no longer be assigned to this class.',
            )

        class_obj.delete()
        messages.success(
            request,
            f'Class "{class_name}" deleted successfully.',
        )
        return redirect('school_admin:class_list')


class ClassDetailView(RoleRequiredMixin, View):
    """Class detail with embedded subject management."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        class_obj = get_object_or_404(SchoolClass, school=school, pk=pk)
        linked_subject_ids = list(
            ClassSubject.objects.filter(
                school=school, school_class=class_obj
            ).values_list('subject_id', flat=True)
        )
        available_subjects = Subject.objects.filter(
            school=school
        ).exclude(id__in=linked_subject_ids).order_by('name')
        class_subjects = ClassSubject.objects.filter(
            school=school, school_class=class_obj
        ).select_related('subject').order_by('subject__name')

        context = {
            'class_obj': class_obj,
            'available_subjects': available_subjects,
            'class_subjects': class_subjects,
        }
        return render(request, 'school_admin/class_detail.html', context)


class ClassSubjectAddView(RoleRequiredMixin, View):
    """Add existing subjects to a class (single or bulk)."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        class_obj = get_object_or_404(SchoolClass, school=school, pk=pk)
        subject_ids = request.POST.getlist('subject_ids')
        pass_mark = request.POST.get('pass_mark', '').strip()

        if not subject_ids:
            messages.error(request, 'Please select at least one subject.')
            return redirect('school_admin:class_detail', pk=pk)

        try:
            pass_mark_val = int(pass_mark) if pass_mark else None
        except (ValueError, TypeError):
            pass_mark_val = None

        if pass_mark_val is not None and (pass_mark_val < 0 or pass_mark_val > 100):
            messages.error(request, 'Pass mark must be between 0 and 100.')
            return redirect('school_admin:class_detail', pk=pk)

        added = []
        skipped = []
        for subject_id in subject_ids:
            subject = get_object_or_404(Subject, pk=subject_id, school=school)
            link, created = ClassSubject.objects.get_or_create(
                school=school,
                subject=subject,
                school_class=class_obj,
                defaults={'pass_mark': pass_mark_val},
            )
            if created:
                added.append(subject.name)
            else:
                skipped.append(subject.name)

        msg = f'Added {len(added)} subject(s) to {class_obj.name}.'
        if skipped:
            msg += f' {len(skipped)} already existed (skipped).'
        messages.success(request, msg)
        return redirect('school_admin:class_detail', pk=pk)


class ClassSubjectCreateView(RoleRequiredMixin, View):
    """Create a new subject and add it to the class."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        class_obj = get_object_or_404(SchoolClass, school=school, pk=pk)
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip()
        pass_mark = request.POST.get('pass_mark', '').strip()

        if not name or not code:
            messages.error(request, 'Subject name and code are required.')
            return redirect('school_admin:class_detail', pk=pk)

        if Subject.objects.filter(school=school, code__iexact=code).exists():
            messages.error(request, f'A subject with code "{code}" already exists.')
            return redirect('school_admin:class_detail', pk=pk)

        try:
            pass_mark_val = int(pass_mark) if pass_mark else None
        except (ValueError, TypeError):
            pass_mark_val = None

        if pass_mark_val is not None and (pass_mark_val < 0 or pass_mark_val > 100):
            messages.error(request, 'Pass mark must be between 0 and 100.')
            return redirect('school_admin:class_detail', pk=pk)

        with transaction.atomic():
            subject = Subject.objects.create(
                school=school,
                name=name,
                code=code,
            )
            ClassSubject.objects.create(
                school=school,
                subject=subject,
                school_class=class_obj,
                pass_mark=pass_mark_val,
            )

        messages.success(request, f'Subject "{name}" created and added to {class_obj.name}.')
        return redirect('school_admin:class_detail', pk=pk)


class ClassSubjectRemoveView(RoleRequiredMixin, View):
    """Remove a subject from a class."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk, subject_id):
        school = request.school
        class_obj = get_object_or_404(SchoolClass, school=school, pk=pk)
        subject = get_object_or_404(Subject, pk=subject_id, school=school)

        link = ClassSubject.objects.filter(
            school=school, subject=subject, school_class=class_obj
        ).first()
        if link:
            link.delete()
            messages.success(request, f'Removed "{subject.name}" from {class_obj.name}.')
        else:
            messages.error(request, 'Subject is not assigned to this class.')

        return redirect('school_admin:class_detail', pk=pk)


class ClassSubjectBulkAddView(RoleRequiredMixin, View):
    """Bulk add multiple subjects to a class."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        class_obj = get_object_or_404(SchoolClass, school=school, pk=pk)
        subject_ids = request.POST.getlist('subject_ids')
        pass_mark = request.POST.get('pass_mark', '').strip()

        if not subject_ids:
            messages.error(request, 'Please select at least one subject.')
            return redirect('school_admin:class_detail', pk=pk)

        try:
            pass_mark_val = int(pass_mark) if pass_mark else None
        except (ValueError, TypeError):
            pass_mark_val = None

        if pass_mark_val is not None and (pass_mark_val < 0 or pass_mark_val > 100):
            messages.error(request, 'Pass mark must be between 0 and 100.')
            return redirect('school_admin:class_detail', pk=pk)

        added = 0
        skipped = 0
        for subject_id in subject_ids:
            subject = get_object_or_404(Subject, pk=subject_id, school=school)
            _, created = ClassSubject.objects.get_or_create(
                school=school,
                subject=subject,
                school_class=class_obj,
                defaults={'pass_mark': pass_mark_val},
            )
            if created:
                added += 1
            else:
                skipped += 1

        msg = f'Added {added} subject(s) to {class_obj.name}.'
        if skipped:
            msg += f' {skipped} already existed (skipped).'
        messages.success(request, msg)
        return redirect('school_admin:class_detail', pk=pk)
