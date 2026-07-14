"""Finance management views for school admin portal."""
from decimal import Decimal
from datetime import date

from django.db.models import Sum, Q
from django.shortcuts import render, get_object_or_404
from django.views.generic.base import View

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from finance.models import Project, ExpenditureCategory, Expenditure
from core.models import Term, AcademicSession


class ProjectListView(RoleRequiredMixin, View):
    """List all projects with spent/remaining."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        projects = Project.objects.filter(school=school).order_by('-start_date')

        status = request.GET.get('status', '')
        if status:
            projects = projects.filter(status=status)

        context = {
            'projects': projects,
            'filter_status': status,
            'status_choices': Project.STATUS_CHOICES,
        }
        return render(request, 'school_admin/project_list.html', context)


class ProjectDetailView(RoleRequiredMixin, View):
    """Project detail with expenditures."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        school = request.school
        project = get_object_or_404(Project, school=school, pk=pk)
        expenditures = Expenditure.objects.filter(
            project=project
        ).select_related('category', 'recorded_by').order_by('-date')

        context = {
            'project': project,
            'expenditures': expenditures,
        }
        return render(request, 'school_admin/project_detail.html', context)


class ExpenditureListView(RoleRequiredMixin, View):
    """List all expenditures with filters."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        expenditures = Expenditure.objects.filter(
            school=school
        ).select_related('category', 'project', 'recorded_by').order_by('-date')

        category_id = request.GET.get('category_id', '')
        if category_id:
            expenditures = expenditures.filter(category_id=category_id)

        project_id = request.GET.get('project_id', '')
        if project_id:
            expenditures = expenditures.filter(project_id=project_id)

        categories = ExpenditureCategory.objects.filter(school=school).order_by('name')
        projects = Project.objects.filter(school=school).order_by('name')

        context = {
            'expenditures': expenditures,
            'categories': categories,
            'projects': projects,
            'filter_category': category_id,
            'filter_project': project_id,
        }
        return render(request, 'school_admin/expenditure_list.html', context)


class FinancialReportView(RoleRequiredMixin, View):
    """Read-only financial overview showing fees, salaries, and expenditure."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school

        start_date_str = request.GET.get("start_date", "")
        end_date_str = request.GET.get("end_date", "")

        if start_date_str and end_date_str:
            try:
                start_date = date.fromisoformat(start_date_str)
                end_date = date.fromisoformat(end_date_str)
            except ValueError:
                start_date, end_date = self._get_default_range(school)
        else:
            start_date, end_date = self._get_default_range(school)

        from fees.models import Payment

        fees_total = (
            Payment.objects.filter(
                school=school,
                status=Payment.Status.CONFIRMED,
                paid_on__date__gte=start_date,
                paid_on__date__lte=end_date,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

        from payroll.models import SalaryDisbursement

        salaries_total = (
            SalaryDisbursement.objects.filter(
                school=school,
                status=SalaryDisbursement.Status.CONFIRMED,
                disbursed_on__date__gte=start_date,
                disbursed_on__date__lte=end_date,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

        expenditure_total = (
            Expenditure.objects.filter(
                school=school,
                date__gte=start_date,
                date__lte=end_date,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

        net = fees_total - salaries_total - expenditure_total

        context = {
            "start_date": start_date,
            "end_date": end_date,
            "fees_total": fees_total,
            "salaries_total": salaries_total,
            "expenditure_total": expenditure_total,
            "net": net,
        }
        return render(request, "school_admin/financial_report.html", context)

    def _get_default_range(self, school):
        current_term = Term.objects.filter(school=school, is_current=True).first()
        if current_term:
            return current_term.start_date, current_term.end_date
        current_session = AcademicSession.objects.filter(
            school=school, is_current=True
        ).first()
        if current_session:
            return current_session.start_date, current_session.end_date
        today = date.today()
        return date(today.year, 1, 1), date(today.year, 12, 31)
