"""Staff management views for school admin portal."""
from django.shortcuts import render
from django.views.generic.base import View
from django.db.models import Q

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from payroll.models import StaffProfile


class StaffListView(RoleRequiredMixin, View):
    """List all staff profiles in the admin's school."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        staff = StaffProfile.objects.filter(
            school=school
        ).select_related('user', 'pay_grade')

        # Search by name / employee ID
        q = request.GET.get('q', '')
        if q:
            staff = staff.filter(
                Q(user__first_name__icontains=q) |
                Q(user__last_name__icontains=q) |
                Q(employee_id__icontains=q)
            )

        # Filter by status
        status = request.GET.get('status', '')
        if status:
            staff = staff.filter(status=status)

        context = {
            'staff_list': staff,
            'q': q,
            'filter_status': status,
            'status_choices': StaffProfile.STATUS_CHOICES,
        }
        return render(request, 'school_admin/staff_list.html', context)


class StaffCreateView(RoleRequiredMixin, View):
    """Placeholder for staff creation — redirects to admin."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        from django.contrib import messages
        from django.shortcuts import redirect
        messages.info(request, 'Use the admin panel to create staff profiles with complete data.')
        return redirect('school_admin:staff_list')
