from decimal import Decimal
from django.conf import settings
from django.db.models import Q, Prefetch
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse                                       
from django.views.generic.base import View
from django.contrib import messages

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from core.models import Term
from students.models import Student, StudentGuardianLink, ClassEnrollment
from fees.checkout import get_checkout_options, current_term
from fees.models import Invoice, Payment
from fees.selectors import owed_term_ids as owed_term_ids_for
from fees.selectors import owed_term_ids_from

from academics.models import Score, TermResult, TeacherAssignment
from lessons.models import LessonEnrollment


def _parent_portal_context(request) -> dict:
    """Shared context for the parent dashboard and children list pages."""
    guardian_links = StudentGuardianLink.objects.filter(
        guardian=request.user,
    ).select_related(
        'student__user',
    ).prefetch_related(
        'student__enrollments__school_class',
        'student__enrollments__session',
    )

    current_term = Term.objects.filter(
        school=request.school, is_current=True,
    ).first()

    student_ids = [link.student_id for link in guardian_links]
    invoices_qs = Invoice.objects.filter(
        student_id__in=student_ids,
    ).select_related('term', 'student', 'student__user').prefetch_related('payments')
    invoices_by_student = {}
    for inv in invoices_qs:
        invoices_by_student.setdefault(inv.student_id, []).append(inv)

    # Term ids with an unpaid balance — those results stay locked for the child.
    owed_by_student = {
        student_id: owed_term_ids_from(invoices)
        for student_id, invoices in invoices_by_student.items()
    }

    if current_term and current_term.results_published:
        term_results = {
            tr.student_id: tr
            for tr in TermResult.objects.filter(
                student_id__in=student_ids,
                term=current_term,
            )
        }
    else:
        term_results = {}

    children_data = []
    for link in guardian_links:
        student = link.student

        # Current enrollment
        enrollment = student.enrollments.filter(is_current=True).first()

        # Academic performance for current term
        term_result = term_results.get(student.pk)
        results_locked = bool(
            current_term and student.pk in owed_by_student
            and current_term.pk in owed_by_student[student.pk]
        )
        if results_locked:
            term_result = None

        # Total amount owed
        invoices = invoices_by_student.get(student.pk, [])
        unpaid_invoices = [inv for inv in invoices if inv.balance > 0]
        total_owed = sum(inv.balance for inv in unpaid_invoices)
        unpaid_count = len(unpaid_invoices)

        children_data.append({
            'student': student,
            'enrollment': enrollment,
            'term_result': term_result,
            'results_locked': results_locked,
            'total_owed': total_owed,
            'unpaid_count': unpaid_count,
        })

    # Summary stats for dashboard
    total_children = len(children_data)
    total_owed_all = sum(c['total_owed'] for c in children_data)
    unpaid_invoices = sum(c['unpaid_count'] for c in children_data)

    # Results status + average across children
    results_published = bool(
        current_term and current_term.results_published
    )
    averages = [
        c['term_result'].average
        for c in children_data
        if c['term_result'] and c['term_result'].average
    ]
    children_average = (
        round(sum(averages) / len(averages), 1) if averages else None
    )

    published_terms_count = 0
    if children_data:
        child_ids = [c['student'].pk for c in children_data]
        published_terms_count = Term.objects.filter(
            school=request.school,
            results_published=True,
            scores__student_id__in=child_ids,
        ).distinct().count()

    # Fees owed per child (chart)
    child_chart_labels = [
        c['student'].user.get_full_name() or c['student'].user.username
        for c in children_data
    ]
    child_chart_values = [float(c['total_owed']) for c in children_data]

    return {
        'children_data': children_data,
        'total_children': total_children,
        'total_owed_all': total_owed_all,
        'unpaid_invoices': unpaid_invoices,
        'results_published': results_published,
        'children_average': children_average,
        'published_terms_count': published_terms_count,
        'child_chart_labels': child_chart_labels,
        'child_chart_values': child_chart_values,
        'current_term': current_term,
    }


class ParentDashboardView(RoleRequiredMixin, View):
    """Parent landing page — summary stats, quick actions, children snapshot."""

    allowed_roles = [Roles.PARENT]

    def get(self, request):
        return render(
            request,
            'students/parent/dashboard.html',
            _parent_portal_context(request),
        )


class ParentChildrenListView(RoleRequiredMixin, View):
    """Full children list with academic and fee detail per child."""

    allowed_roles = [Roles.PARENT]

    def get(self, request):
        return render(
            request,
            'students/parent/children_list.html',
            _parent_portal_context(request),
        )


class ParentChildDetailView(RoleRequiredMixin, View):
    """Deep dive for a single child — academic trend, invoices, scores, booklets."""

    allowed_roles = [Roles.PARENT]

    def get(self, request, pk):
        guardian_link = get_object_or_404(
            StudentGuardianLink, guardian=request.user, student_id=pk,
        )
        student = guardian_link.student

        current_enrollment = ClassEnrollment.objects.filter(
            student=student, is_current=True,
        ).select_related('school_class', 'session').first()

        current_term = Term.objects.filter(
            school=request.school, is_current=True,
        ).first()

        invoices = Invoice.objects.filter(
            student=student,
        ).prefetch_related('payments').order_by('-term__start_date')

        scores = Score.objects.visible_to_user(request.user).filter(
            student=student,
        ).select_related('subject', 'term').order_by('subject__name')

        published_term_qs = Term.for_current_session(request.school).filter(
            results_published=True, scores__student=student,
        ).distinct()

        # Terms with outstanding fees — results for those stay locked.
        # balance is a computed property (total − confirmed payments), so it
        # is evaluated per invoice, in memory, against the prefetched list.
        owed_term_ids = owed_term_ids_from(invoices)
        published_terms = [
            term for term in published_term_qs if term.pk not in owed_term_ids
        ]
        locked_terms = [
            term for term in published_term_qs if term.pk in owed_term_ids
        ]

        # Academic trend — TermResults across all published terms
        academic_trend = TermResult.objects.filter(
            student=student, term__results_published=True,
        ).exclude(term_id__in=owed_term_ids).select_related('term', 'term__session').order_by('term__start_date')

        # Current term summary
        current_term_result = None
        if current_term:
            if current_term.pk in owed_term_ids:
                current_term_result = None
            else:
                current_term_result = TermResult.objects.filter(
                    student=student, term=current_term,
                ).first()

        # Fee summary
        unpaid_invoices = [inv for inv in invoices if inv.balance > 0]
        total_owed = sum(inv.balance for inv in unpaid_invoices)
        unpaid_count = len(unpaid_invoices)

        return render(request, 'students/parent/child_detail.html', {
            'student': student,
            'current_enrollment': current_enrollment,
            'current_term': current_term,
            'invoices': invoices,
            'scores': scores,
            'published_terms': published_terms,
            'academic_trend': academic_trend,
            'current_term_result': current_term_result,
            'current_term_locked': bool(
                current_term and current_term.pk in owed_term_ids
            ),
            'total_owed': total_owed,
            'unpaid_count': unpaid_count,
        })


class ParentInvoicesView(RoleRequiredMixin, View):
    """All invoices across all children for this parent."""

    allowed_roles = [Roles.PARENT]

    def get(self, request):
        student_ids = StudentGuardianLink.objects.filter(
            guardian=request.user,
        ).values_list('student_id', flat=True)

        invoices = Invoice.objects.filter(
            student_id__in=student_ids,
        ).select_related('student', 'student__user', 'term').order_by('-term__start_date')

        # Filter by child if requested
        child_filter = request.GET.get('child')
        if child_filter:
            invoices = invoices.filter(student_id=child_filter)

        # Summary
        total_owed = sum(inv.balance for inv in invoices)

        # Children for filter dropdown
        children = Student.objects.filter(
            pk__in=student_ids,
        ).select_related('user')

        return render(request, 'students/parent/invoices_list.html', {
            'invoices': invoices,
            'total_owed': total_owed,
            'children': children,
            'child_filter': child_filter,
        })


class ParentInvoiceDetailView(RoleRequiredMixin, View):
    """Single invoice with line items and payment history."""

    allowed_roles = [Roles.PARENT]

    def get(self, request, pk):
        invoice = get_object_or_404(Invoice, pk=pk, school=request.school)

        # Guardian scope check
        if not StudentGuardianLink.objects.filter(
            student=invoice.student, guardian=request.user,
        ).exists():
            messages.error(request, 'You are not authorized to view this invoice.')
            return redirect('parent-children')

        payments = invoice.payments.all().order_by('-paid_on')
        line_items = invoice.line_items.all().select_related('category')

        return render(request, 'students/parent/invoice_detail.html', {
            'invoice': invoice,
            'payments': payments,
            'line_items': line_items,
        })


class ParentExtraLessonsView(RoleRequiredMixin, View):
    """Parent view of their children's Extra Lessons enrollments + balances.

    Read-only: admin remains the source of truth for registration. A parent
    sees only enrollments linked to a child they are guardian for (the
    enrollment's ``student`` FK matches one of their children). External
    walk-in enrollments are never shown because they have no linked student.
    """

    allowed_roles = [Roles.PARENT]

    def get(self, request):
        student_ids = StudentGuardianLink.objects.filter(
            guardian=request.user,
        ).values_list('student_id', flat=True)

        # Guard: no child enrolled for Extra Lessons → send the parent back to
        # their children list. Mirrors the booklet-lock redirect pattern; the
        # nav already hides the tab, this is the backstop.
        if not LessonEnrollment.objects.filter(
            school=request.school, student_id__in=student_ids,
        ).exclude(status=LessonEnrollment.Status.CANCELLED).exists():
            messages.info(
                request,
                'None of your children are enrolled in extra lessons yet.',
            )
            return redirect('parent-children')

        enrollments = (
            LessonEnrollment.objects
            .filter(school=request.school, student_id__in=student_ids)
            .exclude(status=LessonEnrollment.Status.CANCELLED)
            .select_related(
                'lesson_class', 'lesson_class__period',
                'student', 'student__user',
            )
            .prefetch_related('payments')
            .order_by('student__user__last_name', '-registered_on')
        )

        children = {}
        total_outstanding = Decimal('0.00')
        for e in enrollments:
            balance = max(e.fee_amount - e.amount_paid, Decimal('0.00'))
            e.balance = balance
            if balance > 0:
                total_outstanding += balance
            child = children.setdefault(e.student_id, {
                'student': e.student,
                'enrollments': [],
            })
            child['enrollments'].append(e)

        return render(request, 'students/parent/extra_lessons.html', {
            'children': list(children.values()),
            'total_outstanding': total_outstanding,
            'enrollment_count': enrollments.count(),
        })


class MakePaymentView(RoleRequiredMixin, View):
    """Pay page — one view serving both the parent and student portals.

    PARENT  (/parent/pay/): lists all linked children with their invoices and
            outstanding balances; recent confirmed payments across children.
    STUDENT (/student/pay/): lists the student's own invoices and balance.

    The page renders 'students/make_payment.html' once, with role-conditional
    context. Payment initiation itself happens via fees:initiate-payment; this
    page just presents the data and the forms (and the Paystack return state).
    Cart data (``checkouts_by_child``, ``bank_details``) is now passed so the
    template can render fee options and the bank-transfer reveal.
    """
    allowed_roles = [Roles.PARENT, Roles.STUDENT]

    def get(self, request):
        role = request.user.role
        context = {
            'role': role,
            'reference': request.GET.get('reference'),
        }

        if role == Roles.PARENT:
            children = Student.objects.filter(
                guardian_links__guardian=request.user,
            ).select_related('user').distinct()
            context['children'] = children
            invoices = Invoice.objects.filter(student__in=children)
        else:
            student = request.user.student_profile
            children = Student.objects.none()
            context['children'] = children
            context['student'] = student
            invoices = Invoice.objects.filter(student=student)

        # Prefetch payments that count toward the balance so invoice.balance/status
        # don't N+1: only CONFIRMED payments reduce the balance. Pending bank
        # transfers stay visible in the recent list but never count until confirmed.
        balance_status_q = Q(status=Payment.Status.CONFIRMED)
        # Recent payments still show pending bank transfers (pending approval).
        visible_status_q = balance_status_q | Q(
            status=Payment.Status.PENDING, method=Payment.Method.BANK_TRANSFER,
        )
        invoices = invoices.select_related(
            'term', 'student', 'student__user',
        ).prefetch_related(Prefetch(
            'payments',
            queryset=Payment.objects.filter(balance_status_q),
        ))

        invoices_by_child = {}
        total_owed = Decimal('0.00')
        unpaid_invoices_count = 0
        for inv in invoices:
            invoices_by_child.setdefault(inv.student_id, []).append(inv)
            if inv.balance > 0:
                total_owed += inv.balance
                unpaid_invoices_count += 1

        # Fully paid when the student/children have invoices and owe nothing.
        fully_paid = bool(invoices_by_child) and total_owed == 0

        totals_by_child = {
            child_id: sum(
                (inv.balance for inv in inv_list if inv.balance > 0),
                Decimal('0.00'),
            )
            for child_id, inv_list in invoices_by_child.items()
        }

        # Cart data — checkout options per child (or the single student). The
        # term is the latest unpaid invoice's term (carried-over debt) when one
        # exists, otherwise the school's current term.
        checkouts_by_child = {}
        checkout_term = current_term(request.school)
        checkout_students = list(children) if role == Roles.PARENT else [student]
        for child in checkout_students:
            unpaid_terms = [
                inv.term
                for inv in invoices_by_child.get(child.pk, [])
                if inv.balance > 0 and inv.term
            ]
            term = max(
                unpaid_terms, key=lambda t: t.start_date, default=checkout_term,
            )
            if term is None:
                continue
            checkouts_by_child[child.pk] = get_checkout_options(child, term)

        # A child has something to pay for when they carry an outstanding balance
        # OR have a selectable (unbilled, unpaid) category in their cart. When no
        # child has anything payable, the payment section is greyed out.
        can_pay_by_child = {}
        for child in checkout_students:
            co = checkouts_by_child.get(child.pk)
            can_pay = False
            if co is not None:
                if co.outstanding is not None:
                    can_pay = True
                else:
                    payable = [
                        o for o in co.extras if not o.billed
                    ]
                    if co.next_term is not None:
                        payable += [
                            o for o in co.next_term.options if not o.billed
                        ]
                    if payable:
                        can_pay = True
            can_pay_by_child[child.pk] = can_pay
        any_payable = any(can_pay_by_child.values())

        # Bank transfer details for the "I've Transferred" reveal. Comes from
        # the school's settings; hidden when no account number has been entered.
        school = request.school
        bank_details = None
        if school.account_number:
            bank_details = {
                'bank': school.bank_name,
                'account_name': school.account_name,
                'account_number': school.account_number,
            }

        # Recent confirmed + pending bank-transfer payments — pending transfers
        # show immediately after submission. Invoice may be None (invoice-less
        # payments); templates should fall back to payment.description.
        if role == Roles.PARENT:
            recent_qs = Payment.objects.filter(
                school=request.school,
            ).filter(
                visible_status_q
                & (Q(student__in=children) | Q(invoice__student__in=children)),
            )
        else:
            recent_qs = Payment.objects.filter(
                school=request.school,
            ).filter(
                visible_status_q
                & (Q(student=student) | Q(invoice__student=student)),
            )
        recent_payments = recent_qs.select_related(
            'student', 'student__user',
            'invoice', 'invoice__student', 'invoice__student__user',
        )[:5]

        context.update({
            'invoices_by_child': invoices_by_child,
            'totals_by_child': totals_by_child,
            'total_owed': total_owed,
            'fully_paid': fully_paid,
            'unpaid_invoices_count': unpaid_invoices_count,
            'recent_payments': recent_payments,
            'checkouts_by_child': checkouts_by_child,
            'can_pay_by_child': can_pay_by_child,
            'any_payable': any_payable,
            'bank_details': bank_details,
            'paystack_enabled': bool(
                getattr(settings, 'PAYSTACK_SECRET_KEY', '')
                and getattr(settings, 'PAYSTACK_PUBLIC_KEY', '')
            ),
        })
        return render(request, 'students/make_payment.html', context)


class StudentOverviewView(RoleRequiredMixin, View):
    """Student dashboard — KPIs, results banner, chart, invoices."""

    allowed_roles = [Roles.STUDENT]

    def get(self, request):
        enrollment = ClassEnrollment.objects.filter(
            student__user=request.user,
            is_current=True,
        ).select_related('school_class', 'session').first()

        invoices = Invoice.objects.filter(
            student__user=request.user,
        ).select_related('term').prefetch_related('payments')

        scores = Score.objects.visible_to_user(request.user).filter(
            student__user=request.user,
        ).select_related('subject', 'term').order_by('subject__name')

        # Published terms with scores for this student
        published_terms = Term.for_current_session(request.school).filter(
            results_published=True,
            scores__student__user=request.user,
        ).distinct()

        # A term's booklet stays locked while the student owes fees for it.
        # balance is a computed property (total − confirmed payments), so
        # it must be evaluated per invoice, against the prefetched list.
        owed_term_ids = owed_term_ids_from(invoices)
        booklet_terms = [
            {'term': term, 'locked': term.pk in owed_term_ids}
            for term in published_terms
        ]

        current_term = Term.objects.filter(
            school=request.school, is_current=True,
        ).first()

        # Current term result (only shown once published)
        term_result = None
        results_locked = False
        if current_term and current_term.results_published:
            if Invoice.owes_for_term(request.user.student_profile, current_term):
                results_locked = True
            else:
                term_result = TermResult.objects.filter(
                    student__user=request.user, term=current_term,
                ).first()

        # Fee summary
        unpaid_invoices = [inv for inv in invoices if inv.balance > 0]
        outstanding = sum(inv.balance for inv in unpaid_invoices)
        unpaid_count = len(unpaid_invoices)

        # Subject count for current term
        subject_count = 0
        if enrollment and current_term and enrollment.session_id == current_term.session_id:
            subject_count = TeacherAssignment.objects.filter(
                school=request.school,
                school_class=enrollment.school_class,
                session=current_term.session,
            ).values('subject_id').distinct().count()

        # Last confirmed payment
        last_payment = Payment.objects.filter(
            school=request.school,
            student__user=request.user,
            status=Payment.Status.CONFIRMED,
        ).order_by('-paid_on').first()

        # One-time success toast when fees just became fully paid: fires only
        # when the balance transitions from owing → paid (once), so students
        # who were always paid don't get a spur-of-the-moment confirmation.
        prev_owing = request.session.get('_fees_prev_owing', False)
        if outstanding == 0:
            if prev_owing:
                messages.success(request, 'All fees paid. Nice work!')
            request.session['_fees_prev_owing'] = False
        else:
            request.session['_fees_prev_owing'] = True

        return render(request, 'students/student/overview.html', {
            'enrollment': enrollment,
            'invoices': invoices,
            'scores': scores,
            'booklet_terms': booklet_terms,
            'current_term': current_term,
            'term_result': term_result,
            'results_locked': results_locked,
            'outstanding': outstanding,
            'unpaid_count': unpaid_count,
            'subject_count': subject_count,
            'last_payment': last_payment,
        })


class StudentExtraLessonsView(RoleRequiredMixin, View):
    """Simple read-only view of the student's own Extra Lessons enrollments.

    Mirrors the parent view but scoped to the logged-in student. Admin stays
    the source of truth, so this is display-only.
    """

    allowed_roles = [Roles.STUDENT]

    def get(self, request):
        student = request.user.student_profile

        # Guard: not registered for Extra Lessons → back to the dashboard.
        # The nav already hides the tab; this is the backstop redirect.
        if not LessonEnrollment.objects.filter(
            school=request.school, student=student,
        ).exclude(status=LessonEnrollment.Status.CANCELLED).exists():
            messages.info(
                request, 'You have no extra lessons enrollments yet.',
            )
            return redirect('student-overview')

        enrollments = (
            LessonEnrollment.objects
            .filter(school=request.school, student=student)
            .exclude(status=LessonEnrollment.Status.CANCELLED)
            .select_related('lesson_class', 'lesson_class__period')
            .prefetch_related('payments')
            .order_by('-registered_on')
        )

        total_outstanding = Decimal('0.00')
        for e in enrollments:
            balance = max(e.fee_amount - e.amount_paid, Decimal('0.00'))
            e.balance = balance
            if balance > 0:
                total_outstanding += balance

        return render(request, 'students/student/extra_lessons.html', {
            'enrollments': enrollments,
            'total_outstanding': total_outstanding,
        })


class StudentResultBookletView(RoleRequiredMixin, View):
    """Display result booklet inline for a student."""

    allowed_roles = [Roles.STUDENT]

    def get(self, request, term_id):
        student = request.user.student_profile
        term = get_object_or_404(Term, pk=term_id, school=request.school, results_published=True)

        if Invoice.owes_for_term(student, term):
            messages.error(
                request,
                f'Results for {term.name} are locked until outstanding fees '
                'for that term are cleared.',
            )
            return redirect('student-overview')

        from academics.booklet import build_booklet_context

        context, enrollment = build_booklet_context(student, term, request.school)
        if not enrollment:
            messages.error(request, 'No enrollment found for this term.')
            return redirect('student-overview')

        context['booklet_back_url'] = reverse('student-overview')
        return render(request, 'students/result_booklet.html', context)


class ParentChildResultBookletView(RoleRequiredMixin, View):
    """Display result booklet inline for a child (parent portal)."""

    allowed_roles = [Roles.PARENT]

    def get(self, request, child_pk, term_id):
        child = get_object_or_404(Student, school=request.school, pk=child_pk)
        if not StudentGuardianLink.objects.filter(student=child, guardian=request.user).exists():
            messages.error(request, 'You are not linked to this student.')
            return redirect('parent-children')

        term = get_object_or_404(Term, pk=term_id, school=request.school, results_published=True)

        if Invoice.owes_for_term(child, term):
            messages.error(
                request,
                f'Results for {term.name} for {child.user.get_full_name() or child.user.username} '
                'are locked until outstanding fees for that term are cleared.',
            )
            return redirect('parent-child-detail', pk=child_pk)

        from academics.booklet import build_booklet_context

        context, enrollment = build_booklet_context(child, term, request.school)
        if not enrollment:
            messages.error(request, 'No enrollment found for this term.')
            return redirect('parent-child-detail', pk=child_pk)

        context['booklet_back_url'] = reverse('parent-child-detail', kwargs={'pk': child_pk})
        return render(request, 'students/result_booklet.html', context)


class StudentResultsHistoryView(RoleRequiredMixin, View):
    """List all published terms with results for the student."""

    allowed_roles = [Roles.STUDENT]

    def get(self, request):
        student = request.user.student_profile

        published_terms = Term.objects.filter(
            school=request.school,
            results_published=True,
            scores__student=student,
        ).distinct().order_by('-start_date').select_related('session')

        owed_term_ids = owed_term_ids_for(student)

        results = []
        locked_terms = []
        for term in published_terms:
            if term.pk in owed_term_ids:
                locked_terms.append({'term': term})
                continue
            enrollment = ClassEnrollment.objects.filter(
                student=student, session=term.session
            ).select_related('school_class').first()
            results.append({
                'term': term,
                'class_name': enrollment.school_class.name if enrollment else '—',
            })

        return render(request, 'students/student/results_history.html', {
            'results': results,
            'locked_terms': locked_terms,
        })


class StudentSubjectsView(RoleRequiredMixin, View):
    """Current-term subject list for the student.

    Subjects come from the TeacherAssignments for the class the student is
    enrolled in, filtered to the session of the current term.
    """

    allowed_roles = [Roles.STUDENT]

    def get(self, request):
        student = request.user.student_profile

        enrollment = ClassEnrollment.objects.filter(
            student=student, is_current=True,
        ).select_related('school_class', 'session').first()

        current_term = Term.objects.filter(
            school=request.school, is_current=True,
        ).first()

        subjects = []
        if (
            enrollment and current_term
            and enrollment.session_id == current_term.session_id
        ):
            assignments = TeacherAssignment.objects.filter(
                school=request.school,
                school_class=enrollment.school_class,
                session=current_term.session,
            ).select_related('subject', 'teacher').order_by('subject__name')

            by_subject = {}
            for assignment in assignments:
                group = by_subject.setdefault(
                    assignment.subject_id,
                    {'subject': assignment.subject, 'teachers': []},
                )
                group['teachers'].append(
                    assignment.teacher.get_full_name() or assignment.teacher.username
                )

            subjects = sorted(by_subject.values(), key=lambda g: g['subject'].name)

        return render(request, 'students/student/subjects.html', {
            'subjects': subjects,
            'enrollment': enrollment,
            'term': current_term,
        })


class StudentSelfPasswordChangeView(RoleRequiredMixin, View):
    """Student changes their own password."""

    allowed_roles = [Roles.STUDENT]

    def get(self, request):
        return render(request, 'students/student/password_change.html')

    def post(self, request):
        current_password = request.POST.get('current_password', '').strip()
        new_password = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()

        if not current_password:
            messages.error(request, 'Please enter your current password.')
            return redirect('student-password-change')

        if not request.user.check_password(current_password):
            messages.error(request, 'Current password is incorrect.')
            return redirect('student-password-change')

        if not new_password:
            messages.error(request, 'Please enter a new password.')
            return redirect('student-password-change')

        if new_password != confirm_password:
            messages.error(request, 'New passwords do not match.')
            return redirect('student-password-change')

        if len(new_password) < 6:
            messages.error(request, 'Password must be at least 6 characters.')
            return redirect('student-password-change')

        request.user.set_password(new_password)
        request.user.save()
        messages.success(request, 'Password changed successfully.')
        return redirect('student-overview')
