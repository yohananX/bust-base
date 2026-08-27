from django.db.models import F
from .models import InventoryItem


def low_stock_items(school):
    """Items where available stock is at or below threshold."""
    return InventoryItem.objects.filter(
        school=school,
        is_active=True,
        total_stock__lte=F('min_stock_threshold'),
    ).select_related('school_class')


def available_items_for_class(school, school_class):
    """Active items assigned to a specific class."""
    return InventoryItem.objects.filter(
        school=school,
        school_class=school_class,
        is_active=True,
    ).select_related('school_class')


def item_with_transactions(school, item_pk):
    """Item with prefetched transactions for detail view."""
    return InventoryItem.objects.filter(
        school=school, pk=item_pk
    ).prefetch_related(
        'transactions__created_by',
        'procurements__purchased_by',
    ).first()
