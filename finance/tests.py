"""Comprehensive test suite for the finance module."""
from decimal import Decimal
from datetime import date, datetime

from django.test import TestCase
from django.db import IntegrityError
from django.utils import timezone
from django.contrib.auth import get_user_model

from core.models import School, AcademicSession, Term
from accounts.models import Roles
from fees.models import Payment, Invoice, FeeCategory, FeeStructure
from payroll.models import (
    SalaryDisbursement,
    PayrollRun,
    Payslip,
    StaffProfile,
    PayGrade,
)
from students.models import SchoolClass, Student, ClassEnrollment
from .models import Project, ExpenditureCategory, Expenditure


User = get_user_model()


class BaseFinanceTest(TestCase):
    """Common setup for all finance tests."""

    def setUp(self):
        # Create school
        self.school = School.objects.create(
            name="Test School",
            short_code="test",
        )

        # Create session and term
        self.session = AcademicSession.objects.create(
            school=self.school,
            name="2025/2026",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 8, 31),
            is_current=True,
        )
        self.term = Term.objects.create(
            school=self.school,
            session=self.session,
            name="First Term",
            start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 15),
            is_current=True,
        )

        # Create admin user (is_staff=True for admin access)
        self.admin_user = User.objects.create_user(
            username="admin1",
            email="admin@test.com",
            password="testpass123",
            school=self.school,
            role=Roles.ADMIN,
            is_staff=True, is_superuser=True,
            first_name="Admin",
            last_name="User",
        )

        # Create expenditure category
        self.cat_utilities = ExpenditureCategory.objects.create(
            school=self.school,
            name="Utilities",
        )
        self.cat_maintenance = ExpenditureCategory.objects.create(
            school=self.school,
            name="Maintenance",
        )


# ─── Project Model Tests ────────────────────────────────────────────────

class ProjectModelTest(BaseFinanceTest):
    def test_project_creation(self):
        """Test basic Project creation and string representation."""
        project = Project.objects.create(
            school=self.school,
            name="New Library Wing",
            description="Construction of a new library",
            target_amount=Decimal("5000000.00"),
            status=Project.Status.PROPOSED,
            created_by=self.admin_user,
        )
        self.assertEqual(str(project), "New Library Wing")
        self.assertEqual(project.school, self.school)
        self.assertEqual(project.status, Project.Status.PROPOSED)

    def test_project_status_choices(self):
        """All expected status choices exist."""
        expected = ["PROPOSED", "APPROVED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
        for status in expected:
            self.assertIn(status, [s[0] for s in Project.Status.choices])

    def test_project_with_no_expenditures(self):
        """Project with no expenditures — spent=0, remaining=target_amount."""
        project = Project.objects.create(
            school=self.school,
            name="Solar Panels",
            target_amount=Decimal("2000000.00"),
            status=Project.Status.APPROVED,
            created_by=self.admin_user,
        )
        self.assertEqual(project.spent, Decimal("0.00"))
        self.assertEqual(project.remaining, Decimal("2000000.00"))

    def test_project_spent_and_remaining_with_expenditures(self):
        """Create a project, add expenditures, verify spent and remaining."""
        project = Project.objects.create(
            school=self.school,
            name="Classroom Renovation",
            target_amount=Decimal("3000000.00"),
            status=Project.Status.IN_PROGRESS,
            created_by=self.admin_user,
        )

        Expenditure.objects.create(
            school=self.school,
            project=project,
            category=self.cat_maintenance,
            amount=Decimal("500000.00"),
            description="Paint and flooring",
            date=date(2025, 10, 1),
            recorded_by=self.admin_user,
        )
        Expenditure.objects.create(
            school=self.school,
            project=project,
            category=self.cat_maintenance,
            amount=Decimal("750000.00"),
            description="Furniture",
            date=date(2025, 10, 15),
            recorded_by=self.admin_user,
        )

        self.assertEqual(project.spent, Decimal("1250000.00"))
        self.assertEqual(project.remaining, Decimal("1750000.00"))

    def test_project_remaining_recomputes_after_target_change(self):
        """Change target_amount after expenditures — verify remaining recomputes, spent unchanged."""
        project = Project.objects.create(
            school=self.school,
            name="IT Upgrade",
            target_amount=Decimal("1000000.00"),
            status=Project.Status.APPROVED,
            created_by=self.admin_user,
        )

        Expenditure.objects.create(
            school=self.school,
            project=project,
            category=self.cat_utilities,
            amount=Decimal("200000.00"),
            description="New computers",
            date=date(2025, 11, 1),
            recorded_by=self.admin_user,
        )

        self.assertEqual(project.spent, Decimal("200000.00"))
        self.assertEqual(project.remaining, Decimal("800000.00"))

        # Change target_amount
        project.target_amount = Decimal("1500000.00")
        project.save()

        # spent should stay the same, remaining should recompute
        self.assertEqual(project.spent, Decimal("200000.00"))
        self.assertEqual(project.remaining, Decimal("1300000.00"))

    def test_project_multiple_expenditures_sum_correctly(self):
        """Multiple expenditures on the same project sum correctly."""
        project = Project.objects.create(
            school=self.school,
            name="Lab Equipment",
            target_amount=Decimal("4000000.00"),
            status=Project.Status.APPROVED,
            created_by=self.admin_user,
        )

        Expenditure.objects.create(
            school=self.school,
            project=project,
            category=self.cat_utilities,
            amount=Decimal("100000.00"),
            description="Microscopes",
            date=date(2025, 9, 1),
            recorded_by=self.admin_user,
        )
        Expenditure.objects.create(
            school=self.school,
            project=project,
            category=self.cat_utilities,
            amount=Decimal("250000.00"),
            description="Test tubes",
            date=date(2025, 9, 5),
            recorded_by=self.admin_user,
        )
        Expenditure.objects.create(
            school=self.school,
            project=project,
            category=self.cat_maintenance,
            amount=Decimal("50000.00"),
            description="Lab benches",
            date=date(2025, 9, 10),
            recorded_by=self.admin_user,
        )

        self.assertEqual(project.spent, Decimal("400000.00"))
        self.assertEqual(project.remaining, Decimal("3600000.00"))


# ─── ExpenditureCategory Model Tests ─────────────────────────────────────

class ExpenditureCategoryModelTest(BaseFinanceTest):
    def test_category_creation(self):
        """Test ExpenditureCategory creation."""
        cat = ExpenditureCategory.objects.create(
            school=self.school,
            name="Transport",
        )
        self.assertEqual(str(cat), "Transport")
        self.assertEqual(cat.school, self.school)

    def test_category_unique_per_school(self):
        """Test that duplicate category name within same school raises error."""
        with self.assertRaises(IntegrityError):
            ExpenditureCategory.objects.create(
                school=self.school,
                name="Utilities",  # already created in setUp
            )

    def test_same_category_name_different_schools(self):
        """Same category name allowed in different schools."""
        school2 = School.objects.create(name="Second School", short_code="second")
        cat2 = ExpenditureCategory.objects.create(
            school=school2,
            name="Utilities",
        )
        self.assertEqual(cat2.name, "Utilities")
        self.assertNotEqual(cat2.school, self.school)


# ─── Expenditure Model Tests ─────────────────────────────────────────────

class ExpenditureModelTest(BaseFinanceTest):
    def test_expenditure_tied_to_project_counts_toward_spent(self):
        """Expenditure tied to a project — verify it counts toward project.spent."""
        project = Project.objects.create(
            school=self.school,
            name="New Project",
            target_amount=Decimal("100000.00"),
            status=Project.Status.APPROVED,
            created_by=self.admin_user,
        )
        exp = Expenditure.objects.create(
            school=self.school,
            project=project,
            category=self.cat_utilities,
            amount=Decimal("25000.00"),
            description="Supplies",
            date=date(2025, 9, 1),
            recorded_by=self.admin_user,
        )
        self.assertEqual(project.spent, Decimal("25000.00"))
        self.assertIn(exp, project.expenditures.all())

    def test_expenditure_with_no_project(self):
        """Expenditure with NO project (general operational) — no error, doesn't affect any project."""
        exp = Expenditure.objects.create(
            school=self.school,
            project=None,
            category=self.cat_utilities,
            amount=Decimal("50000.00"),
            description="General utilities bill",
            date=date(2025, 9, 15),
            recorded_by=self.admin_user,
        )
        self.assertIsNone(exp.project)
        self.assertEqual(exp.amount, Decimal("50000.00"))

    def test_expenditure_null_project_requires_category(self):
        """Expenditure with null project still requires category."""
        exp = Expenditure(
            school=self.school,
            project=None,
            category=None,  # should fail validation
            amount=Decimal("10000.00"),
            description="No category",
            date=date(2025, 9, 1),
            recorded_by=self.admin_user,
        )
        with self.assertRaises(IntegrityError):
            exp.save()

    def test_expenditure_amount_positive(self):
        """Expenditure amount must be positive."""
        project = Project.objects.create(
            school=self.school,
            name="Test",
            target_amount=Decimal("100000.00"),
            status=Project.Status.APPROVED,
            created_by=self.admin_user,
        )
        exp = Expenditure(
            school=self.school,
            project=project,
            category=self.cat_utilities,
            amount=Decimal("-5000.00"),
            description="Negative amount",
            date=date(2025, 9, 1),
            recorded_by=self.admin_user,
        )
        with self.assertRaises(IntegrityError):
            exp.save()

    def test_expenditure_string_representation(self):
        """Test __str__ for expenditure with and without project."""
        project = Project.objects.create(
            school=self.school,
            name="Lab",
            target_amount=Decimal("500000.00"),
            status=Project.Status.APPROVED,
            created_by=self.admin_user,
        )
        exp_with_proj = Expenditure.objects.create(
            school=self.school,
            project=project,
            category=self.cat_utilities,
            amount=Decimal("10000.00"),
            description="Beakers",
            date=date(2025, 9, 1),
            recorded_by=self.admin_user,
        )
        self.assertIn("Beakers", str(exp_with_proj))
        self.assertIn("Lab", str(exp_with_proj))

        exp_no_proj = Expenditure.objects.create(
            school=self.school,
            project=None,
            category=self.cat_maintenance,
            amount=Decimal("5000.00"),
            description="Plumbing",
            date=date(2025, 9, 1),
            recorded_by=self.admin_user,
        )
        self.assertIn("Plumbing", str(exp_no_proj))
        self.assertNotIn("(", str(exp_no_proj))  # No project suffix


# ─── Expenditure with Project Relationship Tests ─────────────────────────

class ExpenditureProjectRelationTest(BaseFinanceTest):
    def test_expenditure_cascade_null_on_project_delete(self):
        """Expenditure.project set to NULL when referenced project is deleted."""
        project = Project.objects.create(
            school=self.school,
            name="Temp Project",
            target_amount=Decimal("100000.00"),
            status=Project.Status.PROPOSED,
            created_by=self.admin_user,
        )
        exp = Expenditure.objects.create(
            school=self.school,
            project=project,
            category=self.cat_utilities,
            amount=Decimal("10000.00"),
            description="Temp expense",
            date=date(2025, 9, 1),
            recorded_by=self.admin_user,
        )
        project.delete()
        exp.refresh_from_db()
        self.assertIsNone(exp.project)

    def test_expenditure_related_name_is_expenditures(self):
        """Verify related_name='expenditures' works on Project."""
        project = Project.objects.create(
            school=self.school,
            name="Verify Related Name",
            target_amount=Decimal("50000.00"),
            status=Project.Status.APPROVED,
            created_by=self.admin_user,
        )
        Expenditure.objects.create(
            school=self.school,
            project=project,
            category=self.cat_utilities,
            amount=Decimal("5000.00"),
            description="Test",
            date=date(2025, 9, 1),
            recorded_by=self.admin_user,
        )
        self.assertEqual(project.expenditures.count(), 1)

    def test_expenditure_related_name_on_category(self):
        """Verify related_name='expenditures' on ExpenditureCategory."""
        cat = self.cat_utilities
        Expenditure.objects.create(
            school=self.school,
            project=None,
            category=cat,
            amount=Decimal("3000.00"),
            description="Electric bill",
            date=date(2025, 9, 1),
            recorded_by=self.admin_user,
        )
        self.assertEqual(cat.expenditures.count(), 1)

    def test_expenditure_protects_category_deletion(self):
        """ExpenditureCategory cannot be deleted if expenditures reference it."""
        Expenditure.objects.create(
            school=self.school,
            project=None,
            category=self.cat_utilities,
            amount=Decimal("1000.00"),
            description="Water bill",
            date=date(2025, 9, 1),
            recorded_by=self.admin_user,
        )
        with self.assertRaises(IntegrityError):
            self.cat_utilities.delete()


# ─── Financial Report Tests ──────────────────────────────────────────────

class FinancialReportTest(BaseFinanceTest):
    def setUp(self):
        super().setUp()

        # Create student for invoice/payment
        self.school_class = SchoolClass.objects.create(
            school=self.school,
            name="JSS1A",
            level="JSS1",
        )
        self.student_user = User.objects.create_user(
            username="student1",
            email="student@test.com",
            password="testpass123",
            school=self.school,
            role=Roles.STUDENT,
        )
        self.student = Student.objects.create(
            school=self.school,
            user=self.student_user,
            admission_number="STU001",
            date_of_birth=date(2010, 1, 1),
            gender=Student.MALE,
            admission_date=date(2025, 9, 1),
            status=Student.ACTIVE,
        )
        ClassEnrollment.objects.create(
            school=self.school,
            student=self.student,
            school_class=self.school_class,
            session=self.session,
            is_current=True,
        )

        # Create invoice
        fee_cat = FeeCategory.objects.create(school=self.school, name="Tuition")
        self.invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal("100000.00"),
        )

        # Create staff profile and payroll data
        self.teacher_user = User.objects.create_user(
            username="teacher1",
            email="teacher@test.com",
            password="testpass123",
            school=self.school,
            role=Roles.TEACHER,
        )
        pay_grade = PayGrade.objects.create(
            school=self.school,
            name="Teacher",
            base_salary=Decimal("150000.00"),
        )
        self.staff = StaffProfile.objects.create(
            school=self.school,
            user=self.teacher_user,
            employee_id="EMP001",
            bank_name="Test Bank",
            bank_account_number="1234567890",
            bank_account_name="Teacher",
            hire_date=date(2020, 1, 1),
            status=StaffProfile.ACTIVE,
            pay_grade=pay_grade,
        )
        self.payroll_run = PayrollRun.objects.create(
            school=self.school,
            label="Test Run",
            period_start=date(2025, 9, 1),
            period_end=date(2025, 9, 30),
            pay_date=date(2025, 9, 30),
            generated_by=self.admin_user,
        )
        self.payslip = Payslip.objects.create(
            school=self.school,
            staff=self.staff,
            payroll_run=self.payroll_run,
            base_salary=Decimal("150000.00"),
            total_allowances=Decimal("0.00"),
            total_deductions=Decimal("0.00"),
            gross_pay=Decimal("150000.00"),
            net_pay=Decimal("150000.00"),
        )

    def _create_confirmed_payment(self, amount, day=1):
        """Helper to create a CONFIRMED fees payment on a specific day."""
        Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=amount,
            method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.make_aware(datetime(2025, 10, day, 10, 0, 0)),
            recorded_by=self.admin_user,
        )

    def _create_confirmed_salary(self, amount, day=1):
        """Helper to create a CONFIRMED salary disbursement on a specific day."""
        SalaryDisbursement.objects.create(
            school=self.school,
            payslip=self.payslip,
            amount=amount,
            method=SalaryDisbursement.Method.BANK_TRANSFER,
            reference=f"SAL-{day}",
            status=SalaryDisbursement.Status.CONFIRMED,
            disbursed_on=timezone.make_aware(datetime(2025, 10, day, 10, 0, 0)),
            recorded_by=self.admin_user,
        )

    def _create_expenditure(self, amount, day=1):
        """Helper to create an expenditure on a specific day."""
        Expenditure.objects.create(
            school=self.school,
            project=None,
            category=self.cat_utilities,
            amount=amount,
            description=f"Expense {day}",
            date=date(2025, 10, day),
            recorded_by=self.admin_user,
        )

    def test_report_math_is_correct(self):
        """CRITICAL: Hand-calculate and verify each section total."""
        # Known dataset:
        # Fees: 50000 + 30000 = 80000
        # Salaries: 100000 + 50000 = 150000
        # Expenditure: 20000 + 15000 = 35000
        # Net: 80000 - 150000 - 35000 = -105000

        self._create_confirmed_payment(Decimal("50000.00"), day=5)
        self._create_confirmed_payment(Decimal("30000.00"), day=10)

        self._create_confirmed_salary(Decimal("100000.00"), day=2)
        self._create_confirmed_salary(Decimal("50000.00"), day=15)

        self._create_expenditure(Decimal("20000.00"), day=3)
        self._create_expenditure(Decimal("15000.00"), day=12)

        # Login as admin and hit the report view
        self.client.force_login(self.admin_user)
        response = self.client.get(
            "/finance/report/",
            {"start_date": "2025-10-01", "end_date": "2025-10-31"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "80000.00")
        self.assertContains(response, "150000.00")
        self.assertContains(response, "35000.00")
        self.assertContains(response, "-105000.00")

    def test_report_defaults_to_current_term(self):
        """Report without date params defaults to current term."""
        self._create_confirmed_payment(Decimal("25000.00"), day=1)

        self.client.force_login(self.admin_user)
        response = self.client.get("/finance/report/")

        self.assertEqual(response.status_code, 200)
        # Current term is 2025-09-01 to 2025-12-15, so 25000.00 should appear
        self.assertContains(response, "25000.00")

    def test_report_outside_period_excludes_data(self):
        """Data outside the period should not appear."""
        self._create_confirmed_payment(Decimal("100000.00"), day=1)
        self._create_confirmed_salary(Decimal("50000.00"), day=1)
        self._create_expenditure(Decimal("10000.00"), day=1)

        self.client.force_login(self.admin_user)
        # Query a period before the data was created
        response = self.client.get(
            "/finance/report/",
            {"start_date": "2025-01-01", "end_date": "2025-06-30"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "0.00")

    def test_report_zero_data_returns_zeros(self):
        """Empty period returns zeros, not errors."""
        self.client.force_login(self.admin_user)
        response = self.client.get(
            "/finance/report/",
            {"start_date": "2025-01-01", "end_date": "2025-01-31"},
        )

        self.assertEqual(response.status_code, 200)
        # Should contain at least some 0.00 values
        self.assertContains(response, "0.00")

    def test_report_requires_admin_role(self):
        """Non-admin users get 403 or redirect."""
        teacher_user = User.objects.create_user(
            username="teacher2",
            email="teacher2@test.com",
            password="testpass123",
            school=self.school,
            role=Roles.TEACHER,
        )
        self.client.force_login(teacher_user)
        response = self.client.get("/finance/report/")
        self.assertEqual(response.status_code, 403)

    def test_report_net_negative_shown_correctly(self):
        """When expenses exceed income, net is displayed as negative."""
        self._create_confirmed_payment(Decimal("10000.00"), day=1)
        self._create_confirmed_salary(Decimal("50000.00"), day=1)
        self._create_expenditure(Decimal("20000.00"), day=1)

        self.client.force_login(self.admin_user)
        response = self.client.get(
            "/finance/report/",
            {"start_date": "2025-10-01", "end_date": "2025-10-31"},
        )

        self.assertEqual(response.status_code, 200)
        # Net = 10000 - 50000 - 20000 = -60000
        self.assertContains(response, "-60000.00")


# ─── Cross-School Isolation Tests ─────────────────────────────────────────

class CrossSchoolIsolationTest(BaseFinanceTest):
    def test_projects_isolated_by_school(self):
        """Projects from different schools are isolated."""
        school2 = School.objects.create(name="Second School", short_code="second")

        Project.objects.create(
            school=self.school,
            name="School 1 Project",
            target_amount=Decimal("100000.00"),
            status=Project.Status.PROPOSED,
            created_by=self.admin_user,
        )
        user2 = User.objects.create_user(
            username="admin2",
            email="admin2@test.com",
            password="testpass123",
            school=school2,
            role=Roles.ADMIN,
        )
        Project.objects.create(
            school=school2,
            name="School 2 Project",
            target_amount=Decimal("200000.00"),
            status=Project.Status.APPROVED,
            created_by=user2,
        )

        self.assertEqual(Project.objects.filter(school=self.school).count(), 1)
        self.assertEqual(Project.objects.filter(school=school2).count(), 1)

    def test_expenditures_isolated_by_school(self):
        """Expenditures from different schools don't leak."""
        school2 = School.objects.create(name="Second School", short_code="second")
        cat2 = ExpenditureCategory.objects.create(school=school2, name="Utilities")

        Expenditure.objects.create(
            school=self.school,
            project=None,
            category=self.cat_utilities,
            amount=Decimal("1000.00"),
            description="School 1 expense",
            date=date(2025, 9, 1),
            recorded_by=self.admin_user,
        )
        user2 = User.objects.create_user(
            username="admin3",
            email="admin3@test.com",
            password="testpass123",
            school=school2,
            role=Roles.ADMIN,
        )
        Expenditure.objects.create(
            school=school2,
            project=None,
            category=cat2,
            amount=Decimal("2000.00"),
            description="School 2 expense",
            date=date(2025, 9, 1),
            recorded_by=user2,
        )

        self.assertEqual(Expenditure.objects.filter(school=self.school).count(), 1)
        self.assertEqual(Expenditure.objects.filter(school=school2).count(), 1)


# ─── Decimal Enforcement Test ─────────────────────────────────────────────

class DecimalCheckTest(BaseFinanceTest):
    """CRITICAL: No FloatField anywhere in the finance app."""

    def test_no_float_in_finance_app(self):
        """Verify no float usage in finance models, views."""
        import os

        finance_dir = os.path.join(os.path.dirname(__file__))
        skip_files = {"tests.py"}
        skip_dirs = {"migrations", "__pycache__"}
        for root, dirs, files in os.walk(finance_dir):
            basename = os.path.basename(root)
            if basename in skip_dirs:
                continue
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                if filename in skip_files:
                    continue
                filepath = os.path.join(root, filename)
                with open(filepath, "r") as f:
                    content_lines = f.readlines()
                for i, line in enumerate(content_lines, 1):
                    stripped = line.strip()
                    if stripped.startswith("#") or not stripped:
                        continue
                    if "float" in stripped.lower():
                        self.fail(
                            f"FLOAT USAGE FOUND: {filename}:{i}: {stripped}"
                        )


# ─── Admin Tests ──────────────────────────────────────────────────────────

from django.test import override_settings


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class AdminTest(BaseFinanceTest):
    def test_project_admin_accessible(self):
        """Admin can access the project admin list."""
        self.client.force_login(self.admin_user)
        response = self.client.get("/admin/finance/project/")
        self.assertEqual(response.status_code, 200)

    def test_expenditure_admin_accessible(self):
        """Admin can access the expenditure admin list."""
        self.client.force_login(self.admin_user)
        response = self.client.get("/admin/finance/expenditure/")
        self.assertEqual(response.status_code, 200)

    def test_expenditure_category_admin_accessible(self):
        """Admin can access the category admin list."""
        self.client.force_login(self.admin_user)
        response = self.client.get("/admin/finance/expenditurecategory/")
        self.assertEqual(response.status_code, 200)
