"""Dashboard view for school admin portal — summary cards, charts, recent activity."""
from calendar import month_abbr

from decimal import Decimal

from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone
from django.views.generic.base import View

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from core.models import AcademicSession, Term
from students.models import Student, SchoolClass, ClassEnrollment
from fees.models import Invoice, Payment
from fees.selectors import invoices_with_balance
from payroll.models import PayrollRun
from finance.models import Project


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
        invoices = invoices_with_balance(Invoice.objects.filter(school=school))
        outstanding_fees = invoices.aggregate(
            total=Sum('balance_annotated')
        )['total'] or Decimal('0.00')
        owing_students = len(set(
            invoices.filter(
                balance_annotated__gt=0
            ).values_list('student_id', flat=True)
        ))

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

        # Fee collection trend — last 6 calendar months of confirmed payments
        month_keys = []
        year, month = now.year, now.month
        for _ in range(6):
            month_keys.append((year, month))
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        month_keys.reverse()
        monthly_labels = [month_abbr[m] for _, m in month_keys]

        first_month = month_keys[0]
        earliest = timezone.datetime(
            first_month[0], first_month[1], 1,
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
            for key in month_keys
        ]

        # Recent confirmed payments
        recent_payments = []
        for p in Payment.objects.filter(
            school=school, status=Payment.Status.CONFIRMED
        ).select_related(
            'invoice__student__user'
        ).prefetch_related('invoice__student__enrollments')[:5]:
            student = p.invoice.student
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
            'monthly_fees': monthly_fees,
            'recent_payments': recent_payments,
        }
        return render(request, 'school_admin/dashboard.html', context)
