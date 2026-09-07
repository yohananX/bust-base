"""Shared mixins and forms for school_admin generic views."""

from django.views.generic import CreateView, DeleteView, UpdateView
from django.urls import reverse_lazy

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles


class SchoolScopedMixin:
    """Filter queryset by the current request's school."""

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(school=self.request.school)


class AdminRequiredMixin:
    """Require ADMIN role."""
    allowed_roles = [Roles.ADMIN]


class AdminCreateView(AdminRequiredMixin, RoleRequiredMixin, CreateView):
    pass


class AdminUpdateView(AdminRequiredMixin, RoleRequiredMixin, SchoolScopedMixin, UpdateView):
    pass


class AdminDeleteView(AdminRequiredMixin, RoleRequiredMixin, SchoolScopedMixin, DeleteView):
    success_url = None

    def get_success_url(self):
        return reverse_lazy(self.success_url)
