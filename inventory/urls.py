from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('admin/items/', views.AdminItemListView.as_view(), name='admin-item-list'),
    path('admin/items/new/', views.AdminItemCreateView.as_view(), name='admin-item-create'),
    path('admin/items/<int:pk>/edit/', views.AdminItemEditView.as_view(), name='admin-item-edit'),
    path('admin/items/<int:pk>/delete/', views.AdminItemDeleteView.as_view(), name='admin-item-delete'),
    path('admin/procurement/', views.AdminProcurementCreateView.as_view(), name='admin-procurement-create'),
    path('admin/transactions/', views.AdminTransactionListView.as_view(), name='admin-transaction-list'),
    path('admin/low-stock/', views.AdminLowStockView.as_view(), name='admin-low-stock'),
]
