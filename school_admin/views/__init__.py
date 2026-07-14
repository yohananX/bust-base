from .dashboard import DashboardView
from .students import (
    StudentListView, StudentCreateView, StudentDetailView,
    StudentGuardianLinkCreateView, StudentGuardianLinkDeleteView,
)
from .staff import StaffListView, StaffCreateView
from .academics import SubjectListView, TeacherAssignmentListView, ScoreAdminView
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
from .results import PublishResultsView
from .notifications import NotificationLogView
from .users import (
    UserListView, UserCreateView, UserEditView, UserToggleActiveView,
)
