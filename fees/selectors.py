"""Query helpers for fee reporting — annotated balances without N+1 queries."""
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

from .models import Payment


def _confirmed_amount_paid_subquery():
    """Subquery summing CONFIRMED payments for each invoice (OuterRef pk)."""
    return Subquery(
        Payment.objects.filter(
            invoice=OuterRef('pk'),
            status=Payment.Status.CONFIRMED,
        ).values('invoice').annotate(total=Sum('amount')).values('total'),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )


def invoices_with_balance(queryset):
    """Annotate each Invoice with ``amount_paid_annotated`` and ``balance_annotated``.

    Additive annotations for list/report views — the model's Python properties
    (``amount_paid``, ``balance``, ``status``) are left untouched. PENDING/FAILED
    payments never count toward the paid total (business rule).
    """
    amount_paid_expr = Coalesce(
        _confirmed_amount_paid_subquery(),
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
