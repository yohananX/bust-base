from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.views.generic.base import View
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.core.paginator import Paginator
from decimal import Decimal

from accounts.mixins import RoleRequiredMixin
from accounts.models import Roles
from students.models import SchoolClass
from inventory.models import (
    InventoryItem, InventoryProcurement, InventoryTransaction, BookPurchase
)
from inventory.services import add_procurement
from inventory.selectors import low_stock_items, available_items_for_class


# ======================================================================
# ITEM MANAGEMENT
# ======================================================================

class AdminItemListView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        items = InventoryItem.objects.filter(school=school)

        category = request.GET.get('category')
        if category:
            items = items.filter(category=category)

        class_id = request.GET.get('class_id')
        if class_id:
            items = items.filter(school_class_id=class_id)

        stock_status = request.GET.get('stock_status')
        if stock_status == 'low':
            items = low_stock_items(school)
        elif stock_status == 'out':
            items = items.filter(total_stock=0)

        q = request.GET.get('q')
        if q:
            items = items.filter(name__icontains=q)

        items = items.select_related('school_class').order_by('category', 'name')

        paginator = Paginator(items, 25)
        page = request.GET.get('page', 1)
        items_page = paginator.get_page(page)

        classes = SchoolClass.objects.filter(school=school, is_active=True)

        return render(request, 'school_admin/inventory/item_list.html', {
            'items': items_page,
            'classes': classes,
            'category_choices': InventoryItem.CATEGORY_CHOICES,
            'selected_category': category,
            'selected_class': class_id,
            'selected_stock_status': stock_status,
            'query': q,
        })


class AdminItemCreateView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        classes = SchoolClass.objects.filter(school=request.school, is_active=True)
        return render(request, 'school_admin/inventory/item_form.html', {
            'classes': classes,
            'category_choices': InventoryItem.CATEGORY_CHOICES,
            'is_edit': False,
        })

    def post(self, request):
        school = request.school
        required = ['name', 'school_class']
        if not all(request.POST.get(f) for f in required):
            messages.error(request, 'Name and class are required.')
            return redirect('school_admin:inventory_item_create')

        try:
            with transaction.atomic():
                item = InventoryItem(
                    school=school,
                    name=request.POST.get('name', '').strip(),
                    category=request.POST.get('category', 'BOOK'),
                    school_class_id=request.POST.get('school_class'),
                    sku=request.POST.get('sku', '').strip(),
                    unit=request.POST.get('unit', 'piece'),
                    total_stock=int(request.POST.get('initial_stock', 0)),
                    min_stock_threshold=int(request.POST.get('min_stock_threshold', 5)),
                    unit_price=Decimal(request.POST.get('unit_price', '0')),
                    is_active=True,
                )
                item.full_clean()
                item.save()

                if item.total_stock > 0:
                    InventoryTransaction.objects.create(
                        school=school,
                        item=item,
                        transaction_type=InventoryTransaction.TransactionType.PROCUREMENT,
                        quantity_change=item.total_stock,
                        balance_after=item.total_stock,
                        reference='initial-stock',
                        created_by=request.user,
                        notes='Initial stock on item creation',
                    )

                messages.success(request, f'Item "{item.name}" created successfully.')
                return redirect('school_admin:inventory_item_list')

        except Exception as e:
            messages.error(request, f'Error creating item: {e}')
            return redirect('school_admin:inventory_item_create')


class AdminItemEditView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def get(self, request, pk):
        item = get_object_or_404(InventoryItem, pk=pk, school=request.school)
        classes = SchoolClass.objects.filter(school=request.school, is_active=True)
        return render(request, 'school_admin/inventory/item_form.html', {
            'item': item,
            'classes': classes,
            'category_choices': InventoryItem.CATEGORY_CHOICES,
            'is_edit': True,
        })

    def post(self, request, pk):
        item = get_object_or_404(InventoryItem, pk=pk, school=request.school)

        try:
            item.name = request.POST.get('name', item.name).strip()
            item.category = request.POST.get('category', item.category)
            item.school_class_id = request.POST.get('school_class', item.school_class_id)
            item.sku = request.POST.get('sku', '').strip()
            item.unit = request.POST.get('unit', item.unit)
            item.min_stock_threshold = int(request.POST.get('min_stock_threshold', item.min_stock_threshold))
            item.unit_price = Decimal(request.POST.get('unit_price', str(item.unit_price)))
            item.full_clean()
            item.save(update_fields=[
                'name', 'category', 'school_class', 'sku', 'unit',
                'min_stock_threshold', 'unit_price',
            ])
            messages.success(request, f'Item "{item.name}" updated.')
            return redirect('school_admin:inventory_item_list')

        except Exception as e:
            messages.error(request, f'Error updating item: {e}')
            return redirect('school_admin:inventory_item_edit', pk=pk)


class AdminItemDeleteView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def post(self, request, pk):
        item = get_object_or_404(InventoryItem, pk=pk, school=request.school)
        item.is_active = False
        item.save(update_fields=['is_active'])
        messages.success(request, f'Item "{item.name}" deactivated.')
        return redirect('school_admin:inventory_item_list')


# ======================================================================
# PROCUREMENT
# ======================================================================

class AdminProcurementCreateView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        items = InventoryItem.objects.filter(
            school=request.school, is_active=True
        ).select_related('school_class')
        return render(request, 'school_admin/inventory/procurement_form.html', {
            'items': items,
        })

    def post(self, request):
        school = request.school
        required = ['item_id', 'quantity', 'unit_cost', 'procurement_date']
        if not all(request.POST.get(f) for f in required):
            messages.error(request, 'All fields are required.')
            return redirect('school_admin:inventory_procurement')

        try:
            with transaction.atomic():
                item = get_object_or_404(
                    InventoryItem, pk=request.POST.get('item_id'), school=school
                )
                quantity = int(request.POST.get('quantity', 0))
                unit_cost = Decimal(request.POST.get('unit_cost', '0'))
                procurement_date = request.POST.get('procurement_date')

                if quantity <= 0:
                    messages.error(request, 'Quantity must be positive.')
                    return redirect('school_admin:inventory_procurement')

                procurement = add_procurement(
                    item=item,
                    quantity=quantity,
                    purchased_by=request.user,
                    unit_cost=unit_cost,
                    procurement_date=procurement_date,
                    supplier_name=request.POST.get('supplier_name', ''),
                    reference=request.POST.get('reference', ''),
                    notes=request.POST.get('notes', ''),
                )

                messages.success(
                    request,
                    f'Procurement recorded: {quantity} × {item.name}. '
                    f'New stock: {item.total_stock}'
                )
                return redirect('school_admin:inventory_item_list')

        except Exception as e:
            messages.error(request, f'Error recording procurement: {e}')
            return redirect('school_admin:inventory_procurement')


# ======================================================================
# TRANSACTIONS & REPORTS
# ======================================================================

class AdminTransactionListView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        transactions = InventoryTransaction.objects.filter(school=school)

        item_id = request.GET.get('item_id')
        if item_id:
            transactions = transactions.filter(item_id=item_id)

        tx_type = request.GET.get('type')
        if tx_type:
            transactions = transactions.filter(transaction_type=tx_type)

        transactions = transactions.select_related(
            'item', 'item__school_class', 'created_by'
        ).order_by('-created_at')

        paginator = Paginator(transactions, 50)
        page = request.GET.get('page', 1)
        transactions_page = paginator.get_page(page)

        items = InventoryItem.objects.filter(school=school).select_related('school_class')

        return render(request, 'school_admin/inventory/transaction_list.html', {
            'transactions': transactions_page,
            'items': items,
            'type_choices': InventoryTransaction.TransactionType.choices,
            'selected_item': item_id,
            'selected_type': tx_type,
        })


class AdminLowStockView(RoleRequiredMixin, View):
    allowed_roles = [Roles.ADMIN]

    def get(self, request):
        school = request.school
        items = low_stock_items(school)
        return render(request, 'school_admin/inventory/low_stock.html', {
            'items': items,
        })
