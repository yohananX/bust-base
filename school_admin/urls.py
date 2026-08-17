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
    StudentPasswordChangeView,
    StudentGuardianLinkCreateView, StudentGuardianLinkDeleteView,
    StaffListView, StaffCreateView, StaffEditView, StaffToggleActiveView,
    ClassListView, ClassCreateView, ClassEditView, ClassDeleteView,
    SubjectListView, SubjectCreateView, SubjectEditView, SubjectDeleteView,
    TeacherAssignmentListView, AssignmentDeleteView, AssignmentAddView, AssignmentSubjectsPartialView,
    ScoreAdminView,
    FeeCategoryListView, FeeCategoryCreateView, FeeCategoryEditView,
    FeeCategoryDeleteView, FeePricingListView, FeePricingCreateView,
    FeePricingEditView, FeePricingDeleteView,
    InvoiceListView, InvoiceDetailView, GenerateInvoicesView,
    OutstandingFeesReportView,
    PendingTransfersView, PendingTransferConfirmView, PendingTransferRejectView,
    PaymentEditView, PaymentDeleteView, StudentRecordPaymentView,
    PayGradeListView, AllowanceDeductionListView,
    PayrollRunListView, PayrollRunDetailView,
    GeneratePayrollView, RecordDisbursementView,
    ProjectListView, ProjectDetailView,
    ExpenditureListView, FinancialReportView,
    PublishResultsView, ResultReviewView,
    SessionListView, SessionCreateView, SessionSetCurrentView, TermSetCurrentView,
    SchoolSettingsView,
    NotificationLogView,
    UserListView, UserCreateView, UserEditView, UserToggleActiveView,
    CredentialSlipView, CredentialBatchView, CredentialBatchPrintView, CredentialSingleResetView,
    CredentialMemberConfirmView,
    StudentSearchAPIView, StaffSearchAPIView, UserSearchAPIView, MemberSearchAPIView,
    InvoiceSearchAPIView, ClassSearchAPIView, SubjectSearchAPIView,
    NotificationSearchAPIView,
)

app_name = 'school_admin'

urlpatterns = [
    # Dashboard
    path('', DashboardView.as_view(), name='dashboard'),

    # Students
    path('students/', StudentListView.as_view(), name='student_list'),
    path('api/students/', StudentSearchAPIView.as_view(), name='student_search_api'),
    path('api/staff/', StaffSearchAPIView.as_view(), name='staff_search_api'),
    path('api/users/', UserSearchAPIView.as_view(), name='user_search_api'),
    path('api/members/', MemberSearchAPIView.as_view(), name='member_search_api'),
    path('api/invoices/', InvoiceSearchAPIView.as_view(), name='invoice_search_api'),
    path('api/classes/', ClassSearchAPIView.as_view(), name='class_search_api'),
    path('api/subjects/', SubjectSearchAPIView.as_view(), name='subject_search_api'),
    path('api/notifications/', NotificationSearchAPIView.as_view(), name='notification_search_api'),
    path('students/new/', StudentCreateView.as_view(), name='student_create'),
    path('students/<int:pk>/', StudentDetailView.as_view(), name='student_detail'),
    path('students/<int:pk>/edit/', StudentEditView.as_view(), name='student_edit'),
    path('students/<int:pk>/delete/', StudentDeleteView.as_view(), name='student_delete'),
    path('students/<int:pk>/change-password/', StudentPasswordChangeView.as_view(), name='student_password_change'),
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
    path('assignments/delete/<int:pk>/', AssignmentDeleteView.as_view(), name='assignment_delete'),
    path('assignments/add/', AssignmentAddView.as_view(), name='assignment_add'),
    path('assignments/subjects/', AssignmentSubjectsPartialView.as_view(), name='assignment_subjects'),
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
    path('fees/categories/new/', FeeCategoryCreateView.as_view(), name='fee_category_create'),
    path('fees/categories/<int:pk>/edit/', FeeCategoryEditView.as_view(), name='fee_category_edit'),
    path('fees/categories/<int:pk>/delete/', FeeCategoryDeleteView.as_view(), name='fee_category_delete'),
    path('fees/', FeePricingListView.as_view(), name='fee_pricing_list'),
    path('fees/new/', FeePricingCreateView.as_view(), name='fee_pricing_create'),
    path('fees/<int:pk>/edit/', FeePricingEditView.as_view(), name='fee_pricing_edit'),
    path('fees/<int:pk>/delete/', FeePricingDeleteView.as_view(), name='fee_pricing_delete'),
    path('fees/outstanding/', OutstandingFeesReportView.as_view(), name='outstanding_fees'),
    path('fees/pending/', PendingTransfersView.as_view(), name='pending_transfers'),
    path('fees/pending/<int:pk>/confirm/', PendingTransferConfirmView.as_view(), name='pending_transfer_confirm'),
    path('fees/pending/<int:pk>/reject/', PendingTransferRejectView.as_view(), name='pending_transfer_reject'),
path('fees/payments/<int:pk>/edit/', PaymentEditView.as_view(), name='payment_edit'),
path('fees/payments/<int:pk>/delete/', PaymentDeleteView.as_view(), name='payment_delete'),
path('students/<int:pk>/record-payment/', StudentRecordPaymentView.as_view(), name='student_record_payment'),
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

    # Sessions & Terms
    path('sessions/', SessionListView.as_view(), name='session_list'),
    path('sessions/new/', SessionCreateView.as_view(), name='session_create'),
    path('sessions/<int:pk>/current/', SessionSetCurrentView.as_view(), name='session_set_current'),
    path('sessions/terms/<int:pk>/current/', TermSetCurrentView.as_view(), name='term_set_current'),

    # School Settings
    path('settings/', SchoolSettingsView.as_view(), name='school_settings'),

    # User Management
    path('users/', UserListView.as_view(), name='user_list'),
    path('users/new/', UserCreateView.as_view(), name='user_create'),
    path('users/<int:pk>/edit/', UserEditView.as_view(), name='user_edit'),
    path('users/<int:pk>/toggle-active/', UserToggleActiveView.as_view(), name='user_toggle_active'),

    # Credential Slips
    path('credentials/user/<int:pk>/', CredentialSlipView.as_view(), name='credential_slip'),
    path('credentials/batch/', CredentialBatchView.as_view(), name='credential_batch'),
    path('credentials/print/', CredentialBatchPrintView.as_view(), name='credential_batch_print'),
    path('credentials/user/<int:pk>/reset/', CredentialSingleResetView.as_view(), name='credential_single_reset'),
    path('credentials/member/<int:pk>/', CredentialMemberConfirmView.as_view(), name='credential_member_confirm'),

    # Data Import
    path('import/', DataImportView.as_view(), name='import'),
    path('import/confirm/', DataImportConfirmView.as_view(), name='import_confirm'),
    path('import/template/<str:type>/', DataImportTemplateDownloadView.as_view(), name='import_template'),
]
