"""Shared live stats used by the admin dashboard and sidebar badge counts."""
from fees.models import Invoice, Payment
from fees.selectors import invoices_with_balance


def outstanding_invoices(school):
    """Annotated invoices queryset for a school with positive balances."""
    return invoices_with_balance(Invoice.objects.filter(school=school))


def outstanding_fees_total(school):
    """Sum of all unpaid invoice balances for a school."""
    from django.db.models import Sum

    return outstanding_invoices(school).aggregate(
        total=Sum('balance_annotated')
    )['total'] or 0


def owing_student_count(school):
    """Number of distinct students with a positive invoice balance."""
    return len(set(
        outstanding_invoices(school).filter(
            balance_annotated__gt=0
        ).values_list('student_id', flat=True)
    ))


def pending_transfer_count(school):
    """Count of unconfirmed bank transfers awaiting admin action."""
    return Payment.objects.filter(
        school=school,
        status=Payment.Status.PENDING,
        method=Payment.Method.BANK_TRANSFER,
    ).count()


def pending_score_review_count(school):
    """Count of scores awaiting moderation review."""
    from academics.models import Score

    return Score.objects.filter(
        school=school, moderation_status='PENDING'
    ).count()
