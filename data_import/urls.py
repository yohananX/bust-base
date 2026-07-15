from django.urls import path

from data_import.views import (
    DataImportView,
    DataImportConfirmView,
    DataImportTemplateDownloadView,
)

app_name = 'data_import'

urlpatterns = [
    path('', DataImportView.as_view(), name='import'),
    path('confirm/', DataImportConfirmView.as_view(), name='import_confirm'),
    path('template/<str:type>/', DataImportTemplateDownloadView.as_view(), name='import_template'),
]
