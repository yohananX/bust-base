from django.shortcuts import get_object_or_404, render
from django.views.generic.base import View

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from core.models import Term
from students.models import StudentGuardianLink, ClassEnrollment
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

        return render(request, 'students/parent/child_detail.html', {
            'student': student,
            'current_enrollment': current_enrollment,
            'current_term': current_term,
            'invoices': invoices,
            'scores': scores,
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

        return render(request, 'students/student/overview.html', {
            'enrollment': enrollment,
            'invoices': invoices,
            'scores': scores,
        })
