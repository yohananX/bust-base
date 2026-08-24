"""Tests for the School Admin portal views."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal

from core.models import School, AcademicSession, Term
from accounts.models import Roles
from academics.models import Score, Subject, TeacherAssignment, TermResult
from students.models import SchoolClass, Student, ClassEnrollment, StudentGuardianLink
from fees.models import FeeCategory, FeeStructure, Invoice, Payment


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


class FlowReproTest(TestCase):
    """Repro checks for guardian linking and staff-create redirect."""

    def setUp(self):
        self.school = School.objects.create(name='Repro School', short_code='repro')
        self.session = AcademicSession.objects.create(
            school=self.school, name='2026/2027',
            start_date=date(2026, 9, 1), end_date=date(2027, 8, 31), is_current=True,
        )
        self.term = Term.objects.create(
            school=self.school, session=self.session, name='First Term',
            start_date=date(2026, 9, 1), end_date=date(2026, 12, 15), is_current=True,
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school, name='JSS1', level='JSS1',
        )
        self.tuition_cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', is_compulsory=True,
        )
        FeeStructure.objects.create(
            school=self.school, school_class=self.school_class,
            term=self.term, category=self.tuition_cat, amount=Decimal('54000.00'),
        )
        self.admin = User.objects.create_user(
            username='adminx', email='adminx@test.com', password='pass123',
            school=self.school, role=Roles.ADMIN, first_name='Admin', last_name='X',
        )
        self.parent1 = User.objects.create_user(
            username='parent1', email='p1@test.com', password='pass123',
            school=self.school, role=Roles.PARENT, first_name='Papa', last_name='One',
        )
        self.parent2 = User.objects.create_user(
            username='parent2', email='p2@test.com', password='pass123',
            school=self.school, role=Roles.PARENT, first_name='Mama', last_name='Two',
        )
        self.student_user = User.objects.create_user(
            username='stud1', email='s@test.com', password='pass123',
            school=self.school, role=Roles.STUDENT, first_name='Kid', last_name='One',
        )
        self.student = Student.objects.create(
            school=self.school, user=self.student_user, admission_number='S001',
            date_of_birth=date(2012, 1, 1), gender='MALE',
            admission_date=date(2026, 9, 1), status='ACTIVE',
        )
        StudentGuardianLink.objects.create(
            school=self.school, student=self.student, guardian=self.parent1,
            relationship='FATHER', is_primary_contact=True,
        )

    def test_link_second_guardian(self):
        self.client.login(username='adminx', password='pass123')
        resp = self.client.post(reverse('school_admin:student_add_guardian', args=[self.student.pk]), {
            'student_id': self.student.pk,
            'guardian_id': self.parent2.pk,
            'relationship': 'MOTHER',
            'is_primary_contact': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        links = StudentGuardianLink.objects.filter(student=self.student)
        self.assertEqual(links.count(), 2)
        primary = links.filter(is_primary_contact=True)
        self.assertEqual(primary.count(), 1)
        self.assertEqual(primary.first().guardian, self.parent2)

    def test_staff_create_redirects_to_assignments(self):
        self.client.login(username='adminx', password='pass123')
        resp = self.client.post(reverse('school_admin:staff_create'), {
            'first_name': 'Tee', 'last_name': 'Cher',
            'phone_number': '08012345678', 'email': 't@test.com', 'role': 'TEACHER',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/school-admin/assignments/', resp.url)
        self.assertIn('teacher_id=', resp.url)

    def test_staff_create_auto_generates_username(self):
        self.client.login(username='adminx', password='pass123')
        resp = self.client.post(reverse('school_admin:staff_create'), {
            'username': 'ignored-input',
            'first_name': 'Grace', 'last_name': 'House',
            'phone_number': '08011112222', 'role': 'ADMIN',
        })
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(email='', first_name='Grace', last_name='House')
        self.assertEqual(user.username, 'grace.house')
        self.assertEqual(user.role, Roles.ADMIN)

    def test_staff_create_uniquifies_duplicate_names(self):
        User.objects.create_user(
            username='john.doe', email='jd@test.com', password='pass123',
            school=self.school, role=Roles.TEACHER,
        )
        self.client.login(username='adminx', password='pass123')
        resp = self.client.post(reverse('school_admin:staff_create'), {
            'first_name': 'John', 'last_name': 'Doe',
            'phone_number': '08033334444', 'role': 'TEACHER',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(username='john.doe1').exists())

    def test_student_create_creates_new_user(self):
        self.client.login(username='adminx', password='pass123')
        resp = self.client.post(reverse('school_admin:student_create'), {
            'first_name': 'New', 'last_name': 'Kid',
            'admission_number': 'S002',
            'date_of_birth': '2013-05-05', 'gender': 'FEMALE',
            'admission_date': '2026-09-01', 'status': 'ACTIVE',
            'class_id': self.school_class.pk,
            'session_id': self.session.pk,
        })
        self.assertEqual(resp.status_code, 302)
        student = Student.objects.get(admission_number='S002')
        self.assertEqual(student.user.first_name, 'New')
        self.assertEqual(student.user.role, Roles.STUDENT)
        self.assertTrue(
            ClassEnrollment.objects.filter(student=student, is_current=True).exists()
        )
        invoice = Invoice.objects.filter(student=student).first()
        self.assertIsNotNone(invoice, 'expected an auto-generated invoice')
        self.assertEqual(invoice.total_amount, Decimal('54000.00'))
        self.assertEqual(invoice.line_items.count(), 1)
        resp = self.client.get(reverse('school_admin:student_create'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'user_mode')
        self.assertNotContains(resp, 'existing-user-section')


class PaymentAdminActionsTest(TestCase):
    """Admin payment recording, editing and deletion (school_admin portal)."""

    def setUp(self):
        self.school = School.objects.create(name='Test School', short_code='test')
        self.session = AcademicSession.objects.create(
            school=self.school, name='2025/2026',
            start_date=date(2025, 9, 1), end_date=date(2026, 8, 31),
            is_current=True,
        )
        self.term = Term.objects.create(
            school=self.school, session=self.session, name='First Term',
            start_date=date(2025, 9, 1), end_date=date(2025, 12, 15),
            is_current=True,
        )
        self.admin_user = User.objects.create_user(
            username='admin1', email='admin@test.com', password='testpass123',
            school=self.school, role=Roles.ADMIN,
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school, name='JSS1A', level='JSS1',
        )
        self.student = self._make_student('student1', 'John', 'Doe', 'STU001')
        self.invoice = Invoice.objects.create(
            school=self.school, student=self.student, term=self.term,
            total_amount=Decimal('60000.00'),
        )

    def _make_student(self, username, first, last, admission):
        user = User.objects.create_user(
            username=username, email=f'{username}@test.com', password='testpass123',
            school=self.school, role=Roles.STUDENT, first_name=first, last_name=last,
        )
        student = Student.objects.create(
            school=self.school, user=user, admission_number=admission,
            date_of_birth=date(2010, 1, 1), gender=Student.MALE,
            admission_date=date(2025, 9, 1), status=Student.ACTIVE,
        )
        ClassEnrollment.objects.create(
            school=self.school, student=student, school_class=self.school_class,
            session=self.session, is_current=True,
        )
        return student

    def test_invoice_detail_records_payment_with_method_and_payer(self):
        """The invoice page records a POS payment with payer details."""
        self.client.force_login(self.admin_user)
        resp = self.client.post(
            reverse('school_admin:invoice_detail', kwargs={'pk': self.invoice.pk}),
            {
                'amount': '25000.00',
                'method': 'POS',
                'paid_by_name': 'Uncle Emeka',
                'paid_by_relation': 'Uncle',
                'reference': 'POS-001',
            },
        )
        self.assertEqual(resp.status_code, 302)
        payment = Payment.objects.get(invoice=self.invoice)
        self.assertEqual(payment.method, Payment.Method.POS)
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)
        self.assertEqual(payment.paid_by_name, 'Uncle Emeka')
        self.assertEqual(payment.paid_by_relation, 'Uncle')
        self.assertEqual(self.invoice.balance, Decimal('35000.00'))

    def test_record_payment_without_invoice(self):
        """A payment can be recorded against a student with no invoice."""
        self.client.force_login(self.admin_user)
        resp = self.client.post(
            reverse('school_admin:student_record_payment', kwargs={'pk': self.student.pk}),
            {
                'amount': '5000.00',
                'method': 'CHEQUE',
                'paid_by_name': 'Sponsor Fund',
                'description': 'Books',
            },
        )
        self.assertEqual(resp.status_code, 302)
        payment = Payment.objects.get(student=self.student, invoice__isnull=True)
        self.assertEqual(payment.method, Payment.Method.CHEQUE)
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)
        self.assertEqual(payment.description, 'Books')
        self.assertIsNotNone(payment.receipt)

    def test_record_payment_attaches_to_invoice(self):
        """An invoice-id in the record form links the payment to that invoice."""
        self.client.force_login(self.admin_user)
        resp = self.client.post(
            reverse('school_admin:student_record_payment', kwargs={'pk': self.student.pk}),
            {'amount': '10000.00', 'method': 'CASH', 'invoice_id': str(self.invoice.pk)},
        )
        self.assertEqual(resp.status_code, 302)
        payment = Payment.objects.get(invoice=self.invoice)
        self.assertEqual(self.invoice.balance, Decimal('50000.00'))

    def test_edit_payment_updates_amount_method_and_payer(self):
        """A wrongly recorded payment can be corrected."""
        payment = Payment.objects.create(
            school=self.school, invoice=self.invoice, student=self.student,
            amount=Decimal('10000.00'), method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED, paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )
        self.client.force_login(self.admin_user)
        resp = self.client.post(
            reverse('school_admin:payment_edit', kwargs={'pk': payment.pk}),
            {
                'amount': '15000.00',
                'method': 'POS',
                'paid_by_name': 'Ada',
                'paid_by_relation': 'Mother',
                'reference': '',
            },
        )
        self.assertEqual(resp.status_code, 302)
        payment.refresh_from_db()
        self.assertEqual(payment.amount, Decimal('15000.00'))
        self.assertEqual(payment.method, Payment.Method.POS)
        self.assertEqual(payment.paid_by_name, 'Ada')
        self.assertEqual(self.invoice.balance, Decimal('45000.00'))

    def test_delete_payment_restores_balance(self):
        """Deleting a wrong payment restores the invoice balance."""
        payment = Payment.objects.create(
            school=self.school, invoice=self.invoice, student=self.student,
            amount=Decimal('20000.00'), method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED, paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )
        self.client.force_login(self.admin_user)
        resp = self.client.post(
            reverse('school_admin:payment_delete', kwargs={'pk': payment.pk}),
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Payment.objects.filter(pk=payment.pk).exists())
        self.assertEqual(self.invoice.balance, Decimal('60000.00'))

    def test_edit_and_delete_require_admin(self):
        """Non-admins cannot edit or delete payments."""
        teacher = User.objects.create_user(
            username='teacher1', email='t@test.com', password='testpass123',
            school=self.school, role=Roles.TEACHER,
        )
        payment = Payment.objects.create(
            school=self.school, invoice=self.invoice, student=self.student,
            amount=Decimal('10000.00'), method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED, paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )
        self.client.force_login(teacher)
        resp = self.client.post(
            reverse('school_admin:payment_edit', kwargs={'pk': payment.pk}),
            {'amount': '99999.00', 'method': 'CASH'},
        )
        self.assertEqual(resp.status_code, 403)
        payment.refresh_from_db()
        self.assertEqual(payment.amount, Decimal('10000.00'))

class ResultModerationViewTests(TestCase):
    """Moderation workflow (item 29): role enforcement + automatic ranking
    recomputation when scores are approved or rejected."""

    def setUp(self):
        self.school = School.objects.create(
            name='Moderation Academy', short_code='moderate',
        )
        self.session = AcademicSession.objects.create(
            school=self.school, name='2025/2026',
            start_date=date(2025, 9, 1), end_date=date(2026, 8, 31),
            is_current=True,
        )
        self.term = Term.objects.create(
            school=self.school, session=self.session,
            name='First Term', start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 15), is_current=True,
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school, name='JSS1A', level='JSS1',
        )
        self.subject = Subject.objects.create(
            school=self.school, name='Mathematics', code='MTH', pass_mark=40,
        )
        self.admin_user = User.objects.create_user(
            username='admin1', email='admin@test.com', password='testpass123',
            school=self.school, role=Roles.ADMIN,
        )
        self.teacher_user = User.objects.create_user(
            username='teacher1', email='teacher@test.com', password='testpass123',
            school=self.school, role=Roles.TEACHER,
        )
        TeacherAssignment.objects.create(
            school=self.school, teacher=self.teacher_user,
            subject=self.subject, school_class=self.school_class,
            session=self.session,
        )

    def _make_student(self, username, admission_number):
        user = User.objects.create_user(
            username=username, email=f'{username}@test.com',
            password='testpass123', school=self.school, role=Roles.STUDENT,
        )
        student = Student.objects.create(
            school=self.school, user=user,
            admission_number=admission_number, date_of_birth=date(2010, 1, 1),
            gender=Student.MALE, admission_date=date(2025, 9, 1),
        )
        ClassEnrollment.objects.create(
            school=self.school, student=student,
            school_class=self.school_class, session=self.session,
            is_current=True,
        )
        return student

    def _score(self, student, total_test, status=Score.MODERATION_PENDING):
        return Score.objects.create(
            school=self.school, student=student, subject=self.subject,
            term=self.term, test_1=total_test, test_2=5, test_3=5,
            exam_score=50, entered_by=self.teacher_user,
            moderation_status=status,
        )

    def test_only_admin_can_moderate(self):
        """Teachers (or anyone else) cannot approve/reject scores."""
        student = self._make_student('stu_a', 'A001')
        score = self._score(student, 8)

        self.client.force_login(self.teacher_user)
        resp = self.client.post(reverse('school_admin:review_results'), {
            'score_id': score.pk, 'action': 'approve',
            'term_id': self.term.pk, 'class_id': self.school_class.pk,
        })
        self.assertEqual(resp.status_code, 403)
        score.refresh_from_db()
        self.assertEqual(score.moderation_status, Score.MODERATION_PENDING)

    def test_approve_recomputes_positions_and_term_summaries(self):
        """Approving scores immediately re-ranks the class and builds TermResult."""
        stu_a = self._make_student('stu_a', 'B001')
        stu_b = self._make_student('stu_b', 'B002')
        score_a = self._score(stu_a, 8)   # total 68
        score_b = self._score(stu_b, 10)  # total 70

        self.client.force_login(self.admin_user)
        resp = self.client.post(reverse('school_admin:review_results'), {
            'score_id': score_a.pk, 'action': 'approve',
            'term_id': self.term.pk, 'class_id': self.school_class.pk,
        })
        self.assertEqual(resp.status_code, 302)
        resp = self.client.post(reverse('school_admin:review_results'), {
            'score_id': score_b.pk, 'action': 'approve',
            'term_id': self.term.pk, 'class_id': self.school_class.pk,
        })
        self.assertEqual(resp.status_code, 302)

        score_a.refresh_from_db()
        score_b.refresh_from_db()
        self.assertEqual(score_a.moderation_status, Score.MODERATION_APPROVED)
        self.assertEqual(score_b.moderation_status, Score.MODERATION_APPROVED)
        # Rejected scores never rank: B (70) first, A (68) second
        self.assertEqual(score_a.position, 2)
        self.assertEqual(score_b.position, 1)
        tr_a = TermResult.objects.get(student=stu_a, term=self.term)
        self.assertEqual(tr_a.grand_total, 68)
        self.assertEqual(tr_a.overall_position, 2)

    def test_reject_clears_position_and_updates_summary(self):
        """Rejecting a score drops it from rankings and the term summary."""
        stu_a = self._make_student('stu_a', 'C001')
        stu_b = self._make_student('stu_b', 'C002')
        score_a = self._score(stu_a, 8)
        score_b = self._score(stu_b, 10)

        self.client.force_login(self.admin_user)
        for score in (score_a, score_b):
            self.client.post(reverse('school_admin:review_results'), {
                'score_id': score.pk, 'action': 'approve',
                'term_id': self.term.pk, 'class_id': self.school_class.pk,
            })

        # Reject the higher scorer
        self.client.post(reverse('school_admin:review_results'), {
            'score_id': score_b.pk, 'action': 'reject',
            'term_id': self.term.pk, 'class_id': self.school_class.pk,
        })

        score_a.refresh_from_db()
        score_b.refresh_from_db()
        self.assertEqual(score_b.moderation_status, Score.MODERATION_REJECTED)
        self.assertIsNone(score_b.position)
        self.assertEqual(score_a.position, 1)
        # B's stale TermResult must be gone; A keeps theirs
        self.assertTrue(TermResult.objects.filter(student=stu_a, term=self.term).exists())
        self.assertFalse(TermResult.objects.filter(student=stu_b, term=self.term).exists())

    def test_approve_all_recomputes(self):
        """Bulk approval re-ranks everything in one pass."""
        stu_a = self._make_student('stu_a', 'D001')
        stu_b = self._make_student('stu_b', 'D002')
        self._score(stu_a, 8)
        self._score(stu_b, 10)

        self.client.force_login(self.admin_user)
        resp = self.client.post(reverse('school_admin:review_results'), {
            'action': 'approve_all',
            'term_id': self.term.pk, 'class_id': self.school_class.pk,
        })
        self.assertEqual(resp.status_code, 302)

        positions = dict(
            Score.objects.filter(term=self.term).values_list(
                'student__user__username', 'position',
            )
        )
        self.assertEqual(positions['stu_a'], 2)
        self.assertEqual(positions['stu_b'], 1)
        self.assertEqual(
            TermResult.objects.filter(term=self.term).count(), 2,
        )


class FirstLoginPasswordFlagTests(TestCase):
    """Every generated/reset password must set must_change_password (item 49)."""

    def setUp(self):
        self.school = School.objects.create(name='Flag School', short_code='flags')
        self.session = AcademicSession.objects.create(
            school=self.school, name='2026/2027',
            start_date=date(2026, 9, 1), end_date=date(2027, 8, 31), is_current=True,
        )
        self.term = Term.objects.create(
            school=self.school, session=self.session, name='First Term',
            start_date=date(2026, 9, 1), end_date=date(2026, 12, 15), is_current=True,
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school, name='JSS1', level='JSS1',
        )
        self.admin = User.objects.create_user(
            username='flagadmin', email='flagadmin@test.com', password='pass123',
            school=self.school, role=Roles.ADMIN,
        )
        self.student_user = User.objects.create_user(
            username='flagstud', email='flagstud@test.com', password='pass123',
            school=self.school, role=Roles.STUDENT,
        )
        self.student = Student.objects.create(
            school=self.school, user=self.student_user, admission_number='S001',
            date_of_birth=date(2012, 1, 1), gender='MALE',
            admission_date=date(2026, 9, 1), status='ACTIVE',
        )
        self.client.login(username='flagadmin', password='pass123')

    def test_student_create_sets_flag(self):
        resp = self.client.post(reverse('school_admin:student_create'), {
            'first_name': 'New', 'last_name': 'Kid',
            'admission_number': 'S002',
            'date_of_birth': '2013-05-05', 'gender': 'FEMALE',
            'admission_date': '2026-09-01', 'status': 'ACTIVE',
            'class_id': self.school_class.pk,
            'session_id': self.session.pk,
        })
        self.assertEqual(resp.status_code, 302)
        student = Student.objects.get(admission_number='S002')
        self.assertTrue(student.user.must_change_password)

    def test_parent_create_sets_flag(self):
        resp = self.client.post(reverse('school_admin:student_create'), {
            'first_name': 'New', 'last_name': 'Kid',
            'admission_number': 'S003',
            'date_of_birth': '2013-05-05', 'gender': 'FEMALE',
            'admission_date': '2026-09-01', 'status': 'ACTIVE',
            'class_id': self.school_class.pk,
            'session_id': self.session.pk,
            'parent_name': 'Mama New',
            'parent_email': 'mama.new@test.com', 'parent_phone': '08000000000',
        })
        self.assertEqual(resp.status_code, 302)
        parent = User.objects.get(email='mama.new@test.com')
        self.assertTrue(parent.must_change_password)

    def test_batch_reset_sets_flag(self):
        self.student_user.must_change_password = False
        self.student_user.save(update_fields=['must_change_password'])
        resp = self.client.post(reverse('school_admin:credential_batch'), {'group': 'students'})
        self.assertEqual(resp.status_code, 302)
        self.student_user.refresh_from_db()
        self.assertTrue(self.student_user.must_change_password)

    def test_single_reset_sets_flag(self):
        self.student_user.must_change_password = False
        self.student_user.save(update_fields=['must_change_password'])
        resp = self.client.post(
            reverse('school_admin:credential_single_reset', args=[self.student_user.pk]),
        )
        self.assertEqual(resp.status_code, 302)
        self.student_user.refresh_from_db()
        self.assertTrue(self.student_user.must_change_password)

    def test_admin_password_change_sets_flag(self):
        self.student_user.must_change_password = False
        self.student_user.save(update_fields=['must_change_password'])
        resp = self.client.post(
            reverse('school_admin:student_password_change', args=[self.student.pk]),
            {'action': 'auto_generate'},
        )
        self.assertEqual(resp.status_code, 302)
        self.student_user.refresh_from_db()
        self.assertTrue(self.student_user.must_change_password)
class StudentDetailReceiptTests(TestCase):
    """Admins see receipt links for every confirmed payment on the
    student detail page — including invoice-less payments."""

    def setUp(self):
        self.school = School.objects.create(
            name='Grace House School', short_code='grace-house',
        )
        self.admin_user = User.objects.create_user(
            username='admin', email='admin@test.com', password='testpass123',
            school=self.school, role=Roles.ADMIN,
        )
        self.session = AcademicSession.objects.create(
            school=self.school, name='2025/2026',
            start_date=date(2025, 9, 1), end_date=date(2026, 8, 31),
            is_current=True,
        )
        self.term = Term.objects.create(
            school=self.school, session=self.session, name='First Term',
            start_date=date(2025, 9, 1), end_date=date(2025, 12, 15),
            is_current=True,
        )
        student_user = User.objects.create_user(
            username='student', email='student@test.com', password='testpass123',
            school=self.school, role=Roles.STUDENT,
            first_name='Ada', last_name='Lovelace',
        )
        self.student = Student.objects.create(
            school=self.school, user=student_user,
            admission_number='STU-RCPT-001',
            date_of_birth=date(2010, 1, 1), gender=Student.MALE,
            admission_date=date(2025, 9, 1), status=Student.ACTIVE,
        )

    def _confirmed_payment(self, **kwargs):
        return Payment.objects.create(
            school=self.school,
            student=self.student,
            amount=Decimal('25000.00'),
            method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            recorded_by=self.admin_user,
            **kwargs,
        )

    def test_invoice_receipt_links_rendered(self):
        invoice = Invoice.objects.create(
            school=self.school, student=self.student, term=self.term,
            total_amount=Decimal('50000.00'),
        )
        payment = self._confirmed_payment(
            invoice=invoice, reference='INV-REF-001',
        )
        self.client.force_login(self.admin_user)
        resp = self.client.get(reverse('school_admin:student_detail', args=[self.student.pk]))
        self.assertEqual(resp.status_code, 200)
        receipt_url = reverse('fees:payment-receipt', args=[payment.pk])
        self.assertContains(resp, receipt_url)
        self.assertContains(resp, 'INV-REF-001')

    def test_invoice_less_payment_panel_with_receipt(self):
        payment = self._confirmed_payment(reference='STU-RCPT-A1')
        self.client.force_login(self.admin_user)
        resp = self.client.get(reverse('school_admin:student_detail', args=[self.student.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Payments (no invoice)')
        receipt_url = reverse('fees:payment-receipt', args=[payment.pk])
        self.assertContains(resp, receipt_url)
        self.assertContains(resp, 'STU-RCPT-A1')

    def test_pending_payment_has_no_receipt_link(self):
        pending = Payment.objects.create(
            school=self.school,
            student=self.student,
            amount=Decimal('25000.00'),
            method=Payment.Method.BANK_TRANSFER,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )
        self.client.force_login(self.admin_user)
        resp = self.client.get(reverse('school_admin:student_detail', args=[self.student.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(
            resp, reverse('fees:payment-receipt', args=[pending.pk])
        )
        self.assertContains(resp, 'Pending')

    def test_receipt_page_accessible_to_admin(self):
        """Admins can open the receipt page directly for a confirmed payment."""
        payment = self._confirmed_payment(reference='ADM-OPEN-001')
        self.client.force_login(self.admin_user)
        resp = self.client.get(reverse('fees:payment-receipt', args=[payment.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'ADM-OPEN-001')


class StudentMiddleNameTests(TestCase):
    """Students with multiple names keep their middle name end-to-end."""

    def setUp(self):
        self.school = School.objects.create(name='MNS School', short_code='mns')
        self.session = AcademicSession.objects.create(
            school=self.school, name='2026/2027',
            start_date=date(2026, 9, 1), end_date=date(2027, 8, 31), is_current=True,
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school, name='JSS1', level='JSS1',
        )
        self.admin_user = User.objects.create_user(
            username='mnsadmin', email='mns@test.com', password='pass123',
            school=self.school, role=Roles.ADMIN, first_name='Admin', last_name='MNS',
        )
        self.student_user = User.objects.create_user(
            username='mnsstud', email='mnsstud@test.com', password='pass123',
            school=self.school, role=Roles.STUDENT,
            first_name='Kid', last_name='One',
        )
        self.student = Student.objects.create(
            school=self.school, user=self.student_user, admission_number='M001',
            date_of_birth=date(2012, 1, 1), gender='MALE',
            admission_date=date(2026, 9, 1), status='ACTIVE',
        )

    def test_student_create_saves_middle_name(self):
        self.client.force_login(self.admin_user)
        resp = self.client.post(reverse('school_admin:student_create'), {
            'first_name': 'New', 'middle_name': 'Paul', 'last_name': 'Kid',
            'admission_number': 'M002',
            'date_of_birth': '2013-05-05', 'gender': 'FEMALE',
            'admission_date': '2026-09-01', 'status': 'ACTIVE',
            'class_id': self.school_class.pk,
            'session_id': self.session.pk,
        })
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(username='new.kid')
        self.assertEqual(user.middle_name, 'Paul')
        self.assertEqual(user.get_full_name(), 'New Paul Kid')

    def test_student_create_without_middle_name(self):
        self.client.force_login(self.admin_user)
        resp = self.client.post(reverse('school_admin:student_create'), {
            'first_name': 'No', 'middle_name': '', 'last_name': 'Middle',
            'admission_number': 'M003',
            'date_of_birth': '2013-05-05', 'gender': 'MALE',
            'admission_date': '2026-09-01', 'status': 'ACTIVE',
            'class_id': self.school_class.pk,
            'session_id': self.session.pk,
        })
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(username='no.middle')
        self.assertEqual(user.middle_name, '')
        self.assertEqual(user.get_full_name(), 'No Middle')

    def test_student_edit_updates_middle_name(self):
        self.client.force_login(self.admin_user)
        resp = self.client.post(reverse('school_admin:student_edit', args=[self.student.pk]), {
            'user_first_name': 'Kid', 'user_middle_name': 'Ade', 'user_last_name': 'One',
            'user_email': 'mnsstud@test.com', 'user_phone_number': '',
            'admission_number': 'M001',
            'date_of_birth': '2012-01-01', 'gender': 'MALE',
            'admission_date': '2026-09-01', 'status': 'ACTIVE',
        })
        self.assertEqual(resp.status_code, 302)
        self.student_user.refresh_from_db()
        self.assertEqual(self.student_user.middle_name, 'Ade')
        self.assertEqual(self.student_user.get_full_name(), 'Kid Ade One')

    def test_edit_form_renders_current_middle_name(self):
        self.student_user.middle_name = 'Ade'
        self.student_user.save(update_fields=['middle_name'])
        self.client.force_login(self.admin_user)
        resp = self.client.get(reverse('school_admin:student_edit', args=[self.student.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp,
            'name="user_middle_name" value="Ade"',
            html=False,
        )
