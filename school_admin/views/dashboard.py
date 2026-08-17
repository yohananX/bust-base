"""Dashboard view for school admin portal — summary cards, chart, recent activity."""
from decimal import Decimal

from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone
from django.views.generic.base import View

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles, User
from core.models import AcademicSession, Term
from students.models import Student, SchoolClass, ClassEnrollment
from fees.models import Payment


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

        # Teachers on staff
        teacher_count = User.objects.filter(
            school=school, role=Roles.TEACHER
        ).count()

        # Outstanding fees — sum of balances, and how many students owe
        from core.stats import (
            outstanding_fees_total,
            owing_student_count,
        )
        outstanding_fees = outstanding_fees_total(school)
        owing_students = owing_student_count(school)

        # Current term published results
        current_term = Term.objects.filter(
            school=school, is_current=True
        ).first()
        results_published = (
            current_term is not None and current_term.results_published
        )

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

        active_classes = SchoolClass.objects.filter(school=school).count()

        # Collected this term — confirmed payments within the current term
        collected_this_term = Decimal('0')
        if current_term:
            collected_this_term = (
                Payment.objects.filter(
                    school=school,
                    status=Payment.Status.CONFIRMED,
                    paid_on__date__gte=current_term.start_date,
                    paid_on__date__lte=current_term.end_date,
                ).aggregate(total=Sum('amount'))['total']
                or Decimal('0')
            )

        # Fee collection by term — schools think in terms, not months.
        terms = list(
            Term.objects.filter(school=school)
            .select_related('session')
            .order_by('start_date')
        )
        chart_terms = terms[-6:]
        term_fees = {t.pk: Decimal('0') for t in chart_terms}
        if chart_terms:
            first_start = chart_terms[0].start_date
            last_end = chart_terms[-1].end_date
            for paid_on, amount in Payment.objects.filter(
                school=school,
                status=Payment.Status.CONFIRMED,
                paid_on__date__gte=first_start,
                paid_on__date__lte=last_end,
            ).values_list('paid_on', 'amount'):
                d = paid_on.date()
                for term in chart_terms:
                    if term.start_date <= d <= term.end_date:
                        term_fees[term.pk] = (
                            term_fees.get(term.pk, Decimal('0')) + amount
                        )
                        break
        term_labels = [
            f"{t.name} · {t.session.name}" for t in chart_terms
        ]
        term_fees_list = [float(term_fees[t.pk]) for t in chart_terms]
        fee_trend_has_data = any(term_fees_list)

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
            'teacher_count': teacher_count,
            'outstanding_fees': outstanding_fees,
            'owing_students': owing_students,
            'collected_this_term': collected_this_term,
            'current_term_name': current_term.name if current_term else None,
            'results_published': results_published,
            'active_classes': active_classes,
            'term_labels': term_labels,
            'term_fees': term_fees_list,
            'fee_trend_has_data': fee_trend_has_data,
            'pending_transfers': pending_transfers,
            'results_to_review': results_to_review,
            'top_owing_students': top_owing_students,
            'recent_payments': recent_payments,
        }
        return render(request, 'school_admin/dashboard.html', context)