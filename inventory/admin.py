from decimal import Decimal
from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import (
    InventoryItem, FeeCategoryInventoryItem, InventoryProcurement,
    InventoryTransaction, BookPurchase
)


class FeeCategoryInventoryItemInline(admin.TabularInline):
    model = FeeCategoryInventoryItem
    extra = 1
    autocomplete_fields = ['inventory_item']
    verbose_name = _('attached inventory item')
    verbose_name_plural = _('attached inventory items')


class InventoryProcurementInline(admin.TabularInline):
    model = InventoryProcurement
    extra = 0
    readonly_fields = ['quantity', 'purchased_by', 'procurement_date', 'unit_cost', 'supplier_name']
    can_delete = False
    max_num = 0


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'category', 'school_class', 'total_stock',
        'available_stock_display', 'unit_price', 'is_low_stock', 'is_active',
    ]
    list_filter = ['category', 'school_class', 'is_active', 'school']
    search_fields = ['name', 'sku', 'school_class__name']
    inlines = [InventoryProcurementInline]
    readonly_fields = ['available_stock_display']

    @admin.display(description=_('Available'))
    def available_stock_display(self, obj):
        return obj.available_stock

    @admin.display(boolean=True, description=_('Low stock'))
    def is_low_stock(self, obj):
        return obj.available_stock <= obj.min_stock_threshold


@admin.register(InventoryTransaction)
class InventoryTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'item', 'transaction_type', 'quantity_change', 'balance_after',
        'reference', 'created_by', 'created_at',
    ]
    list_filter = ['transaction_type', 'item', 'school']
    search_fields = ['item__name', 'reference', 'notes']
    readonly_fields = [
        'item', 'transaction_type', 'quantity_change', 'balance_after',
        'reference', 'created_by', 'created_at', 'notes',
    ]

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BookPurchase)
class BookPurchaseAdmin(admin.ModelAdmin):
    list_display = [
        'student', 'item', 'quantity', 'unit_price', 'total_price',
        'status', 'created_at',
    ]
    list_filter = ['status', 'item__category', 'school']
    search_fields = [
        'student__user__username', 'student__admission_number', 'item__name',
    ]
    readonly_fields = [
        'payment', 'student', 'item', 'quantity', 'unit_price',
        'total_price', 'status', 'created_at', 'confirmed_at',
    ]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(FeeCategoryInventoryItem)
class FeeCategoryInventoryItemAdmin(admin.ModelAdmin):
    list_display = ['fee_category', 'inventory_item']
    list_filter = ['fee_category', 'inventory_item__school_class', 'fee_category__school']
    search_fields = ['fee_category__name', 'inventory_item__name']

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'inventory_item':
            kwargs['queryset'] = InventoryItem.objects.filter(is_active=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# Re-register FeeCategory with inventory inline
from fees.models import FeeCategory as _FeeCategory
from fees.admin import FeeCategoryAdmin as _OriginalFeeCategoryAdmin
from django.contrib.admin import site

if not site.is_registered(_FeeCategory):
    class FeeCategoryWithInventoryInline(_OriginalFeeCategoryAdmin):
        inlines = _OriginalFeeCategoryAdmin.inlines + [FeeCategoryInventoryItemInline]

    admin.site.unregister(_FeeCategory)
    admin.site.register(_FeeCategory, FeeCategoryWithInventoryInline)
