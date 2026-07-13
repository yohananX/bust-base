from django.core.exceptions import PermissionDenied
from django.contrib.auth.mixins import LoginRequiredMixin


class RoleRequiredMixin(LoginRequiredMixin):
    """Mixin that restricts access to users with specific roles.

    Usage:
        class MyView(RoleRequiredMixin, View):
            allowed_roles = [Roles.ADMIN, Roles.TEACHER]
    """
    allowed_roles = []

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.role not in self.allowed_roles:
            raise PermissionDenied("You do not have permission to access this page.")
        return super().dispatch(request, *args, **kwargs)


class SchoolScopedQuerySetMixin:
    """Mixin that automatically filters querysets to the current user's school.

    For models inheriting from TenantScopedModel, this adds
    .filter(school=request.school) to all get_queryset() calls.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_authenticated and hasattr(self.request, 'school'):
            return qs.filter(school=self.request.school)
        return qs
