"""Staff management views for school admin portal."""

from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.views.generic.base import View
from django.contrib import messages
from django.db.models import Q
from django.db import transaction
from django.core.exceptions import PermissionDenied

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles, User
from accounts.utils import generate_password, unique_username


def _superuser_or_school_qs(request, queryset):
    if request.user.is_superuser:
        return queryset
    return queryset.filter(school=request.school)


class StaffListView(RoleRequiredMixin, View):
    """List all staff (TEACHER + ADMIN users) in the admin's school."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        qs = User.objects.filter(role__in=[Roles.TEACHER, Roles.ADMIN])
        if not request.user.is_superuser:
            qs = qs.filter(school=school)
        staff = qs.order_by('role', 'last_name', 'first_name')

        q = request.GET.get('q', '')
        if q:
            staff = staff.filter(
                Q(first_name__icontains=q) |
                Q(last_name__icontains=q) |
                Q(email__icontains=q)
            )

        context = {
            'staff_list': staff,
            'q': q,
        }
        return render(request, 'school_admin/staff/staff_list.html', context)


class StaffCreateView(RoleRequiredMixin, View):
    """Create a new staff user (TEACHER or ADMIN)."""

    allowed_roles = [Roles.ADMIN]

    STAFF_ROLES = [
        (Roles.TEACHER, 'Teacher'),
        (Roles.ADMIN, 'Admin'),
    ]

    def get(self, request):
        context = {'staff_roles': self.STAFF_ROLES}
        return render(request, 'school_admin/staff/staff_form.html', context)

    def post(self, request):
        school = request.school
        email = request.POST.get('email', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        role = request.POST.get('role', '')
        phone_number = request.POST.get('phone_number', '').strip()

        # Phone is required, email is not; username is auto-generated
        if not all([first_name, last_name, role, phone_number]):
            messages.error(request, 'Name, role, and phone number are required.')
            return render(request, 'school_admin/staff/staff_form.html', {'staff_roles': self.STAFF_ROLES})

        if role not in [Roles.TEACHER, Roles.ADMIN]:
            messages.error(request, 'Staff role must be Teacher or Admin.')
            return render(request, 'school_admin/staff/staff_form.html', {'staff_roles': self.STAFF_ROLES})

        if email and User.objects.filter(email=email).exists():
            messages.error(request, f'Email "{email}" is already in use.')
            return render(request, 'school_admin/staff/staff_form.html', {'staff_roles': self.STAFF_ROLES})

        # Auto-generate username and password
        username = unique_username(first_name, last_name)
        password = generate_password(8)

        user = User.objects.create_user(
            username=username,
            email=email or '',
            password=password,
            first_name=first_name,
            last_name=last_name,
            role=role,
            school=school,
            phone_number=phone_number,
        )

        messages.success(
            request,
            f'Staff "{user.get_full_name() or user.username}" created. '
            f'Username: {user.username} Password: {password}'
        )

        if role == Roles.TEACHER:
            return redirect(f"{reverse('school_admin:assignment_list')}?teacher_id={user.pk}")
        return redirect('school_admin:staff_list')


class StaffEditView(RoleRequiredMixin, View):
    """Edit an existing staff user."""

    allowed_roles = [Roles.ADMIN]

    STAFF_ROLES = [
        (Roles.TEACHER, 'Teacher'),
        (Roles.ADMIN, 'Admin'),
    ]

    def get(self, request, pk):
        school = request.school
        user = get_object_or_404(User, school=school, pk=pk, role__in=[Roles.TEACHER, Roles.ADMIN])
        context = {
            'staff_obj': user,
            'staff_roles': self.STAFF_ROLES,
            'is_edit': True,
        }
        return render(request, 'school_admin/staff/staff_form.html', context)

    def post(self, request, pk):
        school = request.school
        user = get_object_or_404(User, school=school, pk=pk, role__in=[Roles.TEACHER, Roles.ADMIN])

        email = request.POST.get('email', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        role = request.POST.get('role', '')
        phone_number = request.POST.get('phone_number', '').strip()
        password = request.POST.get('password', '').strip()

        if not all([first_name, last_name, role, phone_number]):
            messages.error(request, 'Name, role, and phone number are required.')
            return render(request, 'school_admin/staff/staff_form.html', {
                'staff_obj': user,
                'staff_roles': self.STAFF_ROLES,
                'is_edit': True,
            })

        if role not in [Roles.TEACHER, Roles.ADMIN]:
            messages.error(request, 'Staff role must be Teacher or Admin.')
            return render(request, 'school_admin/staff/staff_form.html', {
                'staff_obj': user,
                'staff_roles': self.STAFF_ROLES,
                'is_edit': True,
            })

        if email and User.objects.filter(email=email).exclude(pk=user.pk).exists():
            messages.error(request, f'Email "{email}" is already in use by another user.')
            return render(request, 'school_admin/staff/staff_form.html', {
                'staff_obj': user,
                'staff_roles': self.STAFF_ROLES,
                'is_edit': True,
            })

        user.email = email or ''
        user.first_name = first_name
        user.last_name = last_name
        user.role = role
        user.phone_number = phone_number
        if password:
            user.set_password(password)
        user.save()

        messages.success(request, f'Staff "{user.get_full_name() or user.username}" updated successfully.')
        return redirect('school_admin:staff_list')


class StaffToggleActiveView(RoleRequiredMixin, View):
    """Toggle a staff user's is_active status."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        user = get_object_or_404(User, school=school, pk=pk, role__in=[Roles.TEACHER, Roles.ADMIN])

        if user.pk == request.user.pk:
            messages.warning(request, 'You cannot deactivate your own account.')
            return redirect('school_admin:staff_list')

        user.is_active = not user.is_active
        user.save()
        status = 'activated' if user.is_active else 'deactivated'
        messages.success(request, f'Staff "{user.get_full_name() or user.username}" {status}.')
        return redirect('school_admin:staff_list')


class StaffDeleteView(RoleRequiredMixin, View):
    """Hard-delete a staff user. Superusers only."""

    allowed_roles = [Roles.ADMIN]

    def _get_staff_user(self, request, pk):
        qs = User.objects.filter(pk=pk, role__in=[Roles.TEACHER, Roles.ADMIN])
        qs = _superuser_or_school_qs(request, qs)
        return get_object_or_404(qs)

    def get(self, request, pk):
        if not request.user.is_superuser:
            raise PermissionDenied("Only superadmins can delete users.")

        staff_user = self._get_staff_user(request, pk)
        if staff_user.pk == request.user.pk:
            messages.warning(request, "You cannot delete your own account.")
            return redirect('school_admin:staff_list')

        from academics.models import TeacherAssignment, Score
        from payroll.models import PayrollRun, Payslip
        from finance.models import Expenditure, Project
        from lessons.models import LessonTeacherAssignment
        from notifications.models import NotificationLog
        from inventory.models import InventoryItem, InventoryProcurement, InventoryTransaction

        related = {
            'teacher_assignments': TeacherAssignment.objects.filter(teacher=staff_user).count(),
            'scores_entered': Score.objects.filter(entered_by=staff_user).count(),
            'payroll_runs': PayrollRun.objects.filter(generated_by=staff_user).count(),
            'payslips': Payslip.objects.filter(teacher=staff_user).count(),
            'projects': Project.objects.filter(created_by=staff_user).count(),
            'expenditures': Expenditure.objects.filter(created_by=staff_user).count(),
            'lesson_teacher_assignments': LessonTeacherAssignment.objects.filter(teacher=staff_user).count(),
            'notifications': NotificationLog.objects.filter(recipient=staff_user).count(),
            'inventory_items': InventoryItem.objects.filter(created_by=staff_user).count(),
            'procurements': InventoryProcurement.objects.filter(purchased_by=staff_user).count(),
            'inventory_transactions': InventoryTransaction.objects.filter(created_by=staff_user).count(),
        }
        has_related = any(v > 0 for v in related.values())

        context = {
            'staff_user': staff_user,
            'related': related,
            'has_related': has_related,
        }
        return render(request, 'school_admin/staff/staff_confirm_delete.html', context)

    def post(self, request, pk):
        if not request.user.is_superuser:
            raise PermissionDenied("Only superadmins can delete users.")

        staff_user = self._get_staff_user(request, pk)
        name = staff_user.get_full_name() or staff_user.username

        if staff_user.pk == request.user.pk:
            messages.warning(request, "You cannot delete your own account.")
            return redirect('school_admin:staff_list')

        try:
            with transaction.atomic():
                staff_user.delete()
            messages.success(request, f'Staff "{name}" has been permanently deleted.')
        except Exception as e:
            messages.error(request, f'Error deleting staff: {e}')

        return redirect('school_admin:staff_list')
