"""URL configuration for CSV data import (mounted under /school-admin/import/).

All views require the ADMIN role via RoleRequiredMixin.
"""
from django.urls import path

from .views import (
    DataImportView, DataImportConfirmView, DataImportTemplateDownloadView,
)

app_name = 'data_import'

urlpatterns = [
    path('', DataImportView.as_view(), name='import'),
    path('confirm/', DataImportConfirmView.as_view(), name='import_confirm'),
    path('template/<str:type>/', DataImportTemplateDownloadView.as_view(), name='import_template'),
]