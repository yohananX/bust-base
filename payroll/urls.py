from django.urls import path
from . import views

app_name = 'payroll'

urlpatterns = [
    path('api/payslip/<int:payslip_id>/', views.payslip_detail, name='payslip-detail'),
    path('api/my-payslips/', views.my_payslips, name='my-payslips'),
    path('api/run/<int:run_id>/', views.payroll_run_detail, name='payroll-run-detail'),
]
