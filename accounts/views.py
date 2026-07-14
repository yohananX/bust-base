from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic.base import RedirectView


class PostLoginRedirectView(LoginRequiredMixin, RedirectView):
    """Redirect authenticated users to their role-specific dashboard."""
    
    def get_redirect_url(self, *args, **kwargs):
        role = self.request.user.role
        mapping = {
            'ADMIN': '/admin/',
            'TEACHER': '/teacher/',
            'STUDENT': '/student/',
            'PARENT': '/parent/',
        }
        return mapping.get(role, '/admin/')
