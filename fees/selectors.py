"""Query helpers for fee reporting — annotated balances without N+1 queries."""
from decimal import Decimal

from django.db.models import (
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce

from .models import Payment


def _paid_amount_subquery():
    """Subquery summing payments that count toward the balance for each invoice.

    Counts CONFIRMED payments plus PENDING bank transfers (a pending transfer is
    real money already sent; if it is rejected the payment becomes FAILED and stops
    counting). All other PENDING/FAILED payments never count.
    """
    return Subquery(
        Payment.objects.filter(
            invoice=OuterRef('pk'),
        ).filter(
            Q(status=Payment.Status.CONFIRMED)
            | Q(status=Payment.Status.PENDING, method=Payment.Method.BANK_TRANSFER)
        ).values('invoice').annotate(total=Sum('amount')).values('total'),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )


def invoices_with_balance(queryset):
    """Annotate each Invoice with ``amount_paid_annotated`` and ``balance_annotated``.

    Additive annotations for list/report views — the model's Python properties
    (``amount_paid``, ``balance``, ``status``) are left untouched. PENDING bank
    transfers count toward the paid total (money already sent); other PENDING and
    FAILED payments never count (business rule).
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
