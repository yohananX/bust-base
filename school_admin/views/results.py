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
from academics.models import Score, Subject, TeacherAssignment
from students.models import SchoolClass


class PublishResultsView(RoleRequiredMixin, View):
    """List terms and toggle results publication."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        terms = Term.for_current_session(school)

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

            # Notify each student and their guardians (per child, child-
            # specific deep link). Rows dedup by reference + recipient.
            from notifications.utils import notify
            from notifications.models import NotificationLog
            from students.models import Student, StudentGuardianLink
            from django.contrib.auth import get_user_model
            from django.urls import reverse as url_reverse

            student_ids = Score.objects.filter(
                school=school, term=term
            ).values_list('student', flat=True).distinct()
            student_users = {
                pk: user_id for pk, user_id in Student.objects.filter(
                    pk__in=list(student_ids), user__isnull=False,
                ).values_list('pk', 'user_id')
            }
            users_by_id = {
                u.pk: u for u in get_user_model().objects.filter(
                    pk__in=list(student_users.values())
                )
            }

            links = StudentGuardianLink.objects.filter(
                student__in=list(student_ids),
                is_primary_contact=True,
            ).select_related('student__user', 'guardian')

            notified = set(
                NotificationLog.objects.filter(
                    reference__startswith='term-results:{}'.format(term.id),
                    recipient_id__in=(
                        list(student_users.values())
                        + list(links.values_list('guardian', flat=True))
                    ),
                ).values_list('recipient_id', 'reference')
            )

            for link in links:
                ref = 'term-results:{}:g:{}'.format(term.id, link.student_id)
                if (link.guardian_id, ref) in notified:
                    continue
                notify(
                    recipient=link.guardian,
                    channel='IN_APP',
                    subject='Results available for {}'.format(term.name),
                    message=(
                        "{child}'s results for {term} are now available."
                    ).format(child=link.student.user.get_full_name(), term=term.name),
                    reference=ref,
                    url=url_reverse('parent-child-result-booklet', kwargs={
                        'child_pk': link.student_id,
                        'term_id': term.id,
                    }),
                )

            for student_id, user_id in student_users.items():
                ref = 'term-results:{}:s:{}'.format(term.id, student_id)
                if (user_id, ref) in notified:
                    continue
                notify(
                    recipient=users_by_id[user_id],
                    channel='IN_APP',
                    subject='Results available for {}'.format(term.name),
                    message='Your results for {} are now available.'.format(term.name),
                    reference=ref,
                    url=url_reverse('student-result-booklet', kwargs={
                        'term_id': term.id,
                    }),
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
        subject_id = request.GET.get('subject_id') or ''
        status_filter = request.GET.get('status', 'all')
        q = request.GET.get('q', '').strip()

        terms = Term.for_current_session(school)

        # Default to the current active term when none is explicitly selected,
        # so the review page always shows content on load.
        if not term_id:
            current = Term.objects.filter(school=school, is_current=True).first()
            if current:
                term_id = str(current.pk)

        # Get classes that have scores in selected term
        classes = SchoolClass.objects.none()
        selected_term = None
        selected_class = None
        class_summary = []
        matrix = []
        subjects = []
        subject_options = []
        subject_pending = {}
        class_teachers = []
        teacher_by_subject = {}

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

                # Teachers assigned to this class (and subject) for the session
                # the selected term belongs to.
                class_assignments = TeacherAssignment.objects.filter(
                    school_class=selected_class,
                    session=selected_term.session,
                ).select_related('teacher')
                teacher_by_subject = {}
                for assignment in class_assignments:
                    teacher_by_subject.setdefault(
                        assignment.subject_id, []
                    ).append(assignment.teacher.get_full_name() or assignment.teacher.username)
                class_teachers = sorted({
                    name
                    for names in teacher_by_subject.values()
                    for name in names
                })

                # Subject filter options are scoped to the selected class
                subject_options = list(
                    Subject.objects.filter(
                        school=school,
                        scores__term=selected_term,
                        scores__student__enrollments__school_class=selected_class,
                        scores__student__enrollments__is_current=True,
                    ).distinct().order_by('name')
                )

                # Get all scores for this term + class
                scores = Score.objects.filter(
                    school=school,
                    term=selected_term,
                    student__enrollments__school_class=selected_class,
                    student__enrollments__is_current=True,
                ).select_related(
                    'student__user', 'subject', 'entered_by', 'moderated_by'
                ).order_by('student__admission_number', 'subject__name')

                if subject_id:
                    scores = scores.filter(subject_id=subject_id)

                # Student search: split into tokens so "Adaeze Adewale" works
                if q:
                    tokens = [t for t in q.split() if t]
                    q_filter = Q()
                    for token in tokens:
                        q_filter &= (
                            Q(student__user__first_name__icontains=token)
                            | Q(student__user__last_name__icontains=token)
                            | Q(student__admission_number__icontains=token)
                        )
                    scores = scores.filter(q_filter)

                # Build the students × subjects matrix
                matrix = {}
                student_order = {}
                for score in scores:
                    matrix[(score.student_id, score.subject_id)] = score
                    student_order.setdefault(score.student_id, score.student.admission_number)

                student_ids = sorted(student_order, key=lambda sid: student_order[sid])
                subjects = list({score.subject for score in scores})
                subjects.sort(key=lambda s: s.name)

                subject_pending = {}
                for subject in subjects:
                    subject_pending[subject.id] = sum(
                        1 for score in scores
                        if score.subject_id == subject.id
                        and score.moderation_status == Score.MODERATION_PENDING
                    )
                subjects = [
                    {
                        'subject': s,
                        'pending_count': subject_pending[s.id],
                        'teacher': ' / '.join(teacher_by_subject.get(s.id, [])) or None,
                    }
                    for s in subjects
                ]

                rows = []
                for student_id in student_ids:
                    student_scores = [s for s in scores if s.student_id == student_id]
                    student = student_scores[0].student
                    cells = []
                    pending_count = 0
                    for subject in [s['subject'] for s in subjects]:
                        score = matrix.get((student_id, subject.id))
                        if score and score.moderation_status == Score.MODERATION_PENDING:
                            pending_count += 1
                        cells.append(score)
                    rows.append({
                        'student': student,
                        'cells': cells,
                        'pending_count': pending_count,
                    })
            else:
                # Show summary per class
                assignments = TeacherAssignment.objects.filter(
                    school_class__in=classes,
                    session=selected_term.session,
                ).select_related('teacher')
                teachers_by_class = {}
                for assignment in assignments:
                    teachers_by_class.setdefault(
                        assignment.school_class_id, []
                    ).append(assignment.teacher.get_full_name() or assignment.teacher.username)

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
                        'teachers': sorted(set(teachers_by_class.get(cls.pk, []))),
                    })

        template = (
            'school_admin/_review_results.html'
            if request.headers.get('HX-Request')
            else 'school_admin/review_results.html'
        )
        return render(request, template, {
            'terms': terms,
            'classes': classes,
            'selected_term': selected_term,
            'selected_class': selected_class,
            'class_summary': class_summary,
            'matrix': rows if selected_class else [],
            'subjects': subjects,
            'subject_options': subject_options,
            'selected_subject_id': int(subject_id) if subject_id.isdigit() else None,
            'selected_subject_name': (
                next((s.name for s in subject_options if str(s.pk) == subject_id), None)
                if subject_id.isdigit() else None
            ),
            'class_teachers': class_teachers if selected_class else [],
            'subject_teacher': (
                ' / '.join(teacher_by_subject.get(int(subject_id), [])) or None
                if subject_id.isdigit() else None
            ),
            'status_filter': status_filter if status_filter in ('all', 'pending', 'approved', 'rejected') else 'all',
            'q': q,
        })

    def post(self, request):
        school = request.school
        score_id = request.POST.get('score_id')
        action = request.POST.get('action')
        term_id = request.POST.get('term_id')
        class_id = request.POST.get('class_id')
        subject_id = request.POST.get('subject_id')
        student_id = request.POST.get('student_id')

        def _redirect():
            redirect_url = reverse('school_admin:review_results')
            params = {}
            if term_id:
                params['term_id'] = term_id
            if class_id:
                params['class_id'] = class_id
            if subject_id:
                params['subject_id'] = subject_id
            if request.POST.get('status'):
                params['status'] = request.POST['status']
            if request.POST.get('q'):
                params['q'] = request.POST['q']
            return redirect(f"{redirect_url}?{urlencode(params)}" if params else redirect_url)

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

        elif action in ('approve_subject', 'reject_subject'):
            if term_id and class_id and subject_id:
                updated = Score.objects.filter(
                    school=school,
                    term_id=term_id,
                    subject_id=subject_id,
                    student__enrollments__school_class_id=class_id,
                    student__enrollments__is_current=True,
                    moderation_status=Score.MODERATION_PENDING,
                ).update(
                    moderation_status=(
                        Score.MODERATION_APPROVED if action == 'approve_subject'
                        else Score.MODERATION_REJECTED
                    ),
                    moderated_by=request.user,
                    moderated_at=timezone.now(),
                )
                verb = 'approved' if action == 'approve_subject' else 'rejected'
                messages.success(request, f'{updated} pending scores {verb} for this subject.')
            else:
                messages.error(request, 'Missing term, class or subject information.')

        elif action in ('approve_student', 'reject_student'):
            if term_id and class_id and student_id:
                updated = Score.objects.filter(
                    school=school,
                    term_id=term_id,
                    student_id=student_id,
                    student__enrollments__school_class_id=class_id,
                    student__enrollments__is_current=True,
                    moderation_status=Score.MODERATION_PENDING,
                ).update(
                    moderation_status=(
                        Score.MODERATION_APPROVED if action == 'approve_student'
                        else Score.MODERATION_REJECTED
                    ),
                    moderated_by=request.user,
                    moderated_at=timezone.now(),
                )
                verb = 'approved' if action == 'approve_student' else 'rejected'
                messages.success(request, f'{updated} pending scores {verb} for this student.')
            else:
                messages.error(request, 'Missing term, class or student information.')

        else:
            messages.error(request, 'Invalid request.')

        return _redirect()
