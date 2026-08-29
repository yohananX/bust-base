"""Search/autocomplete APIs for admin portals.

Each view returns a JSON array of ``{id, name, subtitle}`` records consumed by
``templates/components/search_autocomplete.html``. APIs that can cheaply detect
changes (a model with ``updated_at``) send ``Last-Modified`` and honour
``If-Modified-Since`` (HTTP 304), so the autocomplete can revalidate its
localStorage cache with a near-zero-cost request.
"""
from django.http import JsonResponse, HttpResponseNotModified
from django.utils.http import http_date, parse_http_date
from django.views.generic.base import View

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles, User
from academics.models import Subject
from fees.models import Invoice
from notifications.models import NotificationLog
from students.models import Student, SchoolClass
from lessons.models import LessonEnrollment


class EntitySearchAPIView(RoleRequiredMixin, View):
    """Base autocomplete API — override ``get_queryset``/``serialize``."""

    allowed_roles = [Roles.ADMIN]

    def get_queryset(self, request):
        raise NotImplementedError

    def serialize(self, obj):
        raise NotImplementedError

    def get_last_modified(self, request):
        """Return a datetime to use for Last-Modified, or None to skip caching."""
        return None

    def get(self, request):
        last_modified = self.get_last_modified(request)

        if last_modified:
            lm_ts = last_modified.timestamp()
            lm_header = http_date(lm_ts)
            since = request.META.get('HTTP_IF_MODIFIED_SINCE')
            if since:
                try:
                    if int(lm_ts) <= parse_http_date(since):
                        resp = HttpResponseNotModified()
                        resp['Last-Modified'] = lm_header
                        resp['Cache-Control'] = 'private, max-age=0, must-revalidate'
                        return resp
                except (ValueError, TypeError):
                    pass

        payload = [self.serialize(o) for o in self.get_queryset(request)]
        response = JsonResponse(payload, safe=False)
        if last_modified:
            response['Last-Modified'] = lm_header
        response['Cache-Control'] = 'private, max-age=0, must-revalidate'
        return response


def _user_payload(u):
    return {
        'id': u.pk,
        'name': u.get_full_name() or u.username,
        'subtitle': f'{u.email} · {u.get_role_display()}',
    }


class StudentSearchAPIView(EntitySearchAPIView):
    def get_queryset(self, request):
        return Student.objects.filter(school=request.school).select_related(
            'user', 'user__student_profile'
        ).prefetch_related('enrollments').order_by('user__first_name', 'user__last_name')

    def serialize(self, student):
        enrollment = next(
            (e for e in student.enrollments.all() if e.is_current), None
        )
        name = student.user.get_full_name() or student.user.username
        return {
            'id': student.pk,
            'name': name,
            'subtitle': ' · '.join(filter(None, [
                student.admission_number,
                enrollment.school_class.name if enrollment else '',
            ])),
        }

    def get_last_modified(self, request):
        newest = Student.objects.filter(
            school=request.school
        ).order_by('-updated_at').values('updated_at').first()
        if newest and newest.get('updated_at'):
            return newest['updated_at']
        return None


class StaffSearchAPIView(EntitySearchAPIView):
    def get_queryset(self, request):
        return User.objects.filter(
            school=request.school,
            role__in=[Roles.TEACHER, Roles.ADMIN],
        ).order_by('role', 'last_name', 'first_name')

    def serialize(self, user):
        return _user_payload(user)


class MemberSearchAPIView(EntitySearchAPIView):
    """Autocomplete for resettable school members (staff/student/parent)."""

    def get_queryset(self, request):
        return User.objects.filter(
            school=request.school,
            role__in=[Roles.TEACHER, Roles.STUDENT, Roles.PARENT],
        ).select_related('student_profile').order_by('role', 'last_name', 'first_name')

    def serialize(self, user):
        payload = _user_payload(user)
        # Make the admission number searchable (and visible) for students.
        admission = getattr(user, 'student_profile', None)
        if admission is not None:
            payload['name'] = user.get_full_name() or user.username
            payload['subtitle'] = ' · '.join(filter(None, [
                admission.admission_number,
                user.email,
                user.get_role_display(),
            ]))
        return payload


class InvoiceSearchAPIView(EntitySearchAPIView):
    def get_queryset(self, request):
        return Invoice.objects.filter(school=request.school).select_related(
            'student__user', 'term'
        ).order_by('student__user__last_name', 'student__user__first_name')

    def serialize(self, invoice):
        student = invoice.student.user
        return {
            'id': invoice.pk,
            'name': student.get_full_name() or student.username,
            'subtitle': f'{invoice.term.name} · ₦{invoice.total_amount} · {invoice.status}',
        }


class ClassSearchAPIView(EntitySearchAPIView):
    def get_queryset(self, request):
        return SchoolClass.objects.filter(school=request.school).order_by('level', 'name')

    def serialize(self, school_class):
        return {
            'id': school_class.pk,
            'name': school_class.name,
            'subtitle': school_class.level,
        }


class SubjectSearchAPIView(EntitySearchAPIView):
    def get_queryset(self, request):
        return Subject.objects.filter(school=request.school).order_by('name')

    def serialize(self, subject):
        return {
            'id': subject.pk,
            'name': subject.name,
            'subtitle': subject.code,
        }


class NotificationSearchAPIView(EntitySearchAPIView):
    def get_queryset(self, request):
        return NotificationLog.objects.filter(
            school=request.school,
        ).select_related('recipient').order_by('-id')

    def serialize(self, log):
        return {
            'id': log.pk,
            'name': log.subject,
            'subtitle': log.recipient.email,
        }


class EnrollmentSearchAPIView(EntitySearchAPIView):
    def get_queryset(self, request):
        return LessonEnrollment.objects.filter(
            school=request.school,
        ).select_related(
            'lesson_class', 'lesson_class__period', 'student', 'student__user',
        ).order_by('-registered_on')

    def serialize(self, enrollment):
        name = enrollment.child_name
        subtitle = f"{enrollment.lesson_class.name} · {enrollment.lesson_class.period.name}"
        return {
            'id': enrollment.pk,
            'name': name,
            'subtitle': subtitle,
        }
