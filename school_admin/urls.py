"""URL configuration for the School Admin Portal.

All views require the ADMIN role via RoleRequiredMixin.
"""
from django.urls import path

from data_import.views import (
    DataImportView, DataImportConfirmView, DataImportTemplateDownloadView,
)
from school_admin.views import (
    DashboardView,
    StudentListView, StudentCreateView, StudentDetailView,
    StudentEditView, StudentDeleteView, StudentChangeClassView,
    StudentGuardianLinkCreateView, StudentGuardianLinkDeleteView,
    StaffListView, StaffCreateView, StaffEditView, StaffToggleActiveView,
    ClassListView, ClassCreateView, ClassEditView, ClassDeleteView,
    SubjectListView, SubjectCreateView, SubjectEditView, SubjectDeleteView,
    TeacherAssignmentListView, ScoreAdminView,
    FeeCategoryListView, FeeStructureListView,
    InvoiceListView, InvoiceDetailView, GenerateInvoicesView,
    PayGradeListView, AllowanceDeductionListView,
    PayrollRunListView, PayrollRunDetailView,
    GeneratePayrollView, RecordDisbursementView,
    ProjectListView, ProjectDetailView,
    ExpenditureListView, FinancialReportView,
    PublishResultsView, ResultReviewView,
    NotificationLogView,
    UserListView, UserCreateView, UserEditView, UserToggleActiveView,
)

app_name = 'school_admin'

urlpatterns = [
    # Dashboard
    path('', DashboardView.as_view(), name='dashboard'),

    # Students
    path('students/', StudentListView.as_view(), name='student_list'),
    path('students/new/', StudentCreateView.as_view(), name='student_create'),
    path('students/<int:pk>/', StudentDetailView.as_view(), name='student_detail'),
    path('students/<int:pk>/edit/', StudentEditView.as_view(), name='student_edit'),
    path('students/<int:pk>/delete/', StudentDeleteView.as_view(), name='student_delete'),
    path('students/<int:pk>/change-class/', StudentChangeClassView.as_view(), name='student_change_class'),
    path('students/<int:pk>/add-guardian/', StudentGuardianLinkCreateView.as_view(), name='student_add_guardian'),
    path('students/guardian/<int:pk>/delete/', StudentGuardianLinkDeleteView.as_view(), name='student_delete_guardian'),

    # Staff
    path('staff/', StaffListView.as_view(), name='staff_list'),
    path('staff/new/', StaffCreateView.as_view(), name='staff_create'),
    path('staff/<int:pk>/edit/', StaffEditView.as_view(), name='staff_edit'),
    path('staff/<int:pk>/toggle-active/', StaffToggleActiveView.as_view(), name='staff_toggle_active'),

    # Academics
    path('subjects/', SubjectListView.as_view(), name='subject_list'),
    path('assignments/', TeacherAssignmentListView.as_view(), name='assignment_list'),
    path('scores/', ScoreAdminView.as_view(), name='score_list'),

    # Classes
    path('classes/', ClassListView.as_view(), name='class_list'),
    path('classes/new/', ClassCreateView.as_view(), name='class_create'),
    path('classes/<int:pk>/edit/', ClassEditView.as_view(), name='class_edit'),
    path('classes/<int:pk>/delete/', ClassDeleteView.as_view(), name='class_delete'),

    # Subjects
    path('subjects/new/', SubjectCreateView.as_view(), name='subject_create'),
    path('subjects/<int:pk>/edit/', SubjectEditView.as_view(), name='subject_edit'),
    path('subjects/<int:pk>/delete/', SubjectDeleteView.as_view(), name='subject_delete'),

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
    path('results/review/', ResultReviewView.as_view(), name='review_results'),

    # Notifications
    path('notifications/', NotificationLogView.as_view(), name='notification_log'),

    # User Management
    path('users/', UserListView.as_view(), name='user_list'),
    path('users/new/', UserCreateView.as_view(), name='user_create'),
    path('users/<int:pk>/edit/', UserEditView.as_view(), name='user_edit'),
    path('users/<int:pk>/toggle-active/', UserToggleActiveView.as_view(), name='user_toggle_active'),

    # Data Import
    path('import/', DataImportView.as_view(), name='import'),
    path('import/confirm/', DataImportConfirmView.as_view(), name='import_confirm'),
    path('import/template/<str:type>/', DataImportTemplateDownloadView.as_view(), name='import_template'),
]
