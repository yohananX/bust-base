"""Portal-level multi-tenant leakage tests.

Two fully-populated schools (A and B); users of school A must never see or
mutate school B's data through any portal — including direct pk-probing of
URLs. Covers the admin, teacher, parent, student portals plus superuser
(school=None) behaviour.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Roles
from academics.models import Subject, TeacherAssignment
from core.models import AcademicSession, School, Term
from fees.models import Invoice, Payment
from finance.models import Expenditure, ExpenditureCategory, Project
from payroll.models import AllowanceDefinition, PayGrade
from students.models import (
    ClassEnrollment,
    SchoolClass,
    Student,
    StudentGuardianLink,
)


User = get_user_model()


def _make_school(code, name):
    return School.objects.create(name=name, short_code=code)


def _make_session_term(school):
    session = AcademicSession.objects.create(
        school=school,
        name='2025/2026',
        start_date=date(2025, 9, 1),
        end_date=date(2026, 8, 31),
        is_current=True,
    )
    term = Term.objects.create(
        school=school,
        session=session,
        name='First Term',
        start_date=date(2025, 9, 1),
        end_date=date(2025, 12, 15),
        is_current=True,
        results_published=True,
    )
    return session, term


class TwoSchoolsFixture(TestCase):
    """Shared fixture: school A (accessing) and school B (foreign data)."""

    def setUp(self):
        self.school_a = _make_school('school-a', 'School A')
        self.school_b = _make_school('school-b', 'School B')

        self.a = self._populate(self.school_a, 'a')
        self.b = self._populate(self.school_b, 'b')

        self.client.force_login(self.a['admin'])

    def _populate(self, school, tag):
        session, term = _make_session_term(school)

        admin = User.objects.create_user(
            username=f'admin_{tag}', email=f'admin_{tag}@test.edu',
            password='testpass123', school=school, role=Roles.ADMIN,
            first_name=f'Admin{tag.upper()}', last_name='User',
        )
        teacher = User.objects.create_user(
            username=f'teacher_{tag}', email=f'teacher_{tag}@test.edu',
            password='testpass123', school=school, role=Roles.TEACHER,
            first_name=f'Teacher{tag.upper()}', last_name='User',
        )
        parent = User.objects.create_user(
            username=f'parent_{tag}', email=f'parent_{tag}@test.edu',
            password='testpass123', school=school, role=Roles.PARENT,
            first_name=f'Parent{tag.upper()}', last_name='User',
        )
        student_user = User.objects.create_user(
            username=f'student_{tag}', email=f'student_{tag}@test.edu',
            password='testpass123', school=school, role=Roles.STUDENT,
            first_name=f'Student{tag.upper()}', last_name='User',
        )

        school_class = SchoolClass.objects.create(
            school=school, name=f'JSS1-{tag.upper()}', level='JSS1',
        )
        subject = Subject.objects.create(
            school=school, name=f'Maths {tag.upper()}', code=f'MTH-{tag.upper()}',
            school_class=school_class,
        )

        student = Student.objects.create(
            school=school, user=student_user,
            admission_number=f'STU-{tag.upper()}-001',
            date_of_birth=date(2011, 2, 3), gender=Student.MALE,
            admission_date=date(2025, 9, 1), status=Student.ACTIVE,
        )
        ClassEnrollment.objects.create(
            school=school, student=student, school_class=school_class,
            session=session, is_current=True,
        )
        StudentGuardianLink.objects.create(
            school=school, student=student, guardian=parent,
            relationship='Father', is_primary_contact=True,
        )

        assignment = TeacherAssignment.objects.create(
            school=school, teacher=teacher, subject=subject,
            school_class=school_class, session=session,
        )
        invoice = Invoice.objects.create(
            school=school, student=student, term=term,
            total_amount=Decimal('50000.00'),
        )

        return {
            'school': school,
            'session': session,
            'term': term,
            'admin': admin,
            'teacher': teacher,
            'parent': parent,
            'student_user': student_user,
            'student': student,
            'school_class': school_class,
            'subject': subject,
            'assignment': assignment,
            'invoice': invoice,
        }

    def login(self, user):
        self.client.force_login(user)


class AdminPortalLeakageTests(TwoSchoolsFixture):
    """School A admin must not see or touch school B data."""

    def test_student_list_hides_foreign_students(self):
        resp = self.client.get(reverse('school_admin:student_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'StudentA')
        self.assertNotContains(resp, 'StudentB')

    def test_student_detail_foreign_pk_404(self):
        resp = self.client.get(
            reverse('school_admin:student_detail', args=[self.b['student'].pk])
        )
        self.assertEqual(resp.status_code, 404)

    def test_invoice_detail_foreign_pk_404(self):
        resp = self.client.get(
            reverse('school_admin:invoice_detail', args=[self.b['invoice'].pk])
        )
        self.assertEqual(resp.status_code, 404)

    def test_record_cash_payment_foreign_invoice_404(self):
        """Admin of A must not be able to record cash against B's invoice."""
        foreign_invoice = self.b['invoice']
        resp = self.client.post(
            reverse('school_admin:invoice_detail', args=[foreign_invoice.pk]),
            data={'amount': '10000.00', 'method': 'CASH'},
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(
            Payment.objects.filter(invoice=foreign_invoice).count(), 0
        )

    def test_pending_transfer_confirm_foreign_404(self):
        """Confirming B's pending bank transfer from A's portal is a 404."""
        payment = Payment.objects.create(
            school=self.school_b,
            invoice=self.b['invoice'],
            student=self.b['student'],
            amount=Decimal('20000.00'),
            method=Payment.Method.BANK_TRANSFER,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )
        resp = self.client.post(
            reverse('school_admin:pending_transfer_confirm', args=[payment.pk])
        )
        self.assertEqual(resp.status_code, 404)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)

    def test_invoice_status_partial_foreign_pk_404(self):
        resp = self.client.get(
            reverse('fees:invoice-status-partial', args=[self.b['invoice'].pk])
        )
        self.assertEqual(resp.status_code, 404)

    def test_pending_transfers_hides_foreign_transfers(self):
        Payment.objects.create(
            school=self.school_b,
            invoice=self.b['invoice'],
            student=self.b['student'],
            amount=Decimal('20000.00'),
            method=Payment.Method.BANK_TRANSFER,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )
        resp = self.client.get(reverse('school_admin:pending_transfers'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'StudentB')

    def test_class_list_hides_foreign_classes(self):
        resp = self.client.get(reverse('school_admin:class_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'JSS1-A')
        self.assertNotContains(resp, 'JSS1-B')

    def test_subject_list_hides_foreign_subjects(self):
        resp = self.client.get(reverse('school_admin:subject_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Maths A')
        self.assertNotContains(resp, 'Maths B')

    def test_staff_list_hides_foreign_staff(self):
        resp = self.client.get(reverse('school_admin:staff_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'TeacherA')
        self.assertNotContains(resp, 'TeacherB')

    def test_parent_list_hides_foreign_parents(self):
        resp = self.client.get(reverse('school_admin:parent_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'ParentA')
        self.assertNotContains(resp, 'ParentB')

    def test_invoice_list_hides_foreign_invoices(self):
        resp = self.client.get(reverse('school_admin:invoice_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'StudentA User')
        self.assertNotContains(resp, 'StudentB User')

    def test_score_moderation_list_reachable(self):
        resp = self.client.get(reverse('school_admin:score_list'))
        self.assertEqual(resp.status_code, 200)

    def test_outstanding_fees_report_hides_foreign(self):
        resp = self.client.get(reverse('school_admin:outstanding_fees'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'STU-A-001')
        self.assertNotContains(resp, 'STU-B-001')

    def test_pay_grade_list_hides_foreign_grades(self):
        PayGrade.objects.create(
            school=self.school_b, name='Foreign Grade', base_salary=Decimal('90000.00'),
        )
        resp = self.client.get(reverse('school_admin:pay_grade_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Foreign Grade')

    def test_allowance_list_hides_foreign_allowances(self):
        AllowanceDefinition.objects.create(
            school=self.school_b, name='Foreign Allowance', amount=Decimal('5000.00'),
        )
        resp = self.client.get(reverse('school_admin:allowance_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Foreign Allowance')

    def test_project_list_hides_foreign_projects(self):
        Project.objects.create(
            school=self.school_b, name='Foreign Project',
            target_amount=Decimal('1000000.00'),
            created_by=self.a['admin'],
        )
        resp = self.client.get(reverse('finance:project_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Foreign Project')

    def test_expenditure_list_hides_foreign_expenditures(self):
        project = Project.objects.create(
            school=self.school_b, name='Foreign Project',
            target_amount=Decimal('1000000.00'),
            created_by=self.a['admin'],
        )
        category = ExpenditureCategory.objects.create(
            school=self.school_b, name='Foreign Category',
        )
        Expenditure.objects.create(
            school=self.school_b, project=project, category=category,
            amount=Decimal('10000.00'), recorded_by=self.a['admin'],
            date=date(2026, 1, 10),
        )
        resp = self.client.get(reverse('finance:expenditure_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Foreign Category')

    def test_financial_report_reachable(self):
        resp = self.client.get(reverse('finance:financial_report'))
        self.assertEqual(resp.status_code, 200)

    def test_subject_edit_foreign_pk_404(self):
        resp = self.client.get(
            reverse('school_admin:subject_edit', args=[self.b['subject'].pk])
        )
        self.assertEqual(resp.status_code, 404)

    def test_class_edit_foreign_pk_404(self):
        resp = self.client.get(
            reverse('school_admin:class_edit', args=[self.b['school_class'].pk])
        )
        self.assertEqual(resp.status_code, 404)

    def test_student_search_api_scoped(self):
        resp = self.client.get(
            reverse('school_admin:student_search_api'), {'q': 'Student'}
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        names = [row['name'] for row in payload]
        self.assertIn('StudentA User', names)
        self.assertNotIn('StudentB User', names)

    def test_invoice_search_api_scoped(self):
        resp = self.client.get(
            reverse('school_admin:invoice_search_api'), {'q': 'STU'}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'STU-B-001')


class TeacherPortalLeakageTests(TwoSchoolsFixture):
    """School A teacher must not see school B assignments/scores."""

    def test_score_grid_foreign_assignment_forbidden(self):
        self.login(self.a['teacher'])
        resp = self.client.get(
            reverse('score_grid', args=[self.b['assignment'].pk])
        )
        self.assertEqual(resp.status_code, 403)

    def test_assignment_list_hides_foreign_assignments(self):
        self.login(self.a['teacher'])
        resp = self.client.get(reverse('assignment_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Maths B')


class ParentPortalLeakageTests(TwoSchoolsFixture):
    """School A parent must not see school B children/invoices/results."""

    def setUp(self):
        super().setUp()
        self.login(self.a['parent'])

    def test_child_detail_foreign_pk_404(self):
        resp = self.client.get(
            reverse('parent-child-detail', args=[self.b['student'].pk])
        )
        self.assertEqual(resp.status_code, 404)

    def test_invoice_detail_foreign_pk_404(self):
        resp = self.client.get(
            reverse('parent-invoice-detail', args=[self.b['invoice'].pk])
        )
        self.assertEqual(resp.status_code, 404)

    def test_result_booklet_foreign_term_404(self):
        resp = self.client.get(
            reverse(
                'parent-child-result-booklet',
                args=[self.a['student'].pk, self.b['term'].pk],
            )
        )
        self.assertEqual(resp.status_code, 404)

    def test_pay_page_lists_only_own_children(self):
        resp = self.client.get(reverse('parent-pay'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'StudentA')
        self.assertNotContains(resp, 'StudentB')

    def test_invoice_json_foreign_pk_forbidden(self):
        """Parent of A must not fetch B's invoice JSON from the pay page."""
        resp = self.client.get(
            reverse('fees:invoice-detail', args=[self.b['invoice'].pk])
        )
        self.assertEqual(resp.status_code, 403)


class StudentPortalLeakageTests(TwoSchoolsFixture):
    """School A student must not see school B terms/invoices/results."""

    def setUp(self):
        super().setUp()
        self.login(self.a['student_user'])

    def test_result_booklet_foreign_term_404(self):
        resp = self.client.get(
            reverse('student-result-booklet', args=[self.b['term'].pk])
        )
        self.assertEqual(resp.status_code, 404)

    def test_results_history_hides_foreign_terms(self):
        resp = self.client.get(reverse('student-results-history'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, self.b['term'].name)

    def test_overview_hides_foreign_invoices(self):
        resp = self.client.get(reverse('student-overview'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'StudentB')

    def test_pay_page_hides_foreign_invoices(self):
        resp = self.client.get(reverse('student-pay'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'StudentB')

    def test_invoice_json_foreign_pk_forbidden(self):
        """Student of A must not fetch B's invoice JSON from the pay page."""
        resp = self.client.get(
            reverse('fees:invoice-detail', args=[self.b['invoice'].pk])
        )
        self.assertEqual(resp.status_code, 403)


class SuperuserBehaviourTests(TestCase):
    """request.school is None for superusers — they never see tenant data."""

    def setUp(self):
        self.school = _make_school('school-s', 'School S')
        self.session, self.term = _make_session_term(self.school)
        self.superuser = User.objects.create_superuser(
            username='root', email='root@test.edu', password='testpass123',
        )

    def test_middleware_sets_school_none_for_superuser(self):
        from django.test import RequestFactory
        from core.middleware import SchoolMiddleware

        request = RequestFactory().get('/')
        request.user = self.superuser
        SchoolMiddleware(lambda req: None)(request)
        self.assertIsNone(request.school)

    def test_superuser_not_redirected_from_secure_control_panel(self):
        self.client.force_login(self.superuser)
        resp = self.client.get('/secure-control-panel/')
        self.assertEqual(resp.status_code, 200)

    def test_school_admin_redirects_non_superuser_admins(self):
        admin = User.objects.create_user(
            username='admin_s', email='admin_s@test.edu',
            password='testpass123', school=self.school, role=Roles.ADMIN,
        )
        self.client.force_login(admin)
        resp = self.client.get('/secure-control-panel/')
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith('/school-admin/'))

    def test_superuser_blocked_from_school_admin_portal(self):
        """Superusers have role='' — RoleRequiredMixin rejects them (403).

        Documented behaviour: cross-school superadmins work through the Django
        admin (/secure-control-panel/) and are never granted the tenant portal.
        """
        self.client.force_login(self.superuser)
        resp = self.client.get(reverse('school_admin:student_list'))
        self.assertEqual(resp.status_code, 403)

    def test_superuser_blocked_from_parent_portal(self):
        self.client.force_login(self.superuser)
        resp = self.client.get(reverse('parent-children'))
        self.assertEqual(resp.status_code, 403)