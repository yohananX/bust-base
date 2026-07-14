"""Results publication view for school admin portal."""
from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic.base import View
from django.contrib import messages

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from core.models import Term


class PublishResultsView(RoleRequiredMixin, View):
    """List terms and toggle results publication."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        terms = Term.objects.filter(school=school).order_by('-start_date')
        return render(request, 'school_admin/publish_results.html', {
            'terms': terms,
        })

    def post(self, request):
        school = request.school
        term_id = request.POST.get('term_id')
        action = request.POST.get('action', '')  # 'publish' or 'unpublish'

        if not term_id:
            messages.error(request, 'Please select a term.')
            return redirect('school_admin:publish_results')

        term = get_object_or_404(Term, school=school, pk=term_id)

        if action == 'publish':
            term.results_published = True
            term.save(update_fields=['results_published'])
            messages.success(request, f'Results published for term "{term.name}".')

            # Notify primary-contact guardians
            from notifications.utils import notify
            from notifications.models import NotificationLog

            if not NotificationLog.objects.filter(
                reference='term-results:{}'.format(term.id)
            ).exists():
                from academics.models import Score
                from students.models import StudentGuardianLink
                from django.contrib.auth import get_user_model

                student_ids = Score.objects.filter(
                    school=school, term=term
                ).values_list('student', flat=True).distinct()

                guardian_ids = StudentGuardianLink.objects.filter(
                    student__in=list(student_ids),
                    is_primary_contact=True,
                ).values_list('guardian', flat=True)

                for guardian in get_user_model().objects.filter(pk__in=guardian_ids):
                    notify(
                        recipient=guardian,
                        channel='EMAIL',
                        subject=f'Results available for {term.name}',
                        message=f'Results for {term.name} are now available.',
                        reference='term-results:{}'.format(term.id),
                    )

        elif action == 'unpublish':
            term.results_published = False
            term.save(update_fields=['results_published'])
            messages.success(request, f'Results unpublished for term "{term.name}".')

        return redirect('school_admin:publish_results')
