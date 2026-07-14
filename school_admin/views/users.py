"""User management views for school admin portal."""
from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic.base import View
from django.contrib import messages

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles, User


class UserListView(RoleRequiredMixin, View):
    """List all users in the admin's school."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        users = User.objects.filter(school=school).order_by('role', 'last_name', 'first_name')

        # Search
        q = request.GET.get('q', '')
        if q:
            from django.db.models import Q
            users = users.filter(
                Q(first_name__icontains=q) |
                Q(last_name__icontains=q) |
                Q(email__icontains=q) |
                Q(username__icontains=q)
            )

        context = {
            'users': users,
            'q': q,
        }
        return render(request, 'school_admin/user_list.html', context)


class UserCreateView(RoleRequiredMixin, View):
    """Create a new user in the school."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        context = {
            'roles': Roles.CHOICES,
        }
        return render(request, 'school_admin/user_form.html', context)

    def post(self, request):
        school = request.school
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        role = request.POST.get('role', '')
        password = request.POST.get('password', '')
        phone_number = request.POST.get('phone_number', '').strip()

        if not all([username, email, role, password]):
            messages.error(request, 'Username, email, role, and password are required.')
            return render(request, 'school_admin/user_form.html', {'roles': Roles.CHOICES})

        if User.objects.filter(username=username).exists():
            messages.error(request, f'Username "{username}" is already taken.')
            return render(request, 'school_admin/user_form.html', {'roles': Roles.CHOICES})

        if User.objects.filter(email=email).exists():
            messages.error(request, f'Email "{email}" is already in use.')
            return render(request, 'school_admin/user_form.html', {'roles': Roles.CHOICES})

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role=role,
            school=school,
            phone_number=phone_number,
        )
        messages.success(request, f'User "{user.get_full_name() or user.username}" created successfully.')
        return redirect('school_admin:user_list')


class UserEditView(RoleRequiredMixin, View):
    """Edit an existing user."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        user = get_object_or_404(User, school=school, pk=pk)
        context = {
            'user_obj': user,
            'roles': Roles.CHOICES,
            'is_edit': True,
        }
        return render(request, 'school_admin/user_form.html', context)

    def post(self, request, pk):
        school = request.school
        user = get_object_or_404(User, school=school, pk=pk)

        email = request.POST.get('email', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        role = request.POST.get('role', '')
        phone_number = request.POST.get('phone_number', '').strip()
        password = request.POST.get('password', '').strip()

        if not all([email, role]):
            messages.error(request, 'Email and role are required.')
            return render(request, 'school_admin/user_form.html', {
                'user_obj': user,
                'roles': Roles.CHOICES,
                'is_edit': True,
            })

        # Check email uniqueness (exclude current user)
        if User.objects.filter(email=email).exclude(pk=user.pk).exists():
            messages.error(request, f'Email "{email}" is already in use by another user.')
            return render(request, 'school_admin/user_form.html', {
                'user_obj': user,
                'roles': Roles.CHOICES,
                'is_edit': True,
            })

        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.role = role
        user.phone_number = phone_number
        if password:
            user.set_password(password)
        user.save()

        messages.success(request, f'User "{user.get_full_name() or user.username}" updated successfully.')
        return redirect('school_admin:user_list')


class UserToggleActiveView(RoleRequiredMixin, View):
    """Toggle a user's is_active status via POST."""

    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        school = request.school
        user = get_object_or_404(User, school=school, pk=pk)

        # Don't allow deactivating yourself
        if user.pk == request.user.pk:
            messages.warning(request, 'You cannot deactivate your own account.')
            return redirect('school_admin:user_list')

        user.is_active = not user.is_active
        user.save()
        status = 'activated' if user.is_active else 'deactivated'
        messages.success(request, f'User "{user.get_full_name() or user.username}" {status}.')
        return redirect('school_admin:user_list')
