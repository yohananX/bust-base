from django.urls import path

from . import views

urlpatterns = [
    path('', views.ParentChildrenListView.as_view(), name='parent-children'),
    path('children/', views.ParentChildrenListView.as_view(), name='parent-children-list'),
    path('child/<int:pk>/', views.ParentChildDetailView.as_view(), name='parent-child-detail'),
    path('invoices/', views.ParentInvoicesView.as_view(), name='parent-invoices'),
    path('invoice/<int:pk>/', views.ParentInvoiceDetailView.as_view(), name='parent-invoice-detail'),
    path('child/<int:child_pk>/results/<int:term_id>/', views.ParentChildResultBookletView.as_view(), name='parent-child-result-booklet'),
    path('child/<int:child_pk>/results/<int:term_id>/download/', views.ParentChildResultDownloadView.as_view(), name='parent-child-result-download'),
]
