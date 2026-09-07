from .dashboard import DashboardView
from .students import (
    StudentListView, StudentCreateView, StudentDetailView,
    StudentEditView, StudentDeleteView, StudentChangeClassView,
    StudentPasswordChangeView,
    StudentGuardianCreateView, StudentGuardianLinkDeleteView, StudentGuardianUpdateView,
)
from .staff import StaffListView, StaffCreateView, StaffEditView, StaffToggleActiveView, StaffDeleteView
from .parents import ParentListView
from .classes import ClassListView, ClassCreateView, ClassEditView, ClassDeleteView, ClassDetailView, ClassSubjectAddView, ClassSubjectCreateView, ClassSubjectRemoveView, ClassSubjectBulkAddView
from .academics import (
    SubjectListView,
    TeacherAssignmentListView, AssignmentDeleteView, AssignmentAddView, AssignmentSubjectsPartialView,
    ScoreAdminView,
)
from .fee_categories import (
    FeeCategoryListView, FeeCategoryCreateView, FeeCategoryEditView,
    FeeCategoryDeleteView,
)
from .fee_pricing import (
    FeePricingListView, FeePricingCreateView,
    FeePricingEditView, FeePricingDeleteView, FeePricingBulkCopyView, FeePricingPromoteView,
)
from .invoices import (
    InvoiceListView, InvoiceDetailView, GenerateInvoicesView,
    OutstandingFeesReportView,
    PendingTransfersView, PendingTransferConfirmView, PendingTransferRejectView,
    PaymentEditView, PaymentDeleteView, StudentRecordPaymentView,
)
from .payroll import (
    PayGradeListView, AllowanceDeductionListView,
    PayrollRunListView, PayrollRunDetailView,
    GeneratePayrollView, RecordDisbursementView,
)
from .results import PublishResultsView, ResultReviewView
from .sessions import (
    SessionListView, SessionCreateView, SessionSetCurrentView, TermSetCurrentView,
)
from .school_settings import SchoolSettingsView
from .notifications import NotificationLogView
from .credentials import (
    CredentialSlipView, CredentialBatchView, CredentialBatchPrintView,
    CredentialSingleResetView, CredentialMemberConfirmView,
)
from .search import (
    StudentSearchAPIView, StaffSearchAPIView, MemberSearchAPIView,
    InvoiceSearchAPIView, ClassSearchAPIView, SubjectSearchAPIView,
    NotificationSearchAPIView, EnrollmentSearchAPIView, GuardianSearchAPIView,
)
