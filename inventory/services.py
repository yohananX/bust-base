from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.db.models import F
from django.urls import reverse
from notifications.utils import notify_admins

from .models import InventoryItem, InventoryTransaction, BookPurchase, InventoryProcurement
from fees.models import Payment


def validate_book_checkout(student, selected_items):
    """Validate stock availability before checkout.

    Args:
        student: Student instance
        selected_items: list of dicts with keys 'item_id' and 'quantity'

    Returns:
        (is_valid: bool, errors: list[str])
    """
    errors = []
    item_ids = [s['item_id'] for s in selected_items]

    if not item_ids:
        return False, ['No items selected.']

    items = InventoryItem.objects.filter(
        pk__in=item_ids,
        school=student.school,
        is_active=True,
    ).select_related('school_class')

    items_by_id = {item.pk: item for item in items}

    for sel in selected_items:
        item = items_by_id.get(sel['item_id'])
        if item is None:
            errors.append(f'Item {sel["item_id"]} not found or inactive.')
            continue

        qty = sel.get('quantity', 0)
        if qty <= 0:
            errors.append(f'Quantity for {item.name} must be positive.')
            continue

        if qty > item.available_stock:
            errors.append(
                f'Only {item.available_stock} × {item.name} available '
                f'(requested {qty}).'
            )

    return len(errors) == 0, errors


def process_payment_confirmation(payment):
    """Post-confirmation hook: deduct stock for confirmed BookPurchases.

    Called from fees.paystack after issue_receipt(). Runs inside the
    webhook's transaction.atomic() block so failures roll back.

    If stock is insufficient at confirmation time:
    - Payment is marked FAILED
    - BookPurchases are CANCELLED
    - Admin is notified
    """
    pending_purchases = payment.book_purchases.filter(
        status=BookPurchase.Status.PENDING
    ).select_related('item')

    if not pending_purchases.exists():
        return

    insufficient_items = []
    for bp in pending_purchases:
        if bp.item.available_stock < bp.quantity:
            insufficient_items.append(bp)

    if insufficient_items:
        payment.status = Payment.Status.FAILED
        payment.save(update_fields=['status'])
        pending_purchases.update(status=BookPurchase.Status.CANCELLED)

        notify_admins(
            school=payment.school,
            subject=_('Book purchase failed: insufficient stock'),
            message=(
                f'{payment.student}\'s payment of ₦{payment.amount} failed because '
                f'the following items are out of stock: '
                f'{", ".join(str(bp.item) for bp in insufficient_items)}. '
                f'The payment has been marked as failed.'
            ),
            reference=f'inventory-stock-fail:{payment.id}',
            url=reverse('school_admin:inventory_item_list'),
            action_label=_('Review inventory'),
        )
        return

    for bp in pending_purchases:
        item = bp.item

        InventoryItem.objects.filter(pk=item.pk).update(
            total_stock=F('total_stock') - bp.quantity
        )
        item.refresh_from_db()

        bp.status = BookPurchase.Status.CONFIRMED
        bp.confirmed_at = timezone.now()
        bp.save(update_fields=['status', 'confirmed_at'])

        InventoryTransaction.objects.create(
            school=payment.school,
            item=item,
            transaction_type=InventoryTransaction.TransactionType.SALE,
            quantity_change=-bp.quantity,
            balance_after=item.total_stock,
            reference=f'payment:{payment.id}',
            created_by=payment.recorded_by or (
                payment.student.user if payment.student else None
            ),
            notes=f'Auto-deducted from payment {payment.reference}',
        )


def restore_stock_for_payment(payment):
    """Restore stock when a payment is refunded.

    Idempotent: checks for existing REFUND transaction before restoring.
    """
    confirmed_purchases = payment.book_purchases.filter(
        status=BookPurchase.Status.CONFIRMED
    ).select_related('item')

    if not confirmed_purchases.exists():
        return

    for bp in confirmed_purchases:
        item = bp.item

        already_restored = InventoryTransaction.objects.filter(
            item=item,
            transaction_type=InventoryTransaction.TransactionType.REFUND,
            reference=f'refund:{payment.id}',
        ).exists()

        if already_restored:
            continue

        InventoryItem.objects.filter(pk=item.pk).update(
            total_stock=F('total_stock') + bp.quantity
        )
        item.refresh_from_db()

        InventoryTransaction.objects.create(
            school=payment.school,
            item=item,
            transaction_type=InventoryTransaction.TransactionType.REFUND,
            quantity_change=bp.quantity,
            balance_after=item.total_stock,
            reference=f'refund:{payment.id}',
            created_by=None,
            notes=f'Stock restored for refunded payment {payment.reference}',
        )


def add_procurement(item, quantity, purchased_by, unit_cost, **kwargs):
    """Add stock via procurement. Atomic: updates item + creates transaction."""
    with transaction.atomic():
        InventoryItem.objects.filter(pk=item.pk).update(
            total_stock=F('total_stock') + quantity
        )
        item.refresh_from_db()

        InventoryTransaction.objects.create(
            school=item.school,
            item=item,
            transaction_type=InventoryTransaction.TransactionType.PROCUREMENT,
            quantity_change=quantity,
            balance_after=item.total_stock,
            reference=kwargs.get('reference', ''),
            created_by=purchased_by,
            notes=kwargs.get('notes', ''),
        )

        procurement = InventoryProcurement.objects.create(
            school=item.school,
            item=item,
            quantity=quantity,
            purchased_by=purchased_by,
            unit_cost=unit_cost,
            **kwargs,
        )
        return procurement
