"""Dashboard view for school admin portal — summary cards, charts, recent activity."""
from calendar import month_abbr

from decimal import Decimal

from django.shortcuts import render
from django.utils import timezone
from django.views.generic.base import View

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from core.models import AcademicSession, Term
from students.models import Student, SchoolClass, ClassEnrollment
from fees.models import Payment
from payroll.models import PayrollRun
from finance.models import Project


def _month_keys(year, month, count):
    keys = []
    for _ in range(count):
        keys.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    keys.reverse()
    return keys


def _pct_change(series):
    if len(series) < 2 or not series[-2]:
        return None
    return round((series[-1] - series[-2]) / series[-2] * 100)


class DashboardView(RoleRequiredMixin, View):
    """School admin dashboard with KPI cards, charts and recent activity."""

    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        now = timezone.localtime(timezone.now())

        # Total active students
        total_students = Student.objects.filter(
            school=school, status=Student.ACTIVE
        ).count()

        # Male / female split (all enrolled, not just active)
        male_count = Student.objects.filter(
            school=school, gender=Student.MALE
        ).count()
        female_count = Student.objects.filter(
            school=school, gender=Student.FEMALE
        ).count()

        # Outstanding fees — sum of balances, and how many students owe
        from core.stats import (
            outstanding_fees_total,
            owing_student_count,
        )
        outstanding_fees = outstanding_fees_total(school)
        owing_students = owing_student_count(school)

        # Payroll runs — active (not cancelled) runs
        payroll_runs = PayrollRun.objects.filter(
            school=school, cancelled_at__isnull=True
        ).count()

        # Active projects
        active_projects = Project.objects.filter(
            school=school
        ).exclude(
            status='CANCELLED'
        ).count()

        # Current term published results
        current_term = Term.objects.filter(
            school=school, is_current=True, results_published=True
        ).first()
        results_published = current_term is not None

        # Sessions — for growth, new admissions, class counts
        current_session = AcademicSession.objects.filter(
            school=school, is_current=True
        ).first()

        # Enrollment growth vs previous session
        student_growth = 0
        if current_session:
            previous_session = AcademicSession.objects.filter(
                school=school, start_date__lt=current_session.start_date
            ).order_by('-start_date').first()
            if previous_session:
                enrolled_now = ClassEnrollment.objects.filter(
                    session=current_session
                ).count()
                enrolled_before = ClassEnrollment.objects.filter(
                    session=previous_session
                ).count()
                if enrolled_before:
                    student_growth = round(
                        (enrolled_now - enrolled_before) / enrolled_before * 100
                    )

        # New admissions within the current session
        new_admissions = 0
        if current_session:
            new_admissions = Student.objects.filter(
                school=school,
                admission_date__range=(current_session.start_date, now.date()),
            ).count()

        active_classes = SchoolClass.objects.filter(school=school).count()

        # Fee collection trend — last 6/12 calendar months of confirmed payments
        month_keys_6 = _month_keys(now.year, now.month, 6)
        month_keys_12 = _month_keys(now.year, now.month, 12)
        monthly_labels = [month_abbr[m] for _, m in month_keys_6]
        monthly_labels_6m = monthly_labels
        monthly_labels_12m = [month_abbr[m] for _, m in month_keys_12]

        first_month_12 = month_keys_12[0]
        earliest = timezone.datetime(
            first_month_12[0], first_month_12[1], 1,
            tzinfo=timezone.get_current_timezone(),
        )
        confirmed_payments = Payment.objects.filter(
            school=school,
            status=Payment.Status.CONFIRMED,
            paid_on__gte=earliest,
        ).values_list('paid_on', 'amount')

        by_month = {}
        for paid_on, amount in confirmed_payments:
            key = (paid_on.year, paid_on.month)
            by_month[key] = by_month.get(key, Decimal('0')) + amount
        monthly_fees = [
            float(by_month.get(key, Decimal('0')))
            for key in month_keys_6
        ]
        monthly_fees_6m = monthly_fees
        monthly_fees_12m = [
            float(by_month.get(key, Decimal('0')))
            for key in month_keys_12
        ]
        fee_trend_has_data = any(monthly_fees_6m) or any(monthly_fees_12m)

        first_month_6 = month_keys_6[0]
        earliest_6 = timezone.datetime(
            first_month_6[0], first_month_6[1], 1,
            tzinfo=timezone.get_current_timezone(),
        )

        students_by_month = {}
        for d in Student.objects.filter(
            school=school,
            admission_date__gte=earliest_6.date(),
        ).values_list('admission_date', flat=True):
            if d is None:
                continue
            key = (d.year, d.month)
            students_by_month[key] = students_by_month.get(key, 0) + 1
        students_spark = [students_by_month.get(key, 0) for key in month_keys_6]

        fees_by_month = {}
        for paid_on in Payment.objects.filter(
            school=school,
            status=Payment.Status.CONFIRMED,
            paid_on__gte=earliest_6,
        ).values_list('paid_on', flat=True):
            key = (paid_on.year, paid_on.month)
            fees_by_month[key] = fees_by_month.get(key, 0) + 1
        fees_spark = [fees_by_month.get(key, 0) for key in month_keys_6]

        payroll_by_month = {}
        for d in PayrollRun.objects.filter(
            school=school,
            cancelled_at__isnull=True,
            generated_on__gte=earliest_6,
        ).values_list('generated_on', flat=True):
            key = (d.year, d.month)
            payroll_by_month[key] = payroll_by_month.get(key, 0) + 1
        payroll_spark = [payroll_by_month.get(key, 0) for key in month_keys_6]

        projects_by_month = {}
        for d in Project.objects.filter(
            school=school,
        ).exclude(status='CANCELLED').exclude(
            start_date__isnull=True,
        ).filter(
            start_date__gte=earliest_6.date(),
        ).values_list('start_date', flat=True):
            key = (d.year, d.month)
            projects_by_month[key] = projects_by_month.get(key, 0) + 1
        projects_spark = [projects_by_month.get(key, 0) for key in month_keys_6]

        outstanding_fees_change = _pct_change(fees_spark)
        payroll_change = _pct_change(payroll_spark)
        projects_change = _pct_change(projects_spark)

        # Recent confirmed payments
        recent_payments = []
        for p in Payment.objects.filter(
            school=school, status=Payment.Status.CONFIRMED
        ).select_related(
            'invoice__student__user', 'student__user'
        ).prefetch_related(
            'invoice__student__enrollments', 'student__enrollments'
        )[:5]:
            student = p.student if p.invoice is None else p.invoice.student
            if student is None:
                continue
            enrollment = next(
                (e for e in student.enrollments.all() if e.is_current), None
            )
            recent_payments.append({
                'student_name': student.user.get_full_name() or student.user.username,
                'class_name': enrollment.school_class.name if enrollment else '',
                'amount': p.amount,
                'method': p.get_method_display(),
                'paid_on': p.paid_on,
                'status': p.status,
            })

        from core.stats import (
            outstanding_invoices,
            pending_score_review_count,
            pending_transfer_count,
        )
        invoices = outstanding_invoices(school)
        pending_transfers = pending_transfer_count(school)
        results_to_review = pending_score_review_count(school)

        top_owing_students = []
        for inv in invoices.filter(
            balance_annotated__gt=0
        ).order_by('-balance_annotated').select_related(
            'student__user'
        ).prefetch_related('student__enrollments')[:5]:
            student = inv.student
            if student is None:
                continue
            enrollment = next(
                (e for e in student.enrollments.all() if e.is_current), None
            )
            top_owing_students.append({
                'student_id': student.pk,
                'student_name': student.user.get_full_name() or student.user.username,
                'class_name': enrollment.school_class.name if enrollment else '',
                'balance': inv.balance_annotated,
            })

        context = {
            'total_students': total_students,
            'student_growth': student_growth,
            'outstanding_fees': outstanding_fees,
            'owing_students': owing_students,
            'payroll_runs': payroll_runs,
            'active_projects': active_projects,
            'results_published': results_published,
            'male_count': male_count,
            'female_count': female_count,
            'new_admissions': new_admissions,
            'active_classes': active_classes,
            'monthly_labels': monthly_labels,
            'monthly_labels_6m': monthly_labels_6m,
            'monthly_labels_12m': monthly_labels_12m,
            'monthly_fees': monthly_fees,
            'monthly_fees_6m': monthly_fees_6m,
            'monthly_fees_12m': monthly_fees_12m,
            'fee_trend_has_data': fee_trend_has_data,
            'students_spark': students_spark,
            'fees_spark': fees_spark,
            'payroll_spark': payroll_spark,
            'projects_spark': projects_spark,
            'outstanding_fees_change': outstanding_fees_change,
            'payroll_change': payroll_change,
            'projects_change': projects_change,
            'pending_transfers': pending_transfers,
            'results_to_review': results_to_review,
            'top_owing_students': top_owing_students,
            'recent_payments': recent_payments,
        }
        return render(request, 'school_admin/dashboard.html', context)
