from decimal import Decimal
from datetime import date

from django.db.models import Sum
from django.shortcuts import render
from django.views import View

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from core.models import Term, AcademicSession


class FinancialReportView(RoleRequiredMixin, View):
    """Read-only financial overview showing fees, salaries, and expenditure."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school

        # Determine date range: default to current term, else current academic session
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

        # Total fees collected (CONFIRMED payments in period)
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

        # Total salaries disbursed (CONFIRMED disbursements in period)
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

        # Total expenditure in period
        from .models import Expenditure

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
        return render(request, "finance/report.html", context)

    def _get_default_range(self, school):
        """Default to current term dates, or current academic session."""
        current_term = Term.objects.filter(school=school, is_current=True).first()
        if current_term:
            return current_term.start_date, current_term.end_date
        # Fallback: current academic session
        current_session = AcademicSession.objects.filter(
            school=school, is_current=True
        ).first()
        if current_session:
            return current_session.start_date, current_session.end_date
        # Last resort: current year
        today = date.today()
        return date(today.year, 1, 1), date(today.year, 12, 31)
