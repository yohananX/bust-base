"""Dashboard view for school admin portal — shows summary cards."""
from decimal import Decimal

from django.db.models import Sum, Q
from django.shortcuts import render
from django.views.generic.base import View

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from students.models import Student
from fees.models import Invoice, Payment
from payroll.models import PayrollRun
from finance.models import Project


class DashboardView(RoleRequiredMixin, View):
    """School admin dashboard with summary cards."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school

        # Total active students
        total_students = Student.objects.filter(
            school=school, status=Student.ACTIVE
        ).count()

        # Outstanding fees — sum of balances where status != PAID
        invoices = Invoice.objects.filter(school=school)
        outstanding_fees = Decimal('0.00')
        for inv in invoices:
            if inv.status != 'PAID':
                outstanding_fees += inv.balance

        # Pending payroll runs — runs with no disbursements
        pending_payroll = PayrollRun.objects.filter(
            school=school, cancelled_at__isnull=True
        ).count()

        # Current term published results
        from core.models import Term
        current_term = Term.objects.filter(
            school=school, is_current=True, results_published=True
        ).first()
        results_published = current_term is not None

        # Active projects
        total_projects = Project.objects.filter(
            school=school
        ).exclude(
            status='CANCELLED'
        ).count()

        context = {
            'total_students': total_students,
            'outstanding_fees': outstanding_fees,
            'pending_payroll': pending_payroll,
            'results_published': results_published,
            'total_projects': total_projects,
        }
        return render(request, 'school_admin/dashboard.html', context)
