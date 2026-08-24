"""URL configuration for the Finance portal (mounted under /school-admin/).

All views require the ADMIN role via RoleRequiredMixin.
"""
from django.urls import path

from .views import (
    ProjectListView, ProjectDetailView,
    ExpenditureListView, FinancialReportView,
)

app_name = 'finance'

urlpatterns = [
    path('finance/projects/', ProjectListView.as_view(), name='project_list'),
    path('finance/projects/<int:pk>/', ProjectDetailView.as_view(), name='project_detail'),
    path('finance/expenditures/', ExpenditureListView.as_view(), name='expenditure_list'),
    path('finance/report/', FinancialReportView.as_view(), name='financial_report'),
]