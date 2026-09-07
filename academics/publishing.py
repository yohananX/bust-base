"""Results publication helpers shared by the admin portal and Django admin."""
from django.contrib.auth import get_user_model

from notifications.models import NotificationLog
from notifications.utils import notify
from students.models import Student, StudentGuardianLink


def notify_results_published(term, student_ids):
    """Notify each student and their primary guardian that results are out.

    One IN_APP row per recipient, child-specific deep links, deduped by
    (recipient, reference) so re-publishing a term never re-spams.

    ``student_ids`` is any iterable of Student pks that have scores in the
    term (callers derive this from Scores or an admin queryset).
    """
    from django.urls import reverse as url_reverse

    student_ids = list(student_ids)

    student_users = {
        pk: user_id for pk, user_id in Student.objects.filter(
            pk__in=student_ids, user__isnull=False,
        ).values_list('pk', 'user_id')
    }
    users_by_id = {
        u.pk: u for u in get_user_model().objects.filter(
            pk__in=list(student_users.values())
        )
    }

    links = StudentGuardianLink.objects.filter(
        student__in=student_ids,
        is_primary_contact=True,
    ).select_related('student__user', 'guardian')

    notified = set(
        NotificationLog.objects.filter(
            reference__startswith=f'term-results:{term.id}',
            recipient_id__in=(
                list(student_users.values())
                + list(links.values_list('guardian', flat=True))
            ),
        ).values_list('recipient_id', 'reference')
    )

    def _notify_one(recipient, ref_suffix, subject, message, url_kwargs):
        ref = f'term-results:{term.id}:{ref_suffix}'
        if (recipient.pk, ref) in notified:
            return
        notify(
            recipient=recipient,
            channel='IN_APP',
            subject=subject,
            message=message,
            reference=ref,
            url=url_reverse('parent-child-result-booklet', kwargs=url_kwargs),
        )

    for link in links:
        _notify_one(
            recipient=link.guardian,
            ref_suffix=f'g:{link.student_id}',
            subject=f'Results available for {term.name}',
            message=(
                f"{link.student.user.get_full_name()}'s results for {term.name} are now available."
            ),
            url_kwargs={
                'child_pk': link.student_id,
                'term_id': term.id,
            },
        )

    for student_id, user_id in student_users.items():
        _notify_one(
            recipient=users_by_id[user_id],
            ref_suffix=f's:{student_id}',
            subject=f'Results available for {term.name}',
            message=f'Your results for {term.name} are now available.',
            url_kwargs={
                'term_id': term.id,
            },
        )