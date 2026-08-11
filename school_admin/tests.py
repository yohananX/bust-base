"""Tests for the School Admin portal views."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from decimal import Decimal

from core.models import School, AcademicSession, Term
from accounts.models import Roles
from students.models import SchoolClass, Student, ClassEnrollment
from fees.models import FeeCategory, Invoice, Payment


User = get_user_model()


class OutstandingFeesReportViewTest(TestCase):
    """Tests for the outstanding-fees report view."""

    def setUp(self):
        self.school = School.objects.create(
            name='Test School',
            short_code='test',
        )
        self.session = AcademicSession.objects.create(
            school=self.school,
            name='2025/2026',
            start_date=date(2025, 9, 1),
            end_date=date(2026, 8, 31),
            is_current=True,
        )
        self.term1 = Term.objects.create(
            school=self.school,
            session=self.session,
            name='First Term',
            start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 15),
            is_current=True,
        )
        self.term2 = Term.objects.create(
            school=self.school,
            session=self.session,
            name='Second Term',
            start_date=date(2026, 1, 5),
            end_date=date(2026, 4, 15),
        )

        self.admin_user = User.objects.create_user(
            username='admin1',
            email='admin@test.com',
            password='testpass123',
            school=self.school,
            role=Roles.ADMIN,
            first_name='Admin',
            last_name='User',
        )

        self.class_a = SchoolClass.objects.create(
            school=self.school, name='JSS1A', level='JSS1',
        )
        self.class_b = SchoolClass.objects.create(
            school=self.school, name='JSS2A', level='JSS2',
        )

        # Student 1 (JSS1A) — partial payer in term1
        self.s1 = self._make_student('student1', 'John', 'Doe', 'STU001', self.class_a)
        # Student 2 (JSS2A) — fully unpaid in term1 + term2
        self.s2 = self._make_student('student2', 'Jane', 'Roe', 'STU002', self.class_b)
        # Student 3 (JSS1A) — fully paid, must never appear
        self.s3 = self._make_student('student3', 'Sam', 'Smith', 'STU003', self.class_a)

        self.inv1 = self._make_invoice(self.s1, self.term1, '100000.00')
        self.inv2 = self._make_invoice(self.s2, self.term1, '80000.00')
        self.inv3 = self._make_invoice(self.s3, self.term1, '50000.00')
        self.inv4 = self._make_invoice(self.s2, self.term2, '20000.00')

        # Student 1 pays 30000 of 100000 (partial)
        self._make_payment(self.inv1, '30000.00')
        # Student 3 pays in full (paid)
        self._make_payment(self.inv3, '50000.00')

    # ── helpers ──────────────────────────────────────────────────────────

    def _make_student(self, username, first, last, admission, school_class):
        user = User.objects.create_user(
            username=username,
            email=f'{username}@test.com',
            password='testpass123',
            school=self.school,
            role=Roles.STUDENT,
            first_name=first,
            last_name=last,
        )
        student = Student.objects.create(
            school=self.school,
            user=user,
            admission_number=admission,
            date_of_birth=date(2010, 1, 1),
            gender=Student.MALE,
            admission_date=date(2025, 9, 1),
            status=Student.ACTIVE,
        )
        ClassEnrollment.objects.create(
            school=self.school,
            student=student,
            school_class=school_class,
            session=self.session,
            is_current=True,
        )
        return student

    def _make_invoice(self, student, term, amount):
        return Invoice.objects.create(
            school=self.school,
            student=student,
            term=term,
            total_amount=Decimal(amount),
        )

    def _make_payment(self, invoice, amount):
        Payment.objects.create(
            school=self.school,
            invoice=invoice,
            amount=Decimal(amount),
            method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )

    def _get(self, **params):
        self.client.force_login(self.admin_user)
        return self.client.get('/school-admin/fees/outstanding/', params)

    # ── tests ────────────────────────────────────────────────────────────

    def test_default_scope_is_current_term(self):
        """Without params, the report defaults to the current term (term1)."""
        response = self._get()
        self.assertEqual(response.status_code, 200)
        ctx = response.context
        self.assertEqual(ctx['selected_term'], self.term1)
        self.assertEqual(ctx['total_outstanding'], Decimal('150000.00'))
        self.assertEqual(ctx['students_owing'], 2)
        self.assertEqual(ctx['unpaid_count'], 1)
        self.assertEqual(ctx['partial_count'], 1)
        self.assertEqual(ctx['total_collected'], Decimal('30000.00'))

    def test_debtor_table_excludes_fully_paid_and_orders_by_balance(self):
        """Only balance>0 invoices appear, sorted by balance descending."""
        response = self._get()
        debtors = response.context['debtors']
        self.assertEqual(len(debtors), 2)
        self.assertEqual(debtors[0]['student'], 'Jane Roe')  # 80000 balance
        self.assertEqual(debtors[1]['student'], 'John Doe')  # 70000 balance
        self.assertNotIn('Sam Smith', [d['student'] for d in debtors])
        # statuses computed from annotations
        self.assertEqual(debtors[0]['status'], 'UNPAID')
        self.assertEqual(debtors[1]['status'], 'PARTIAL')

    def test_by_class_breakdown(self):
        """By-class breakdown groups correctly and orders by total desc."""
        response = self._get()
        by_class = list(response.context['by_class'])
        # JSS2A (80000) before JSS1A (70000)
        self.assertEqual(by_class[0]['student__enrollments__school_class__name'], 'JSS2A')
        self.assertEqual(by_class[0]['total'], Decimal('80000.00'))
        self.assertEqual(by_class[1]['student__enrollments__school_class__name'], 'JSS1A')
        self.assertEqual(by_class[1]['total'], Decimal('70000.00'))
        self.assertEqual(by_class[0]['students'], 1)

    def test_all_terms_shows_by_term_breakdown(self):
        """term_id=all disables the current-term default and shows by-term."""
        response = self._get(term_id='all')
        self.assertEqual(response.status_code, 200)
        ctx = response.context
        self.assertIsNone(ctx['selected_term'])
        self.assertEqual(ctx['total_outstanding'], Decimal('170000.00'))
        by_term = list(ctx['by_term'])
        self.assertEqual(len(by_term), 2)
        totals = {row['term__name']: row['total'] for row in by_term}
        self.assertEqual(totals['First Term'], Decimal('150000.00'))
        self.assertEqual(totals['Second Term'], Decimal('20000.00'))

    def test_status_filter(self):
        """status filter narrows to UNPAID or PARTIAL only."""
        unpaid = self._get(status='UNPAID')
        self.assertEqual(len(unpaid.context['debtors']), 1)
        self.assertEqual(unpaid.context['debtors'][0]['student'], 'Jane Roe')

        partial = self._get(status='PARTIAL')
        self.assertEqual(len(partial.context['debtors']), 1)
        self.assertEqual(partial.context['debtors'][0]['student'], 'John Doe')

    def test_class_filter(self):
        """class_id filter restricts to that class."""
        response = self._get(class_id=str(self.class_a.pk))
        debtors = response.context['debtors']
        self.assertEqual(len(debtors), 1)
        self.assertEqual(debtors[0]['student'], 'John Doe')
        self.assertEqual(response.context['total_outstanding'], Decimal('70000.00'))

    def test_search_filter(self):
        """q searches student name or admission number."""
        by_name = self._get(q='Jane')
        self.assertEqual(len(by_name.context['debtors']), 1)
        self.assertEqual(by_name.context['debtors'][0]['student'], 'Jane Roe')

        by_admission = self._get(q='STU001')
        self.assertEqual(len(by_admission.context['debtors']), 1)
        self.assertEqual(by_admission.context['debtors'][0]['student'], 'John Doe')

    def test_cross_school_isolation(self):
        """A second school's outstanding fees never appear."""
        school2 = School.objects.create(name='Second School', short_code='second')
        user2 = User.objects.create_user(
            username='s2student',
            email='s2@test.com',
            password='testpass123',
            school=school2,
            role=Roles.STUDENT,
            first_name='Other',
            last_name='Kid',
        )
        class2 = SchoolClass.objects.create(school=school2, name='P1A', level='P1')
        student2 = Student.objects.create(
            school=school2,
            user=user2,
            admission_number='STU999',
            date_of_birth=date(2010, 1, 1),
            gender=Student.MALE,
            admission_date=date(2025, 9, 1),
            status=Student.ACTIVE,
        )
        ClassEnrollment.objects.create(
            school=school2,
            student=student2,
            school_class=class2,
            session=self.session,
            is_current=True,
        )
        Invoice.objects.create(
            school=school2,
            student=student2,
            term=self.term1,
            total_amount=Decimal('999999.00'),
        )

        response = self._get()
        self.assertEqual(response.context['total_outstanding'], Decimal('150000.00'))
        self.assertEqual(len(response.context['debtors']), 2)
        self.assertNotIn('Other Kid', [d['student'] for d in response.context['debtors']])

    def test_csv_export_matches_filtered_view(self):
        """?export=csv returns a CSV matching the current filters."""
        response = self._get(export='csv')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        content = response.content.decode()
        lines = content.strip().splitlines()
        self.assertEqual(
            lines[0],
            'Student,Admission No,Class,Term,Total (NGN),Paid (NGN),Balance (NGN),Status,Age Bucket',
        )
        # header + 2 debtors
        self.assertEqual(len(lines), 3)
        self.assertIn('Jane Roe', content)
        self.assertIn('80000', content)
        self.assertIn('UNPAID', content)
        self.assertNotIn('Sam Smith', content)

    def test_csv_export_respects_filters(self):
        """CSV respects the status filter like the HTML view."""
        response = self._get(export='csv', status='PARTIAL')
        lines = response.content.decode().strip().splitlines()
        self.assertEqual(len(lines), 2)  # header + 1 debtor
        self.assertIn('John Doe', response.content.decode())

    def test_report_requires_admin_role(self):
        """Non-admin users get 403."""
        teacher = User.objects.create_user(
            username='teacher1',
            email='teacher@test.com',
            password='testpass123',
            school=self.school,
            role=Roles.TEACHER,
        )
        self.client.force_login(teacher)
        response = self.client.get('/school-admin/fees/outstanding/')
        self.assertEqual(response.status_code, 403)
