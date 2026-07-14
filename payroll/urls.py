from django.urls import path
from . import views

app_name = 'payroll'

urlpatterns = [
    path('payslips/', views.PayslipListView.as_view(), name='payslip-list'),
    path('payslip/<int:payslip_id>/', views.payslip_detail, name='payslip-detail'),
    path('run/<int:pk>/', views.PayrollRunDetailView.as_view(), name='payroll-run-detail'),
]
