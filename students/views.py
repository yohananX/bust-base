from django.shortcuts import get_object_or_404, render, redirect
from django.views.generic.base import View
from django.contrib import messages

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from core.models import Term
from students.models import Student, StudentGuardianLink, ClassEnrollment
from fees.models import Invoice

from academics.models import Score


class ParentChildrenListView(RoleRequiredMixin, View):
    """Lists all children linked to the logged-in parent."""

    allowed_roles = [Roles.PARENT]

    def get(self, request):
        guardian_links = StudentGuardianLink.objects.filter(
            guardian=request.user,
        ).select_related('student', 'student__user')

        current_term = Term.objects.filter(
            school=request.school,
            is_current=True,
        ).first()

        for link in guardian_links:
            student = link.student

            # Annotate school_class from the current enrollment
            enrollment = ClassEnrollment.objects.filter(
                student=student,
                is_current=True,
            ).select_related('school_class').first()
            student.school_class = enrollment.school_class if enrollment else None

            # Annotate invoice_balance
            invoices = Invoice.objects.filter(student=student)
            student.invoice_balance = sum(inv.balance for inv in invoices)

            # Annotate has_published_results
            if current_term and current_term.results_published:
                student.has_published_results = Score.objects.filter(
                    student=student,
                    term=current_term,
                ).exists()
            else:
                student.has_published_results = False

        return render(request, 'students/parent/children_list.html', {
            'guardian_links': guardian_links,
        })


class ParentChildDetailView(RoleRequiredMixin, View):
    """Displays details, scores, and invoices for a specific child."""

    allowed_roles = [Roles.PARENT]

    def get(self, request, pk):
        guardian_link = get_object_or_404(
            StudentGuardianLink,
            guardian=request.user,
            student_id=pk,
        )
        student = guardian_link.student

        current_enrollment = ClassEnrollment.objects.filter(
            student=student,
            is_current=True,
        ).select_related('school_class', 'session').first()

        current_term = Term.objects.filter(
            school=request.school,
            is_current=True,
        ).first()

        invoices = Invoice.objects.filter(
            student=student,
        ).prefetch_related('payments')

        scores = Score.objects.visible_to_user(request.user).filter(
            student=student,
        ).select_related('subject').order_by('subject__name')

        # Published terms with scores for this student
        published_terms = Term.objects.filter(
            school=request.school,
            results_published=True,
            scores__student=student,
        ).distinct().order_by('-start_date')

        return render(request, 'students/parent/child_detail.html', {
            'student': student,
            'current_enrollment': current_enrollment,
            'current_term': current_term,
            'invoices': invoices,
            'scores': scores,
            'published_terms': published_terms,
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
