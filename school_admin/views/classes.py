"""Class management views for school admin portal."""
from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic.base import View
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.http import JsonResponse
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from academics.models import Subject, ClassSubject
from academics.services import copy_subject_configurations
from students.models import (
    AcademicStage, ClassOffering, SchoolClass, ClassEnrollment,
)
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

    A non-empty value must reference a stage in the current school; an
    already-assigned inactive stage may be kept on edit. Whether an empty
    value is allowed is decided by the caller, using
    ``_school_has_active_stages`` (the academic stage is the single
    classification field for classes).
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


def _school_has_active_stages(school):
    """True when the school has any active academic stage configured."""
    return AcademicStage.objects.filter(school=school, is_active=True).exists()


def _class_form_context(school, class_obj=None):
    return {
        'class_obj': class_obj,
        'is_edit': class_obj is not None,
        'stages': _stage_options(
            school,
            class_obj.academic_stage_id if class_obj else None,
        ),
    }


def _class_detail_url(class_obj, offering=None):
    url = reverse('school_admin:class_detail', args=[class_obj.pk])
    if offering is not None:
        return f'{url}?offering_id={offering.pk}'
    return url


def _get_posted_offering(request, class_obj):
    """Resolve the explicit offering submitted by a configuration action."""
    offering_id = (request.POST.get('offering_id') or '').strip()
    if not offering_id:
        return None
    return ClassOffering.objects.filter(
        pk=offering_id,
        school=request.school,
        school_class=class_obj,
    ).select_related('school_class', 'academic_session').first()


def _parse_pass_mark(raw):
    raw = (raw or '').strip()
    if not raw:
        return None, None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, 'Pass mark must be a whole number.'
    if value < 0 or value > 32767:
        return None, 'Pass mark must be between 0 and 32767.'
    return value, None


class ClassListView(RoleRequiredMixin, View):
    """List all classes with search, status filter, and student count."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        classes = SchoolClass.objects.filter(school=school).select_related('academic_stage')

        # Search by name or stage
        q = request.GET.get('q', '').strip()
        if q:
            classes = classes.filter(
                Q(name__icontains=q)
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
        ).order_by('academic_stage__display_order', 'name')

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
        is_active = request.POST.get('is_active') == 'on'

        if not name:
            messages.error(request, 'Class name is required.')
            return redirect('school_admin:class_create')

        stage, stage_error = _resolve_academic_stage(request, school)
        if stage_error:
            messages.error(request, stage_error)
            return redirect('school_admin:class_create')

        # The academic stage is the single classification field for classes.
        # It is only optional while the school has no stages configured yet;
        # administrators create stages in Django admin.
        if stage is None and _school_has_active_stages(school):
            messages.error(request, 'Select an academic stage for this class.')
            return redirect('school_admin:class_create')

        if SchoolClass.objects.filter(school=school, name=name).exists():
            messages.error(
                request,
                f'A class named "{name}" already exists in this school.',
            )
            return redirect('school_admin:class_create')

        try:
            with transaction.atomic():
                new_class = SchoolClass(
                    school=school,
                    name=name,
                    academic_stage=stage,
                    is_active=is_active,
                )
                new_class.save()
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
        is_active = request.POST.get('is_active') == 'on'

        if not name:
            messages.error(request, 'Class name is required.')
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

        # The academic stage is the single classification field for classes.
        # Clearing it is only allowed while no active stages are configured.
        if stage is None and _school_has_active_stages(school):
            messages.error(request, 'Select an academic stage for this class.')
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
                class_obj.is_active = is_active
                class_obj.academic_stage = stage
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
    """Class detail with explicit offering-scoped subject management."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        class_obj = get_object_or_404(SchoolClass, school=school, pk=pk)
        offerings = list(
            ClassOffering.objects.filter(
                school=school, school_class=class_obj,
            ).select_related('academic_session').order_by(
                '-academic_session__start_date'
            )
        )

        selected_offering = None
        offering_id = (request.GET.get('offering_id') or '').strip()
        if offering_id:
            selected_offering = next(
                (offering for offering in offerings if str(offering.pk) == offering_id),
                None,
            )
            if selected_offering is None:
                messages.error(request, 'Select a valid class offering for this school.')
        elif len(offerings) == 1:
            # A single offering is unambiguous; multiple offerings always
            # require the administrator to choose a session explicitly.
            selected_offering = offerings[0]

        class_subjects = ClassSubject.objects.none()
        available_subjects = Subject.objects.none()
        previous_offerings = []
        if selected_offering:
            class_subjects = ClassSubject.objects.filter(
                school=school, class_offering=selected_offering,
            ).select_related('subject').order_by('subject__name')
            linked_subject_ids = class_subjects.values_list('subject_id', flat=True)
            available_subjects = Subject.objects.filter(
                school=school,
            ).exclude(pk__in=linked_subject_ids).order_by('name')
            previous_offerings = [
                offering for offering in offerings
                if offering.academic_session.start_date
                < selected_offering.academic_session.start_date
            ]

        context = {
            'class_obj': class_obj,
            'offerings': offerings,
            'selected_offering': selected_offering,
            'previous_offerings': previous_offerings,
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
        offering = _get_posted_offering(request, class_obj)
        if offering is None:
            messages.error(request, 'Select a valid class offering before adding subjects.')
            return redirect(_class_detail_url(class_obj))
        subject_ids = request.POST.getlist('subject_ids')
        pass_mark_val, pass_mark_error = _parse_pass_mark(
            request.POST.get('pass_mark')
        )

        if not subject_ids:
            messages.error(request, 'Please select at least one subject.')
            return redirect(_class_detail_url(class_obj, offering))
        if pass_mark_error:
            messages.error(request, pass_mark_error)
            return redirect(_class_detail_url(class_obj, offering))

        added = []
        skipped = []
        for subject_id in subject_ids:
            subject = get_object_or_404(Subject, pk=subject_id, school=school)
            link, created = ClassSubject.objects.get_or_create(
                school=school,
                subject=subject,
                class_offering=offering,
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
        return redirect(_class_detail_url(class_obj, offering))


class ClassSubjectCreateView(RoleRequiredMixin, View):
    """Create a new subject and add it to the class."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        class_obj = get_object_or_404(SchoolClass, school=school, pk=pk)
        offering = _get_posted_offering(request, class_obj)
        if offering is None:
            messages.error(request, 'Select a valid class offering before adding subjects.')
            return redirect(_class_detail_url(class_obj))
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip()
        pass_mark_val, pass_mark_error = _parse_pass_mark(
            request.POST.get('pass_mark')
        )

        if not name or not code:
            messages.error(request, 'Subject name and code are required.')
            return redirect(_class_detail_url(class_obj, offering))

        if Subject.objects.filter(school=school, code__iexact=code).exists():
            messages.error(request, f'A subject with code "{code}" already exists.')
            return redirect(_class_detail_url(class_obj, offering))
        if pass_mark_error:
            messages.error(request, pass_mark_error)
            return redirect(_class_detail_url(class_obj, offering))

        with transaction.atomic():
            subject = Subject.objects.create(
                school=school,
                name=name,
                code=code,
            )
            ClassSubject.objects.create(
                school=school,
                subject=subject,
                class_offering=offering,
                pass_mark=pass_mark_val,
            )

        messages.success(request, f'Subject "{name}" created and added to {class_obj.name}.')
        return redirect(_class_detail_url(class_obj, offering))


class ClassSubjectRemoveView(RoleRequiredMixin, View):
    """Remove one configuration when no historical records protect it."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk, class_subject_id):
        school = request.school
        class_obj = get_object_or_404(SchoolClass, school=school, pk=pk)
        link = get_object_or_404(
            ClassSubject.objects.select_related(
                'subject', 'class_offering__academic_session'
            ),
            pk=class_subject_id,
            school=school,
            class_offering__school_class=class_obj,
        )
        try:
            link.delete()
        except ProtectedError:
            messages.error(
                request,
                'This configuration has scores or teacher assignments and is '
                'protected as academic history.',
            )
        else:
            messages.success(
                request,
                f'Removed "{link.subject.name}" from {link.class_offering}.',
            )

        return redirect(_class_detail_url(class_obj, link.class_offering))


class ClassSubjectUpdateView(RoleRequiredMixin, View):
    """Update the pass mark for one explicit offering configuration."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk, class_subject_id):
        school = request.school
        class_obj = get_object_or_404(SchoolClass, school=school, pk=pk)
        config = get_object_or_404(
            ClassSubject.objects.select_related('class_offering'),
            pk=class_subject_id,
            school=school,
            class_offering__school_class=class_obj,
        )
        pass_mark, error = _parse_pass_mark(request.POST.get('pass_mark'))
        if error:
            messages.error(request, error)
        else:
            config.pass_mark = pass_mark
            config.save(update_fields=['pass_mark'])
            messages.success(request, 'Pass mark updated for this class offering.')
        return redirect(_class_detail_url(class_obj, config.class_offering))


class ClassSubjectCopyView(RoleRequiredMixin, View):
    """Explicitly copy configurations from an earlier class offering."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        class_obj = get_object_or_404(SchoolClass, school=school, pk=pk)
        target = _get_posted_offering(request, class_obj)
        source = ClassOffering.objects.filter(
            pk=request.POST.get('source_offering_id'),
            school=school,
            school_class=class_obj,
        ).select_related('academic_session').first()
        if target is None or source is None:
            messages.error(request, 'Select valid source and target class offerings.')
            return redirect(_class_detail_url(class_obj, target))
        try:
            created, skipped = copy_subject_configurations(source, target)
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
        else:
            msg = f'Copied {created} subject configuration(s).'
            if skipped:
                msg += f' {skipped} already existed and were left unchanged.'
            messages.success(request, msg)
        return redirect(_class_detail_url(class_obj, target))


class ClassSubjectBulkAddView(RoleRequiredMixin, View):
    """Bulk add multiple subjects to a class."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        class_obj = get_object_or_404(SchoolClass, school=school, pk=pk)
        offering = _get_posted_offering(request, class_obj)
        if offering is None:
            messages.error(request, 'Select a valid class offering before adding subjects.')
            return redirect(_class_detail_url(class_obj))
        subject_ids = request.POST.getlist('subject_ids')
        pass_mark_val, pass_mark_error = _parse_pass_mark(
            request.POST.get('pass_mark')
        )

        if not subject_ids:
            messages.error(request, 'Please select at least one subject.')
            return redirect(_class_detail_url(class_obj, offering))
        if pass_mark_error:
            messages.error(request, pass_mark_error)
            return redirect(_class_detail_url(class_obj, offering))

        added = 0
        skipped = 0
        for subject_id in subject_ids:
            subject = get_object_or_404(Subject, pk=subject_id, school=school)
            _, created = ClassSubject.objects.get_or_create(
                school=school,
                subject=subject,
                class_offering=offering,
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
        return redirect(_class_detail_url(class_obj, offering))
