from decimal import Decimal
from django.db.models import Sum, Q, Prefetch
from django.shortcuts import get_object_or_404, render, redirect
from django.views.generic.base import View
from django.contrib import messages

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from core.models import Term
from students.models import Student, StudentGuardianLink, ClassEnrollment
from fees.checkout import get_checkout_options, current_term
from fees.models import Invoice, Payment

from academics.models import Score, TermResult


class ParentChildrenListView(RoleRequiredMixin, View):
    """Dashboard overview + children list with academic and fee data."""

    allowed_roles = [Roles.PARENT]

    def get(self, request):
        guardian_links = StudentGuardianLink.objects.filter(
            guardian=request.user,
        ).select_related('student', 'student__user')

        current_term = Term.objects.filter(
            school=request.school, is_current=True,
        ).first()

        children_data = []
        for link in guardian_links:
            student = link.student

            # Current enrollment
            enrollment = ClassEnrollment.objects.filter(
                student=student, is_current=True,
            ).select_related('school_class', 'session').first()

            # Academic performance for current term
            term_result = None
            if current_term and current_term.results_published:
                term_result = TermResult.objects.filter(
                    student=student, term=current_term,
                ).first()

            # Total amount owed
            invoices = Invoice.objects.filter(
                student=student,
            )
            unpaid_invoices = [inv for inv in invoices if inv.balance > 0]
            total_owed = sum(inv.balance for inv in unpaid_invoices)
            unpaid_count = len(unpaid_invoices)

            children_data.append({
                'student': student,
                'enrollment': enrollment,
                'term_result': term_result,
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

        return render(request, 'students/parent/children_list.html', {
            'children_data': children_data,
            'total_children': total_children,
            'total_owed_all': total_owed_all,
            'unpaid_invoices': unpaid_invoices,
            'results_published': results_published,
            'children_average': children_average,
            'published_terms_count': published_terms_count,
            'child_chart_labels': child_chart_labels,
            'child_chart_values': child_chart_values,
        })


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

        published_terms = Term.objects.filter(
            school=request.school, results_published=True, scores__student=student,
        ).distinct().order_by('-start_date')

        # Academic trend — TermResults across all published terms
        academic_trend = TermResult.objects.filter(
            student=student, term__results_published=True,
        ).select_related('term', 'term__session').order_by('term__start_date')

        # Current term summary
        current_term_result = None
        if current_term:
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

        # Prefetch confirmed payments so invoice.balance/status don't N+1
        invoices = invoices.select_related(
            'term', 'student', 'student__user',
        ).prefetch_related(Prefetch(
            'payments',
            queryset=Payment.objects.filter(status=Payment.Status.CONFIRMED),
        ))

        invoices_by_child = {}
        total_owed = Decimal('0.00')
        unpaid_invoices_count = 0
        for inv in invoices:
            invoices_by_child.setdefault(inv.student_id, []).append(inv)
            if inv.balance > 0:
                total_owed += inv.balance
                unpaid_invoices_count += 1

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

        # Bank transfer details for the "I've Transferred" reveal.
        bank_details = {
            'bank': 'First Bank',
            'account_name': 'Grace House School System',
            'account_number': '0000000000',
        }

        # Recent confirmed + pending bank-transfer payments — pending transfers
        # show immediately after submission. Invoice may be None (invoice-less
        # payments); templates should fall back to payment.description.
        visible_status_q = Q(status=Payment.Status.CONFIRMED) | Q(
            status=Payment.Status.PENDING, method=Payment.Method.BANK_TRANSFER,
        )
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
            'unpaid_invoices_count': unpaid_invoices_count,
            'recent_payments': recent_payments,
            'checkouts_by_child': checkouts_by_child,
            'bank_details': bank_details,
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
        published_terms = Term.objects.filter(
            school=request.school,
            results_published=True,
            scores__student__user=request.user,
        ).distinct().order_by('-start_date')

        current_term = Term.objects.filter(
            school=request.school, is_current=True,
        ).first()

        # Current term result (only shown once published)
        term_result = None
        if current_term and current_term.results_published:
            term_result = TermResult.objects.filter(
                student__user=request.user, term=current_term,
            ).first()

        # Fee summary
        unpaid_invoices = [inv for inv in invoices if inv.balance > 0]
        outstanding = sum(inv.balance for inv in unpaid_invoices)
        unpaid_count = len(unpaid_invoices)

        # Academic trend — average per published term (chart)
        term_chart_labels = []
        term_chart_values = []
        for tr in TermResult.objects.filter(
            student__user=request.user, term__results_published=True,
        ).select_related('term', 'term__session').order_by('term__start_date'):
            term_chart_labels.append(tr.term.session.name)
            term_chart_values.append(float(tr.average))

        return render(request, 'students/student/overview.html', {
            'enrollment': enrollment,
            'invoices': invoices,
            'scores': scores,
            'published_terms': published_terms,
            'current_term': current_term,
            'term_result': term_result,
            'outstanding': outstanding,
            'unpaid_count': unpaid_count,
            'term_chart_labels': term_chart_labels,
            'term_chart_values': term_chart_values,
        })


class StudentResultBookletView(RoleRequiredMixin, View):
    """Display result booklet inline for a student."""

    allowed_roles = [Roles.STUDENT]

    def get(self, request, term_id):
        student = request.user.student_profile
        term = get_object_or_404(Term, pk=term_id, school=request.school, results_published=True)

        from academics.models import Score, GradeScale, TermResult

        enrollment = ClassEnrollment.objects.filter(
            student=student, session=term.session
        ).select_related('school_class').first()

        if not enrollment:
            messages.error(request, 'No enrollment found for this term.')
            return redirect('student-overview')

        scores = Score.objects.filter(
            student=student, term=term
        ).select_related('subject').order_by('subject__name')

        term_result = TermResult.objects.filter(
            student=student, term=term
        ).first()

        grade_scale = GradeScale.objects.filter(school=request.school).order_by('-min_score')

        score_data = []
        for score in scores:
            grade_obj = GradeScale.objects.filter(
                school=request.school, label=GradeScale.get_grade(request.school, score.total_score)
            ).first() if GradeScale.get_grade(request.school, score.total_score) else None
            score_data.append({
                'subject': score.subject.name,
                'test_1': score.test_1 or 0,
                'test_2': score.test_2 or 0,
                'test_3': score.test_3 or 0,
                'exam': score.exam_score or 0,
                'total': score.total_score,
                'grade': GradeScale.get_grade(request.school, score.total_score) or '-',
                'position': score.position,
                'remark': grade_obj.remark if grade_obj else '-',
            })

        class_size = ClassEnrollment.objects.filter(
            school_class=enrollment.school_class, session=term.session, is_current=True
        ).count()

        context = {
            'student': student,
            'term': term,
            'enrollment': enrollment,
            'school_class': enrollment.school_class,
            'scores': score_data,
            'term_result': term_result,
            'grade_scale': grade_scale,
            'class_size': class_size,
            'school': request.school,
        }
        return render(request, 'students/student/result_booklet.html', context)


class StudentResultDownloadView(RoleRequiredMixin, View):
    """Download result booklet PDF for a student."""

    allowed_roles = [Roles.STUDENT]

    def get(self, request, term_id):
        from academics.pdf import render_result_booklet_pdf

        student = request.user.student_profile
        term = get_object_or_404(Term, pk=term_id, school=request.school, results_published=True)

        response = render_result_booklet_pdf(student, term)
        if response is None:
            messages.error(request, 'No enrollment found for this term.')
            return redirect('student-overview')
        return response


class ParentChildResultBookletView(RoleRequiredMixin, View):
    """Display result booklet inline for a child (parent portal)."""

    allowed_roles = [Roles.PARENT]

    def get(self, request, child_pk, term_id):
        child = get_object_or_404(Student, school=request.school, pk=child_pk)
        if not StudentGuardianLink.objects.filter(student=child, guardian=request.user).exists():
            messages.error(request, 'You are not linked to this student.')
            return redirect('parent-children')

        term = get_object_or_404(Term, pk=term_id, school=request.school, results_published=True)

        from academics.models import Score, GradeScale, TermResult

        enrollment = ClassEnrollment.objects.filter(
            student=child, session=term.session
        ).select_related('school_class').first()

        if not enrollment:
            messages.error(request, 'No enrollment found for this term.')
            return redirect('parent-child-detail', pk=child_pk)

        scores = Score.objects.filter(
            student=child, term=term
        ).select_related('subject').order_by('subject__name')

        term_result = TermResult.objects.filter(
            student=child, term=term
        ).first()

        grade_scale = GradeScale.objects.filter(school=request.school).order_by('-min_score')

        score_data = []
        for score in scores:
            grade_obj = GradeScale.objects.filter(
                school=request.school, label=GradeScale.get_grade(request.school, score.total_score)
            ).first() if GradeScale.get_grade(request.school, score.total_score) else None
            score_data.append({
                'subject': score.subject.name,
                'test_1': score.test_1 or 0,
                'test_2': score.test_2 or 0,
                'test_3': score.test_3 or 0,
                'exam': score.exam_score or 0,
                'total': score.total_score,
                'grade': GradeScale.get_grade(request.school, score.total_score) or '-',
                'position': score.position,
                'remark': grade_obj.remark if grade_obj else '-',
            })

        class_size = ClassEnrollment.objects.filter(
            school_class=enrollment.school_class, session=term.session, is_current=True
        ).count()

        context = {
            'student': child,
            'term': term,
            'enrollment': enrollment,
            'school_class': enrollment.school_class,
            'scores': score_data,
            'term_result': term_result,
            'grade_scale': grade_scale,
            'class_size': class_size,
            'school': request.school,
            'child_pk': child_pk,
        }
        return render(request, 'students/parent/result_booklet.html', context)


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

        results = []
        for term in published_terms:
            enrollment = ClassEnrollment.objects.filter(
                student=student, session=term.session
            ).select_related('school_class').first()
            results.append({
                'term': term,
                'class_name': enrollment.school_class.name if enrollment else '—',
            })

        return render(request, 'students/student/results_history.html', {
            'results': results,
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


class ParentChildResultDownloadView(RoleRequiredMixin, View):
    """Download result booklet PDF for a child (parent portal)."""

    allowed_roles = [Roles.PARENT]

    def get(self, request, child_pk, term_id):
        from academics.pdf import render_result_booklet_pdf

        # Verify parent is linked to this child
        child = get_object_or_404(Student, school=request.school, pk=child_pk)
        if not StudentGuardianLink.objects.filter(student=child, guardian=request.user).exists():
            messages.error(request, 'You are not linked to this student.')
            return redirect('parent-children')

        term = get_object_or_404(Term, pk=term_id, school=request.school, results_published=True)

        response = render_result_booklet_pdf(child, term)
        if response is None:
            messages.error(request, 'No enrollment found for this term.')
            return redirect('parent-child-detail', pk=child_pk)
        return response
