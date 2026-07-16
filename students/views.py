from django.db.models import Sum
from django.shortcuts import get_object_or_404, render, redirect
from django.views.generic.base import View
from django.contrib import messages

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from core.models import Term
from students.models import Student, StudentGuardianLink, ClassEnrollment
from fees.models import Invoice

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
            unpaid_invoices = Invoice.objects.filter(
                student=student,
            ).exclude(status='PAID')
            total_owed = sum(inv.balance for inv in unpaid_invoices)
            unpaid_count = unpaid_invoices.count()

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

        return render(request, 'students/parent/children_list.html', {
            'children_data': children_data,
            'total_children': total_children,
            'total_owed_all': total_owed_all,
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
        total_owed = sum(inv.balance for inv in invoices)
        unpaid_count = invoices.exclude(status='PAID').count()

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


class StudentOverviewView(RoleRequiredMixin, View):
    """Student dashboard showing enrollment, invoices, and scores."""

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

        return render(request, 'students/student/overview.html', {
            'enrollment': enrollment,
            'invoices': invoices,
            'scores': scores,
            'published_terms': published_terms,
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
