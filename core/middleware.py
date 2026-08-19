from django.shortcuts import redirect

from .audit import set_current_user


class SchoolMiddleware:
    """Sets request.school and redirects school admins from superadmin area."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            request.school = getattr(request.user, 'school', None)

            # Redirect school admins away from /secure-control-panel/ to /school-admin/
            if (getattr(request.user, 'role', None) == 'ADMIN' 
                and not request.user.is_superuser
                and request.path.startswith('/secure-control-panel/')):
                return redirect('/school-admin/')
        else:
            request.school = None

        response = self.get_response(request)
        return response


class CurrentUserMiddleware:
    """Track the request user thread-locally so audit signals can record actors."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        set_current_user(request.user if request.user.is_authenticated else None)
        try:
            return self.get_response(request)
        finally:
            set_current_user(None)
