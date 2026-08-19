"""Query helpers for fee reporting — annotated balances without N+1 queries.

This module is the service layer for list-level money logic: anything that
asks about several invoices at once (annotated balances, owed-term sets)
lives here so views never re-implement the business rule. The model's own
properties (``Invoice.balance``, ``Invoice.status``) remain the canonical
single-instance computation and are reused by these helpers.
"""
from decimal import Decimal

from django.db.models import (
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce

from .models import Invoice, Payment


def owed_term_ids(student) -> set:
    """Set of term ids for which the student still has an unpaid balance.

    Prefetches payments so the balance rule is evaluated in memory — a
    constant number of queries regardless of how many invoices exist.
    """
    return {
        inv.term_id
        for inv in Invoice.objects.filter(student=student).prefetch_related('payments')
        if inv.balance > 0
    }


def _paid_amount_subquery():
    """Subquery summing payments that count toward the balance for each invoice.

    Only CONFIRMED payments count. PENDING payments (including bank transfers)
    never reduce the balance until the admin confirms them; FAILED payments
    never count either.
    """
    return Subquery(
        Payment.objects.filter(
            invoice=OuterRef('pk'),
        ).filter(
            status=Payment.Status.CONFIRMED,
        ).values('invoice').annotate(total=Sum('amount')).values('total'),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )


def invoices_with_balance(queryset):
    """Annotate each Invoice with ``amount_paid_annotated`` and ``balance_annotated``.

    Additive annotations for list/report views — the model's Python properties
    (``amount_paid``, ``balance``, ``status``) are left untouched. Only CONFIRMED
    payments count toward the paid total; PENDING and FAILED payments never count
    (business rule).
    """
    amount_paid_expr = Coalesce(
        _paid_amount_subquery(),
        Value(Decimal('0.00')),
    )
    balance_expr = ExpressionWrapper(
        F('total_amount') - amount_paid_expr,
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )
    return queryset.annotate(
        amount_paid_annotated=amount_paid_expr,
        balance_annotated=balance_expr,
    )
