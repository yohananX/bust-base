from accounts.models import Roles


class GuardianScopedQuerySetMixin:
    """Mixin that limits student querysets to only those linked to the current parent user.

    For parent-facing views, this provides privacy isolation so a parent
    only sees their own linked children.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_authenticated and self.request.user.role == Roles.PARENT:
            return qs.filter(guardian_links__guardian=self.request.user)
        return qs
