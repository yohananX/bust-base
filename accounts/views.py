from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views.generic.base import RedirectView, View


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


class ForcedPasswordChangeView(LoginRequiredMixin, View):
    """First-login password change for accounts with generated passwords.

    Middleware funnels users with ``must_change_password`` here regardless
    of role. Successful change clears the flag; the user then lands on their
    role dashboard via the post-login redirect.
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.must_change_password:
            return redirect('post_login_redirect')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        return render(request, 'accounts/forced_password_change.html')

    def post(self, request):
        current_password = request.POST.get('current_password', '').strip()
        new_password = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()

        if not current_password:
            messages.error(request, 'Enter your current (temporary) password.')
            return redirect('forced_password_change')

        if not request.user.check_password(current_password):
            messages.error(request, 'Current password is incorrect.')
            return redirect('forced_password_change')

        if len(new_password) < 6:
            messages.error(request, 'New password must be at least 6 characters.')
            return redirect('forced_password_change')

        if new_password != confirm_password:
            messages.error(request, 'New passwords do not match.')
            return redirect('forced_password_change')

        if new_password == current_password:
            messages.error(request, 'New password must be different from the current one.')
            return redirect('forced_password_change')

        request.user.set_password(new_password)
        request.user.must_change_password = False
        request.user.save(update_fields=['password', 'must_change_password'])
        messages.success(request, 'Password updated. Welcome aboard!')
        return redirect('post_login_redirect')