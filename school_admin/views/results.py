"""Results publication and review views for school admin portal."""
from django.shortcuts import render, get_object_or_404, redirect, reverse
from urllib.parse import urlencode
from django.views.generic.base import View
from django.contrib import messages
from django.db.models import Count, Q
from django.utils import timezone

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from core.models import Term
from academics.models import Score
from students.models import SchoolClass


class PublishResultsView(RoleRequiredMixin, View):
    """List terms and toggle results publication."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        terms = Term.objects.filter(school=school).order_by('-start_date')

        # Annotate terms with moderation stats
        terms_with_stats = []
        for term in terms:
            score_counts = Score.objects.filter(school=school, term=term).aggregate(
                total=Count('id'),
                pending=Count('id', filter=Q(moderation_status=Score.MODERATION_PENDING)),
                approved=Count('id', filter=Q(moderation_status=Score.MODERATION_APPROVED)),
                rejected=Count('id', filter=Q(moderation_status=Score.MODERATION_REJECTED)),
            )
            terms_with_stats.append({
                'term': term,
                'total_scores': score_counts['total'],
                'pending_count': score_counts['pending'],
                'approved_count': score_counts['approved'],
                'rejected_count': score_counts['rejected'],
            })

        return render(request, 'school_admin/publish_results.html', {
            'terms': terms_with_stats,
        })

    def post(self, request):
        school = request.school
        term_id = request.POST.get('term_id')
        action = request.POST.get('action', '')  # 'publish' or 'unpublish'

        if not term_id or action not in ('publish', 'unpublish'):
            messages.error(request, 'Invalid request.')
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


class ResultReviewView(RoleRequiredMixin, View):
    """Review and moderate individual student scores per term/class."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        term_id = request.GET.get('term_id')
        class_id = request.GET.get('class_id')

        terms = Term.objects.filter(school=school).order_by('-start_date')

        # Get classes that have scores in selected term
        classes = SchoolClass.objects.none()
        scores = Score.objects.none()
        selected_term = None
        selected_class = None
        class_summary = []

        if term_id:
            selected_term = get_object_or_404(Term, school=school, pk=term_id)

            # Find classes with scores in this term
            class_ids = Score.objects.filter(
                school=school, term=selected_term
            ).values_list(
                'student__enrollments__school_class', flat=True
            ).distinct()
            classes = SchoolClass.objects.filter(
                pk__in=list(class_ids), is_active=True
            ).order_by('level', 'name')

            if class_id:
                selected_class = get_object_or_404(SchoolClass, school=school, pk=class_id)

                # Get all scores for this term + class
                scores = Score.objects.filter(
                    school=school,
                    term=selected_term,
                    student__enrollments__school_class=selected_class,
                    student__enrollments__is_current=True,
                ).select_related(
                    'student__user', 'subject', 'entered_by', 'moderated_by'
                ).order_by('student__admission_number', 'subject__name')
            else:
                # Show summary per class
                for cls in classes:
                    counts = Score.objects.filter(
                        school=school,
                        term=selected_term,
                        student__enrollments__school_class=cls,
                        student__enrollments__is_current=True,
                    ).aggregate(
                        total=Count('id'),
                        pending=Count('id', filter=Q(moderation_status=Score.MODERATION_PENDING)),
                        approved=Count('id', filter=Q(moderation_status=Score.MODERATION_APPROVED)),
                        rejected=Count('id', filter=Q(moderation_status=Score.MODERATION_REJECTED)),
                    )
                    class_summary.append({
                        'class': cls,
                        'total_scores': counts['total'],
                        'pending_count': counts['pending'],
                        'approved_count': counts['approved'],
                        'rejected_count': counts['rejected'],
                    })

        return render(request, 'school_admin/review_results.html', {
            'terms': terms,
            'classes': classes,
            'scores': scores,
            'selected_term': selected_term,
            'selected_class': selected_class,
            'class_summary': class_summary,
        })

    def post(self, request):
        school = request.school
        score_id = request.POST.get('score_id')
        action = request.POST.get('action')
        term_id = request.POST.get('term_id')
        class_id = request.POST.get('class_id')

        if action in ('approve', 'reject') and score_id:
            score = get_object_or_404(Score, school=school, pk=score_id)

            if action == 'approve':
                score.moderation_status = Score.MODERATION_APPROVED
                messages.success(request, f'Score approved for {score.student} - {score.subject}.')
            elif action == 'reject':
                score.moderation_status = Score.MODERATION_REJECTED
                messages.success(request, f'Score rejected for {score.student} - {score.subject}.')

            score.moderated_by = request.user
            score.moderated_at = timezone.now()
            score.save(update_fields=['moderation_status', 'moderated_by', 'moderated_at'])

        elif action == 'approve_all':
            if term_id and class_id:
                updated = Score.objects.filter(
                    school=school,
                    term_id=term_id,
                    student__enrollments__school_class_id=class_id,
                    student__enrollments__is_current=True,
                    moderation_status=Score.MODERATION_PENDING,
                ).update(
                    moderation_status=Score.MODERATION_APPROVED,
                    moderated_by=request.user,
                    moderated_at=timezone.now(),
                )
                messages.success(request, f'{updated} pending scores approved.')
            else:
                messages.error(request, 'Missing term or class information.')

        else:
            messages.error(request, 'Invalid request.')

        # Redirect back to same view preserving filters
        redirect_url = reverse('school_admin:review_results')
        params = {}
        if term_id:
            params['term_id'] = term_id
        if class_id:
            params['class_id'] = class_id
        return redirect(f"{redirect_url}?{urlencode(params)}" if params else redirect_url)
