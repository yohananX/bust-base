from django.urls import path

from . import views

urlpatterns = [
    path('', views.ParentDashboardView.as_view(), name='parent-dashboard'),
    path('children/', views.ParentChildrenListView.as_view(), name='parent-children'),
    path('child/<int:pk>/', views.ParentChildDetailView.as_view(), name='parent-child-detail'),
    path('invoices/', views.ParentInvoicesView.as_view(), name='parent-invoices'),
    path('invoice/<int:pk>/', views.ParentInvoiceDetailView.as_view(), name='parent-invoice-detail'),
    path('pay/', views.MakePaymentView.as_view(), name='parent-pay'),
    path('extra-lessons/', views.ParentExtraLessonsView.as_view(), name='parent-extra-lessons'),
    path('child/<int:child_pk>/results/<int:term_id>/', views.ParentChildResultBookletView.as_view(), name='parent-child-result-booklet'),
]
