from .dashboard import DashboardView
from .students import (
    StudentListView, StudentCreateView, StudentDetailView,
    StudentEditView, StudentDeleteView, StudentChangeClassView,
    StudentPasswordChangeView,
    StudentGuardianLinkCreateView, StudentGuardianLinkDeleteView,
)
from .staff import StaffListView, StaffCreateView, StaffEditView, StaffToggleActiveView
from .classes import ClassListView, ClassCreateView, ClassEditView, ClassDeleteView
from .academics import (
    SubjectListView, SubjectCreateView, SubjectEditView, SubjectDeleteView,
    TeacherAssignmentListView, AssignmentDeleteView, AssignmentAddView, AssignmentSubjectsPartialView,
    ScoreAdminView,
)
from .fees import (
    FeeCategoryListView, FeeStructureListView,
    InvoiceListView, InvoiceDetailView, GenerateInvoicesView,
)
from .payroll import (
    PayGradeListView, AllowanceDeductionListView,
    PayrollRunListView, PayrollRunDetailView,
    GeneratePayrollView, RecordDisbursementView,
)
from .finance import (
    ProjectListView, ProjectDetailView,
    ExpenditureListView, FinancialReportView,
)
from .results import PublishResultsView, ResultReviewView
from .notifications import NotificationLogView
from .users import (
    UserListView, UserCreateView, UserEditView, UserToggleActiveView,
)
