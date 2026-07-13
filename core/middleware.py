class SchoolMiddleware:
    """Sets request.school based on the authenticated user's school.

    Must be placed after AuthenticationMiddleware in MIDDLEWARE settings.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            request.school = getattr(request.user, 'school', None)
        else:
            request.school = None
        response = self.get_response(request)
        return response
