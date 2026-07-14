"""Class management views for school admin portal."""
from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic.base import View
from django.contrib import messages
from django.db import transaction, IntegrityError

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from students.models import SchoolClass, ClassEnrollment
from django.db.models import Q, Count


class ClassListView(RoleRequiredMixin, View):
    """List all classes with search, status filter, and student count."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        classes = SchoolClass.objects.filter(school=school)

        # Search by name or level
        q = request.GET.get('q', '').strip()
        if q:
            classes = classes.filter(
                Q(name__icontains=q) | Q(level__icontains=q)
            )

        # Filter by active status (yes / no / all)
        status = request.GET.get('status', '')
        if status == 'yes':
            classes = classes.filter(is_active=True)
        elif status == 'no':
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
        context = {
            'is_edit': False,
        }
        return render(request, 'school_admin/class_form.html', context)

    def post(self, request):
        school = request.school
        name = request.POST.get('name', '').strip()
        level = request.POST.get('level', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        if not name or not level:
            messages.error(request, 'Both name and level are required.')
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
        context = {
            'class_obj': class_obj,
            'is_edit': True,
        }
        return render(request, 'school_admin/class_form.html', context)

    def post(self, request, pk):
        school = request.school
        class_obj = get_object_or_404(SchoolClass, school=school, pk=pk)

        name = request.POST.get('name', '').strip()
        level = request.POST.get('level', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        if not name or not level:
            messages.error(request, 'Both name and level are required.')
            return render(request, 'school_admin/class_form.html', {
                'class_obj': class_obj,
                'is_edit': True,
            })

        # If the name changed, check uniqueness against other classes
        if name != class_obj.name:
            if SchoolClass.objects.filter(school=school, name=name).exists():
                messages.error(
                    request,
                    f'A class named "{name}" already exists in this school.',
                )
                return render(request, 'school_admin/class_form.html', {
                    'class_obj': class_obj,
                    'is_edit': True,
                })

        try:
            with transaction.atomic():
                class_obj.name = name
                class_obj.level = level
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
            return render(request, 'school_admin/class_form.html', {
                'class_obj': class_obj,
                'is_edit': True,
            })


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
