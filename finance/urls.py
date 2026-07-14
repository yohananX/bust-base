from django.urls import path
from . import views

app_name = "finance"

urlpatterns = [
    path("report/", views.FinancialReportView.as_view(), name="financial-report"),
]
