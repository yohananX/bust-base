from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from core.models import TenantScopedModel


class InventoryItem(TenantScopedModel):
    CATEGORY_CHOICES = [
        ('BOOK', _('Book / Textbook')),
        ('NOTEBOOK', _('Notebook / Lesson Note')),
        ('WRITING', _('Pen / Pencil / Writing Material')),
        ('UNIFORM', _('Uniform / Wearable')),
        ('EQUIPMENT', _('Equipment / Device')),
        ('OTHER', _('Other')),
    ]

    name = models.CharField(max_length=200, verbose_name=_('name'))
    category = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default='BOOK',
        verbose_name=_('category'),
    )
    school_class = models.ForeignKey(
        'students.SchoolClass',
        on_delete=models.CASCADE,
        verbose_name=_('school class'),
        help_text=_('Items without a class assignment are admin-only.'),
    )
    sku = models.CharField(max_length=50, blank=True, verbose_name=_('SKU'))
    unit = models.CharField(max_length=50, default='piece', verbose_name=_('unit'))
    total_stock = models.PositiveIntegerField(default=0, verbose_name=_('total stock'))
    min_stock_threshold = models.PositiveIntegerField(
        default=5, verbose_name=_('min stock threshold'),
    )
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        verbose_name=_('unit price'),
    )
    is_active = models.BooleanField(default=True, verbose_name=_('active'))

    class Meta:
        verbose_name = _('inventory item')
        verbose_name_plural = _('inventory items')
        unique_together = ('school', 'name', 'school_class')
        ordering = ['category', 'name']

    def __str__(self):
        return f'{self.name} ({self.school_class.name})'

    def clean(self):
        if self.total_stock < 0:
            raise ValidationError({'total_stock': _('Stock cannot be negative.')})

    @property
    def available_stock(self) -> int:
        return max(self.total_stock - getattr(self, '_reserved', 0), 0)


class FeeCategoryInventoryItem(models.Model):
    fee_category = models.ForeignKey(
        'fees.FeeCategory', on_delete=models.CASCADE,
        related_name='inventory_items', verbose_name=_('fee category'),
    )
    inventory_item = models.ForeignKey(
        'inventory.InventoryItem', on_delete=models.CASCADE,
        related_name='fee_categories', verbose_name=_('inventory item'),
    )

    class Meta:
        verbose_name = _('fee category inventory item')
        verbose_name_plural = _('fee category inventory items')
        unique_together = ('fee_category', 'inventory_item')

    def __str__(self):
        return f'{self.fee_category} → {self.inventory_item}'

    def clean(self):
        if self.fee_category.school_id != self.inventory_item.school_id:
            raise ValidationError(_('Cannot link items from different schools.'))


class InventoryProcurement(TenantScopedModel):
    item = models.ForeignKey(
        InventoryItem, on_delete=models.CASCADE, related_name='procurements',
        verbose_name=_('item'),
    )
    quantity = models.PositiveIntegerField(verbose_name=_('quantity'))
    purchased_by = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, verbose_name=_('purchased by'),
    )
    procurement_date = models.DateField(verbose_name=_('procurement date'))
    supplier_name = models.CharField(max_length=200, blank=True, verbose_name=_('supplier'))
    unit_cost = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name=_('unit cost'),
    )
    reference = models.CharField(max_length=100, blank=True, verbose_name=_('reference'))
    notes = models.TextField(blank=True, verbose_name=_('notes'))

    class Meta:
        verbose_name = _('inventory procurement')
        verbose_name_plural = _('inventory procurements')
        ordering = ['-procurement_date']

    def __str__(self):
        return f'{self.item} +{self.quantity} on {self.procurement_date}'


class InventoryTransaction(TenantScopedModel):
    class TransactionType(models.TextChoices):
        PROCUREMENT = 'PROCUREMENT', _('Procurement')
        SALE = 'SALE', _('Sale')
        REFUND = 'REFUND', _('Refund')
        ADJUSTMENT = 'ADJUSTMENT', _('Adjustment')

    item = models.ForeignKey(
        InventoryItem, on_delete=models.CASCADE, related_name='transactions',
        verbose_name=_('item'),
    )
    transaction_type = models.CharField(
        max_length=20, choices=TransactionType.choices, verbose_name=_('type'),
    )
    quantity_change = models.IntegerField(verbose_name=_('quantity change'))
    balance_after = models.PositiveIntegerField(verbose_name=_('balance after'))
    reference = models.CharField(
        max_length=100, blank=True, verbose_name=_('reference'),
    )
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, verbose_name=_('created by'),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('created at'))
    notes = models.TextField(blank=True, verbose_name=_('notes'))

    class Meta:
        verbose_name = _('inventory transaction')
        verbose_name_plural = _('inventory transactions')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.item} {self.get_transaction_type_display()} {self.quantity_change:+d}'


class BookPurchase(TenantScopedModel):
    class Status(models.TextChoices):
        PENDING = 'PENDING', _('Pending')
        CONFIRMED = 'CONFIRMED', _('Confirmed')
        CANCELLED = 'CANCELLED', _('Cancelled')

    payment = models.ForeignKey(
        'fees.Payment',
        on_delete=models.CASCADE,
        related_name='book_purchases',
        verbose_name=_('payment'),
    )
    student = models.ForeignKey(
        'students.Student', on_delete=models.CASCADE, verbose_name=_('student'),
    )
    item = models.ForeignKey(
        InventoryItem, on_delete=models.CASCADE, verbose_name=_('item'),
    )
    quantity = models.PositiveIntegerField(verbose_name=_('quantity'))
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name=_('unit price'),
    )
    total_price = models.DecimalField(
        max_digits=10, decimal_places=2, verbose_name=_('total price'),
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING,
        verbose_name=_('status'),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('created at'))
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name=_('confirmed at'))

    class Meta:
        verbose_name = _('book purchase')
        verbose_name_plural = _('book purchases')
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.student} — {self.item} ×{self.quantity} ({self.status})'

    def clean(self):
        if self.total_price != self.unit_price * self.quantity:
            raise ValidationError({
                'total_price': _('Total price must equal unit price × quantity.')
            })
