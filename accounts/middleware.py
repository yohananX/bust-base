from django.shortcuts import redirect


class PasswordChangeRequiredMiddleware:
    """Funnel users flagged ``must_change_password`` to the forced-change page.

    Applies to every role (students, parents, teachers). Only the change
    page, logout, and the Django admin are reachable until the flag is
    cleared, so generated credentials can never be used to roam the portal.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if (
            user is not None
            and user.is_authenticated
            and getattr(user, 'must_change_password', False)
        ):
            path = request.path
            if not (
                path == '/accounts/forced-password-change/'
                or path == '/accounts/logout/'
                or path.startswith('/secure-control-panel/')
                or path.startswith('/static/')
                or path.startswith('/media/')
                or path == '/health/'
            ):
                return redirect('forced_password_change')

        response = self.get_response(request)
        return response