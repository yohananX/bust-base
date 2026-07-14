"""URL configuration for the School Admin Portal.

All views require the ADMIN role via RoleRequiredMixin.
"""
from django.urls import path

from school_admin.views import (
    DashboardView,
    StudentListView, StudentCreateView, StudentDetailView,
    StaffListView, StaffCreateView,
    SubjectListView, TeacherAssignmentListView, ScoreAdminView,
    FeeCategoryListView, FeeStructureListView,
    InvoiceListView, InvoiceDetailView, GenerateInvoicesView,
    PayGradeListView, AllowanceDeductionListView,
    PayrollRunListView, PayrollRunDetailView,
    GeneratePayrollView, RecordDisbursementView,
    ProjectListView, ProjectDetailView,
    ExpenditureListView, FinancialReportView,
    PublishResultsView,
    NotificationLogView,
)

app_name = 'school_admin'

urlpatterns = [
    # Dashboard
    path('', DashboardView.as_view(), name='dashboard'),

    # Students
    path('students/', StudentListView.as_view(), name='student_list'),
    path('students/new/', StudentCreateView.as_view(), name='student_create'),
    path('students/<int:pk>/', StudentDetailView.as_view(), name='student_detail'),

    # Staff
    path('staff/', StaffListView.as_view(), name='staff_list'),
    path('staff/new/', StaffCreateView.as_view(), name='staff_create'),

    # Academics
    path('subjects/', SubjectListView.as_view(), name='subject_list'),
    path('assignments/', TeacherAssignmentListView.as_view(), name='assignment_list'),
    path('scores/', ScoreAdminView.as_view(), name='score_list'),

    # Fees & Invoices
    path('fees/categories/', FeeCategoryListView.as_view(), name='fee_category_list'),
    path('fees/structures/', FeeStructureListView.as_view(), name='fee_structure_list'),
    path('invoices/', InvoiceListView.as_view(), name='invoice_list'),
    path('invoices/generate/', GenerateInvoicesView.as_view(), name='generate_invoices'),
    path('invoices/<int:pk>/', InvoiceDetailView.as_view(), name='invoice_detail'),

    # Payroll
    path('payroll/grades/', PayGradeListView.as_view(), name='pay_grade_list'),
    path('payroll/allowances/', AllowanceDeductionListView.as_view(), name='allowance_list'),
    path('payroll/runs/', PayrollRunListView.as_view(), name='payroll_run_list'),
    path('payroll/runs/generate/', GeneratePayrollView.as_view(), name='generate_payroll'),
    path('payroll/runs/<int:pk>/', PayrollRunDetailView.as_view(), name='payroll_run_detail'),
    path('payroll/disburse/<int:payslip_id>/', RecordDisbursementView.as_view(), name='record_disbursement'),

    # Finance
    path('finance/projects/', ProjectListView.as_view(), name='project_list'),
    path('finance/projects/<int:pk>/', ProjectDetailView.as_view(), name='project_detail'),
    path('finance/expenditures/', ExpenditureListView.as_view(), name='expenditure_list'),
    path('finance/report/', FinancialReportView.as_view(), name='financial_report'),

    # Results
    path('results/publish/', PublishResultsView.as_view(), name='publish_results'),

    # Notifications
    path('notifications/', NotificationLogView.as_view(), name='notification_log'),
]
