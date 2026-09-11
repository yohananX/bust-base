"""Tests for the School Admin portal views."""
from datetime import date

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal

from core.models import School, AcademicSession, Term
from accounts.models import Roles
from academics.models import Score, Subject, ClassSubject, TeacherAssignment, TermResult
from students.models import SchoolClass, Student, ClassEnrollment, StudentGuardianLink
from fees.models import FeeCategory, FeePrice, Invoice, Payment
from payroll.models import StaffProfile


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
        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_CLASS, school_class=self.school_class,
            term=self.term, category=self.tuition_cat, amount=Decimal('54000.00'),
            student_type='ALL',
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
        resp = self.client.post(
            reverse('school_admin:student_add_guardian', args=[self.student.pk]),
            {
                'guardian_first_name': 'Mama',
                'guardian_last_name': 'Two',
                'guardian_email': 'mama2@test.com',
                'guardian_phone_number': '0802',
                'relationship': 'MOTHER',
                'is_primary_contact': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        links = StudentGuardianLink.objects.filter(student=self.student)
        self.assertEqual(links.count(), 2)
        primary = links.filter(is_primary_contact=True)
        self.assertEqual(primary.count(), 1)
        self.assertEqual(primary.first().guardian.first_name, 'Mama')

    def test_student_create_with_multiple_guardians(self):
        self.client.login(username='adminx', password='pass123')
        resp = self.client.post(reverse('school_admin:student_create'), {
            'first_name': 'Multi', 'last_name': 'Kid',
            'date_of_birth': '2013-05-05', 'gender': 'FEMALE',
            'admission_date': '2026-09-01', 'status': 'ACTIVE',
            'class_id': self.school_class.pk,
            'session_id': self.session.pk,
            'guardian_0_name': 'Papa One',
            'guardian_0_email': 'papa1@test.com',
            'guardian_0_phone': '0801',
            'guardian_0_relationship': 'FATHER',
            'guardian_0_occupation': 'Engineer',
            'guardian_0_address': '1 Main St',
            'guardian_0_authorized_pickup_person': 'Driver A',
            'guardian_1_name': 'Mama Two',
            'guardian_1_email': 'mama2@test.com',
            'guardian_1_phone': '0802',
            'guardian_1_relationship': 'MOTHER',
            'guardian_1_occupation': 'Doctor',
            'guardian_1_address': '2 Main St',
            'guardian_1_authorized_pickup_person': 'Driver B',
        })
        self.assertEqual(resp.status_code, 302)
        student = Student.objects.get(user__first_name='Multi')
        links = StudentGuardianLink.objects.filter(student=student)
        self.assertEqual(links.count(), 2)
        names = sorted([link.guardian.get_full_name() for link in links])
        self.assertEqual(names, ['Mama Two', 'Papa One'])

    def test_edit_guardian_updates_details(self):
        link = StudentGuardianLink.objects.create(
            school=self.school, student=self.student, guardian=self.parent2,
            relationship='MOTHER', is_primary_contact=False,
            occupation='Nurse', address='12 Main St', authorized_pickup_person='',
        )
        self.client.login(username='adminx', password='pass123')
        resp = self.client.post(
            reverse('school_admin:student_edit_guardian', args=[link.pk]),
            {
                'guardian_first_name': 'Mama',
                'guardian_last_name': 'Two',
                'guardian_email': 'mama2@test.com',
                'guardian_phone_number': '0802',
                'relationship': 'MOTHER',
                'guardian_occupation': 'Doctor',
                'guardian_address': '45 Broad St',
                'guardian_authorized_pickup_person': 'Uncle Emeka',
                'is_primary_contact': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        link.refresh_from_db()
        self.parent2.refresh_from_db()
        self.assertEqual(self.parent2.phone_number, '0802')
        self.assertEqual(link.occupation, 'Doctor')
        self.assertEqual(link.address, '45 Broad St')
        self.assertEqual(link.authorized_pickup_person, 'Uncle Emeka')
        self.assertTrue(link.is_primary_contact)

    def test_edit_guardian_detail_page_renders_edit_button(self):
        link = StudentGuardianLink.objects.create(
            school=self.school, student=self.student, guardian=self.parent2,
            relationship='MOTHER', is_primary_contact=False,
        )
        self.client.login(username='adminx', password='pass123')
        resp = self.client.get(reverse('school_admin:student_detail', args=[self.student.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'edit-guardian-btn')
        self.assertContains(resp, str(link.pk))

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
            'date_of_birth': '2013-05-05', 'gender': 'FEMALE',
            'admission_date': '2026-09-01', 'status': 'ACTIVE',
            'class_id': self.school_class.pk,
            'session_id': self.session.pk,
        })
        self.assertEqual(resp.status_code, 302)
        student = Student.objects.get(user__first_name='New', user__last_name='Kid')
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

    def test_guardian_search_api_returns_matching_parents(self):
        self.client.login(username='adminx', password='pass123')
        resp = self.client.get(reverse('school_admin:guardian_search_api'), {'q': 'Papa'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        names = [item['name'] for item in data]
        self.assertIn('Papa One', names)

    def test_guardian_search_api_scoped_to_school(self):
        other_school = School.objects.create(name='Other School', short_code='other')
        User.objects.create_user(
            username='other_parent', email='other@test.com', password='pass123',
            school=other_school, role=Roles.PARENT, first_name='Other', last_name='Parent',
        )
        self.client.login(username='adminx', password='pass123')
        resp = self.client.get(reverse('school_admin:guardian_search_api'), {'q': 'Parent'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 0)

    def test_student_create_warns_on_reused_guardian_email(self):
        self.client.login(username='adminx', password='pass123')
        resp = self.client.post(reverse('school_admin:student_create'), {
            'first_name': 'Second', 'last_name': 'Kid',
            'date_of_birth': '2014-06-06', 'gender': 'MALE',
            'admission_date': '2026-09-01', 'status': 'ACTIVE',
            'class_id': self.school_class.pk,
            'session_id': self.session.pk,
            'guardian_0_name': 'Papa One',
            'guardian_0_email': self.parent1.email,
            'guardian_0_phone': '0801',
            'guardian_0_relationship': 'FATHER',
        })
        self.assertEqual(resp.status_code, 302)
        messages_list = list(messages.get_messages(resp.wsgi_request))
        student = Student.objects.get(user__first_name='Second')
        link = StudentGuardianLink.objects.get(student=student)
        self.assertEqual(link.guardian, self.parent1)
        self.assertTrue(
            any('Reused existing guardian' in str(m) for m in messages_list),
            'Expected reuse warning in messages',
        )

    def test_student_create_warns_on_new_guardian(self):
        self.client.login(username='adminx', password='pass123')
        resp = self.client.post(reverse('school_admin:student_create'), {
            'first_name': 'Third', 'last_name': 'Kid',
            'date_of_birth': '2015-07-07', 'gender': 'FEMALE',
            'admission_date': '2026-09-01', 'status': 'ACTIVE',
            'class_id': self.school_class.pk,
            'session_id': self.session.pk,
            'guardian_0_name': 'New Parent',
            'guardian_0_email': f'newparent_{self.school.pk}@test.com',
            'guardian_0_phone': '0803',
            'guardian_0_relationship': 'MOTHER',
        })
        self.assertEqual(resp.status_code, 302)
        messages_list = list(messages.get_messages(resp.wsgi_request))
        self.assertTrue(
            any('New guardian account created' in str(m) for m in messages_list),
            'Expected new-account warning in messages',
        )
        new_parent = User.objects.get(email=f'newparent_{self.school.pk}@test.com')
        self.assertEqual(new_parent.role, Roles.PARENT)

    def test_student_create_rejects_duplicate_guardian_names(self):
        self.client.login(username='adminx', password='pass123')
        resp = self.client.post(reverse('school_admin:student_create'), {
            'first_name': 'Dup', 'last_name': 'Kid',
            'date_of_birth': '2014-06-06', 'gender': 'MALE',
            'admission_date': '2026-09-01', 'status': 'ACTIVE',
            'class_id': self.school_class.pk,
            'session_id': self.session.pk,
            'guardian_0_name': 'Same Name',
            'guardian_0_email': 'a@test.com',
            'guardian_0_phone': '0801',
            'guardian_0_relationship': 'FATHER',
            'guardian_1_name': 'Same Name',
            'guardian_1_email': 'b@test.com',
            'guardian_1_phone': '0802',
            'guardian_1_relationship': 'MOTHER',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('school_admin:student_create'))
        messages_list = list(messages.get_messages(resp.wsgi_request))
        self.assertTrue(
            any('duplicate guardian' in str(m).lower() for m in messages_list),
            'Expected duplicate guardian error in messages',
        )
        self.assertFalse(Student.objects.filter(user__first_name='Dup').exists())

    def test_student_create_rejects_duplicate_guardian_emails(self):
        self.client.login(username='adminx', password='pass123')
        resp = self.client.post(reverse('school_admin:student_create'), {
            'first_name': 'Dup', 'last_name': 'Kid',
            'date_of_birth': '2014-06-06', 'gender': 'MALE',
            'admission_date': '2026-09-01', 'status': 'ACTIVE',
            'class_id': self.school_class.pk,
            'session_id': self.session.pk,
            'guardian_0_name': 'Parent A',
            'guardian_0_email': 'same@test.com',
            'guardian_0_phone': '0801',
            'guardian_0_relationship': 'FATHER',
            'guardian_1_name': 'Parent B',
            'guardian_1_email': 'same@test.com',
            'guardian_1_phone': '0802',
            'guardian_1_relationship': 'MOTHER',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('school_admin:student_create'))
        messages_list = list(messages.get_messages(resp.wsgi_request))
        self.assertTrue(
            any('duplicate guardian' in str(m).lower() for m in messages_list),
            'Expected duplicate guardian error in messages',
        )
        self.assertFalse(Student.objects.filter(user__first_name='Dup').exists())

    def test_student_create_rejects_duplicate_guardian_phones(self):
        self.client.login(username='adminx', password='pass123')
        resp = self.client.post(reverse('school_admin:student_create'), {
            'first_name': 'Dup', 'last_name': 'Kid',
            'date_of_birth': '2014-06-06', 'gender': 'MALE',
            'admission_date': '2026-09-01', 'status': 'ACTIVE',
            'class_id': self.school_class.pk,
            'session_id': self.session.pk,
            'guardian_0_name': 'Parent A',
            'guardian_0_email': 'a@test.com',
            'guardian_0_phone': '08099999999',
            'guardian_0_relationship': 'FATHER',
            'guardian_1_name': 'Parent B',
            'guardian_1_email': 'b@test.com',
            'guardian_1_phone': '08099999999',
            'guardian_1_relationship': 'MOTHER',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('school_admin:student_create'))
        messages_list = list(messages.get_messages(resp.wsgi_request))
        self.assertTrue(
            any('duplicate guardian' in str(m).lower() for m in messages_list),
            'Expected duplicate guardian error in messages',
        )
        self.assertFalse(Student.objects.filter(user__first_name='Dup').exists())

    def test_student_create_allows_distinct_guardians(self):
        self.client.login(username='adminx', password='pass123')
        resp = self.client.post(reverse('school_admin:student_create'), {
            'first_name': 'Distinct', 'last_name': 'Kid',
            'date_of_birth': '2014-06-06', 'gender': 'MALE',
            'admission_date': '2026-09-01', 'status': 'ACTIVE',
            'class_id': self.school_class.pk,
            'session_id': self.session.pk,
            'guardian_0_name': 'Parent A',
            'guardian_0_email': 'a@test.com',
            'guardian_0_phone': '0801',
            'guardian_0_relationship': 'FATHER',
            'guardian_1_name': 'Parent B',
            'guardian_1_email': 'b@test.com',
            'guardian_1_phone': '0802',
            'guardian_1_relationship': 'MOTHER',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Student.objects.filter(user__first_name='Distinct').exists())

class PaymentAdminTest(TestCase):
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
        """A payment recorded without an invoice auto-links to the oldest outstanding invoice."""
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
        payment = Payment.objects.get(student=self.student, invoice=self.invoice)
        self.assertEqual(payment.method, Payment.Method.CHEQUE)
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)
        self.assertEqual(payment.description, 'Books')
        self.assertEqual(self.invoice.balance, Decimal('55000.00'))
        self.assertIsNotNone(payment.receipt)

    def test_record_payment_without_invoice_remains_unlinked_when_no_outstanding(self):
        """A payment without an invoice stays invoice-less if the student owes nothing."""
        user2 = User.objects.create_user(
            username='student4', email='student4@test.com', password='testpass123',
            school=self.school, role=Roles.STUDENT, first_name='No', last_name='Debt',
        )
        student2 = Student.objects.create(
            school=self.school, user=user2, admission_number='STU004',
            date_of_birth=date(2010, 1, 1), gender=Student.MALE,
            admission_date=date(2025, 9, 1), status=Student.ACTIVE,
        )
        ClassEnrollment.objects.create(
            school=self.school, student=student2, school_class=self.school_class,
            session=self.session, is_current=True,
        )
        paid_inv = Invoice.objects.create(
            school=self.school, student=student2, term=self.term,
            total_amount=Decimal('20000.00'),
        )
        Payment.objects.create(
            school=self.school, invoice=paid_inv, student=student2,
            amount=Decimal('20000.00'), method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED, paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )
        self.client.force_login(self.admin_user)
        resp = self.client.post(
            reverse('school_admin:student_record_payment', kwargs={'pk': student2.pk}),
            {'amount': '3000.00', 'method': 'CASH'},
        )
        self.assertEqual(resp.status_code, 302)
        payment = Payment.objects.get(student=student2, invoice__isnull=True)
        self.assertEqual(payment.amount, Decimal('3000.00'))
        self.assertEqual(paid_inv.balance, Decimal('0.00'))

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
        ClassSubject.objects.create(
            school=self.school, subject=self.subject, school_class=self.school_class,
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
            'date_of_birth': '2013-05-05', 'gender': 'FEMALE',
            'admission_date': '2026-09-01', 'status': 'ACTIVE',
            'class_id': self.school_class.pk,
            'session_id': self.session.pk,
        })
        self.assertEqual(resp.status_code, 302)
        student = Student.objects.get(user__first_name='New', user__last_name='Kid')
        self.assertTrue(student.user.must_change_password)

    def test_parent_create_sets_flag(self):
        resp = self.client.post(reverse('school_admin:student_create'), {
            'first_name': 'New', 'last_name': 'Kid',
            'date_of_birth': '2013-05-05', 'gender': 'FEMALE',
            'admission_date': '2026-09-01', 'status': 'ACTIVE',
            'class_id': self.school_class.pk,
            'session_id': self.session.pk,
            'guardian_0_name': 'Mama New',
            'guardian_0_email': 'mama.new@test.com',
            'guardian_0_phone': '08000000000',
            'guardian_0_relationship': 'MOTHER',
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


class StudentOriginAndGuardianDetailsTests(TestCase):
    """New student origin and guardian detail fields."""

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
            username='adminx', email='admin@test.com', password='pass123',
            school=self.school, role=Roles.ADMIN,
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school, name='JSS1A', level='JSS1',
        )
        self.client.login(username='adminx', password='pass123')

    def test_student_create_saves_origin_fields(self):
        resp = self.client.post(reverse('school_admin:student_create'), {
            'first_name': 'New', 'last_name': 'Kid',
            'date_of_birth': '2013-05-05', 'gender': 'FEMALE',
            'admission_date': '2026-09-01', 'status': 'ACTIVE',
            'state_of_origin': 'Lagos',
            'local_government_area': 'Ikeja',
            'class_id': self.school_class.pk,
            'session_id': self.session.pk,
        })
        self.assertEqual(resp.status_code, 302)
        student = Student.objects.get(user__first_name='New')
        self.assertEqual(student.state_of_origin, 'Lagos')
        self.assertEqual(student.local_government_area, 'Ikeja')

    def test_student_edit_updates_origin_fields(self):
        student_user = User.objects.create_user(
            username='stud1', email='s@test.com', password='pass123',
            school=self.school, role=Roles.STUDENT, first_name='Kid', last_name='One',
        )
        student = Student.objects.create(
            school=self.school, user=student_user, admission_number='S001',
            date_of_birth=date(2012, 1, 1), gender='MALE',
            admission_date=date(2026, 9, 1), status='ACTIVE',
            state_of_origin='', local_government_area='',
        )
        resp = self.client.post(
            reverse('school_admin:student_edit', args=[student.pk]), {
                'admission_number': 'S001',
                'date_of_birth': '2012-01-01', 'gender': 'MALE',
                'admission_date': '2026-09-01', 'status': 'ACTIVE',
                'state_of_origin': 'Rivers',
                'local_government_area': 'PH',
            }
        )
        self.assertEqual(resp.status_code, 302)
        student.refresh_from_db()
        self.assertEqual(student.state_of_origin, 'Rivers')
        self.assertEqual(student.local_government_area, 'PH')

    def test_add_guardian_saves_detail_fields(self):
        student_user = User.objects.create_user(
            username='stud1', email='s@test.com', password='pass123',
            school=self.school, role=Roles.STUDENT, first_name='Kid', last_name='One',
        )
        student = Student.objects.create(
            school=self.school, user=student_user, admission_number='S001',
            date_of_birth=date(2012, 1, 1), gender='MALE',
            admission_date=date(2026, 9, 1), status='ACTIVE',
        )
        resp = self.client.post(
            reverse('school_admin:student_add_guardian', args=[student.pk]), {
                'guardian_first_name': 'Mama',
                'guardian_last_name': 'Two',
                'guardian_email': 'mama2@test.com',
                'guardian_phone_number': '0802',
                'relationship': 'MOTHER',
                'guardian_occupation': 'Doctor',
                'guardian_address': '123 Main St',
                'guardian_authorized_pickup_person': 'Uncle Emeka',
                'is_primary_contact': 'on',
            },
        )
        self.assertEqual(resp.status_code, 302)
        link = StudentGuardianLink.objects.get(student=student)
        self.assertEqual(link.occupation, 'Doctor')
        self.assertEqual(link.address, '123 Main St')
        self.assertEqual(link.authorized_pickup_person, 'Uncle Emeka')

    def test_student_create_guardian_block_saves_detail_fields(self):
        resp = self.client.post(reverse('school_admin:student_create'), {
            'first_name': 'New', 'last_name': 'Kid',
            'date_of_birth': '2013-05-05', 'gender': 'FEMALE',
            'admission_date': '2026-09-01', 'status': 'ACTIVE',
            'class_id': self.school_class.pk,
            'session_id': self.session.pk,
            'guardian_0_name': 'Mama New',
            'guardian_0_email': 'mama.new@test.com',
            'guardian_0_phone': '08000000000',
            'guardian_0_relationship': 'MOTHER',
            'guardian_0_occupation': 'Nurse',
            'guardian_0_address': '45 Broad St',
            'guardian_0_authorized_pickup_person': 'Aunty Ngozi',
        })
        self.assertEqual(resp.status_code, 302)
        student = Student.objects.get(user__first_name='New')
        link = StudentGuardianLink.objects.get(student=student)
        self.assertEqual(link.occupation, 'Nurse')
        self.assertEqual(link.address, '45 Broad St')
        self.assertEqual(link.authorized_pickup_person, 'Aunty Ngozi')


class DashboardCollectedThisTermTest(TestCase):
    """Dashboard 'Collected This Term' and fee chart count payments by invoice term."""

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
        self.student_user = User.objects.create_user(
            username='student1', email='student1@test.com', password='testpass123',
            school=self.school, role=Roles.STUDENT, first_name='Kid', last_name='One',
        )
        self.student = Student.objects.create(
            school=self.school, user=self.student_user, admission_number='M001',
            date_of_birth=date(2012, 1, 1), gender='MALE',
            admission_date=date(2025, 9, 1), status='ACTIVE',
        )
        ClassEnrollment.objects.create(
            school=self.school, student=self.student, school_class=self.school_class,
            session=self.session, is_current=True,
        )
        self.invoice = Invoice.objects.create(
            school=self.school, student=self.student, term=self.term,
            total_amount=Decimal('60000.00'),
        )

    def test_collected_this_term_counts_pre_term_payments(self):
        """Payments made before the term starts still count for the term."""
        self.client.force_login(self.admin_user)
        Payment.objects.create(
            school=self.school, invoice=self.invoice, student=self.student,
            amount=Decimal('30000.00'), method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.make_aware(
                timezone.datetime(2025, 8, 1, 10, 0, 0)
            ),
            recorded_by=self.admin_user,
        )
        resp = self.client.get(reverse('school_admin:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '30000')

    def test_fee_chart_groups_by_invoice_term_not_payment_date(self):
        """Chart buckets a payment under its invoice's term, not paid_on date."""
        self.client.force_login(self.admin_user)
        Payment.objects.create(
            school=self.school, invoice=self.invoice, student=self.student,
            amount=Decimal('25000.00'), method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.make_aware(
                timezone.datetime(2025, 8, 1, 10, 0, 0)
            ),
            recorded_by=self.admin_user,
        )
        resp = self.client.get(reverse('school_admin:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '25000')


class DashboardOnboardingTest(TestCase):
    """Dashboard onboarding links point to the relevant admin setup pages."""

    def setUp(self):
        self.school = School.objects.create(name='Test School', short_code='test')
        self.admin_user = User.objects.create_user(
            username='admin', email='admin@test.com', password='testpass123',
            school=self.school, role=Roles.ADMIN,
        )
        self.client.force_login(self.admin_user)

    def test_empty_school_shows_onboarding_links(self):
        response = self.client.get(reverse('school_admin:dashboard'), follow=True)

        self.assertContains(response, 'Finish setting up your school')
        for route_name in (
            'school_settings',
            'session_list',
            'class_list',
            'subject_list',
            'staff_list',
            'student_list',
            'fee_category_list',
        ):
            self.assertContains(response, reverse(f'school_admin:{route_name}'))

    def test_completed_setup_hides_onboarding_alert(self):
        session = AcademicSession.objects.create(
            school=self.school, name='2025/2026',
            start_date=date(2025, 9, 1), end_date=date(2026, 8, 31),
            is_current=True,
        )
        Term.objects.create(
            school=self.school, session=session, name='First Term',
            start_date=date(2025, 9, 1), end_date=date(2025, 12, 15),
            is_current=True,
        )
        self.school.address = '1 School Road'
        self.school.phone = '08000000000'
        self.school.email = 'school@test.com'
        self.school.principal_name = 'Principal'
        self.school.save()
        SchoolClass.objects.create(school=self.school, name='JSS1', level='JSS1')
        Subject.objects.create(school=self.school, name='Maths', code='MTH')
        User.objects.create_user(
            username='teacher', email='teacher@test.com', password='testpass123',
            school=self.school, role=Roles.TEACHER,
        )
        student_user = User.objects.create_user(
            username='student', email='student@test.com', password='testpass123',
            school=self.school, role=Roles.STUDENT,
        )
        Student.objects.create(
            school=self.school, user=student_user, admission_number='S001',
            date_of_birth=date(2012, 1, 1), gender='MALE',
            admission_date=date(2025, 9, 1),
        )
        FeeCategory.objects.create(school=self.school, name='Tuition')
        FeePrice.objects.create(
            school=self.school, category=FeeCategory.objects.get(school=self.school),
            term=Term.objects.get(school=self.school), amount=Decimal('1000'),
            scope=FeePrice.SCOPE_SCHOOL_WIDE,
        )

        response = self.client.get(reverse('school_admin:dashboard'), follow=True)

        self.assertNotContains(response, 'Finish setting up your school')


class ClassFirstSubjectManagementTests(TestCase):
    """Tests for class-first subject management."""

    def setUp(self):
        self.school = School.objects.create(name='Test School', short_code='test')
        self.session = AcademicSession.objects.create(
            school=self.school, name='2025/2026',
            start_date=date(2025, 9, 1), end_date=date(2026, 8, 31), is_current=True,
        )
        self.admin_user = User.objects.create_user(
            username='admin', email='admin@test.com', password='testpass123',
            school=self.school, role=Roles.ADMIN,
        )
        self.client.force_login(self.admin_user)
        self.school_class = SchoolClass.objects.create(
            school=self.school, name='JSS 1', level='Junior',
        )
        self.subject = Subject.objects.create(
            school=self.school, name='Mathematics', code='MTH',
        )

    def test_class_detail_renders_subjects(self):
        resp = self.client.get(reverse('school_admin:class_detail', args=[self.school_class.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Mathematics')

    def test_add_existing_subject_to_class(self):
        resp = self.client.post(
            reverse('school_admin:class_subject_add', args=[self.school_class.pk]),
            {'subject_ids': [self.subject.pk], 'pass_mark': '50'},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            ClassSubject.objects.filter(
                school=self.school, subject=self.subject, school_class=self.school_class, pass_mark=50
            ).exists()
        )

    def test_bulk_add_subjects(self):
        english = Subject.objects.create(school=self.school, name='English', code='ENG')
        resp = self.client.post(
            reverse('school_admin:class_subject_bulk_add', args=[self.school_class.pk]),
            {'subject_ids': [self.subject.pk, english.pk], 'pass_mark': '45'},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(ClassSubject.objects.filter(school_class=self.school_class).count(), 2)

    def test_create_new_subject_from_class(self):
        resp = self.client.post(
            reverse('school_admin:class_subject_create', args=[self.school_class.pk]),
            {'name': 'Physics', 'code': 'PHY', 'pass_mark': '50'},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Subject.objects.filter(school=self.school, name='Physics').exists())
        self.assertTrue(
            ClassSubject.objects.filter(
                school=self.school, subject__name='Physics', school_class=self.school_class, pass_mark=50
            ).exists()
        )

    def test_remove_subject_from_class(self):
        ClassSubject.objects.create(
            school=self.school, subject=self.subject, school_class=self.school_class, pass_mark=40,
        )
        resp = self.client.post(
            reverse('school_admin:class_subject_remove', args=[self.school_class.pk, self.subject.pk]),
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            ClassSubject.objects.filter(
                school=self.school, subject=self.subject, school_class=self.school_class
            ).exists()
        )


class StaffDeleteViewTest(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='Del School', short_code='delsch')
        self.session = AcademicSession.objects.create(
            school=self.school, name='2026/2027',
            start_date=date(2026, 9, 1), end_date=date(2027, 8, 31), is_current=True,
        )
        self.term = Term.objects.create(
            school=self.school, session=self.session, name='First Term',
            start_date=date(2026, 9, 1), end_date=date(2026, 12, 15), is_current=True,
        )
        self.school_class = SchoolClass.objects.create(school=self.school, name='JSS1', level='JSS1')
        self.superadmin = User.objects.create_user(
            username='super1', email='super1@test.com', password='pass123',
            school=None, role=Roles.ADMIN, first_name='Super', last_name='Admin',
            is_superuser=True, is_staff=True,
        )
        self.regular_admin = User.objects.create_user(
            username='admin1', email='admin1@test.com', password='pass123',
            school=self.school, role=Roles.ADMIN, first_name='Admin', last_name='Regular',
        )
        self.teacher = User.objects.create_user(
            username='teacher1', email='teacher1@test.com', password='pass123',
            school=self.school, role=Roles.TEACHER, first_name='Tea', last_name='Cher',
        )

    def test_superuser_can_access_delete_page(self):
        self.client.force_login(self.superadmin)
        resp = self.client.get(reverse('school_admin:staff_delete', args=[self.teacher.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Delete Staff Member')

    def test_regular_admin_cannot_delete(self):
        self.client.force_login(self.regular_admin)
        resp = self.client.get(reverse('school_admin:staff_delete', args=[self.teacher.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_superuser_can_hard_delete_teacher(self):
        self.client.force_login(self.superadmin)
        resp = self.client.post(reverse('school_admin:staff_delete', args=[self.teacher.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(User.objects.filter(pk=self.teacher.pk).exists())

    def test_superuser_cannot_delete_self(self):
        self.client.force_login(self.superadmin)
        resp = self.client.post(reverse('school_admin:staff_delete', args=[self.superadmin.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(pk=self.superadmin.pk).exists())

    def test_delete_page_shows_related_warnings(self):
        from academics.models import TeacherAssignment, Score
        subject = Subject.objects.create(school=self.school, name='Math', code='MTH')
        TeacherAssignment.objects.create(school=self.school, teacher=self.teacher, subject=subject, school_class=self.school_class, session=self.session)
        student_user = User.objects.create_user(
            username='scorestu', email='scorestu@test.com', password='pass123',
            school=self.school, role=Roles.STUDENT, first_name='Score', last_name='Student',
        )
        student = Student.objects.create(
            school=self.school, user=student_user, admission_number='SCR01',
            date_of_birth=date(2012, 1, 1), gender='MALE',
            admission_date=date(2026, 9, 1), status='ACTIVE',
        )
        Score.objects.create(school=self.school, student=student, subject=subject, term=self.term, entered_by=self.teacher)

        self.client.force_login(self.superadmin)
        resp = self.client.get(reverse('school_admin:staff_delete', args=[self.teacher.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'teacher assignment(s)')
        self.assertContains(resp, 'score record(s) entered')

        self.client.force_login(self.superadmin)
        resp = self.client.get(reverse('school_admin:staff_delete', args=[self.teacher.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'teacher assignment(s)')
        self.assertContains(resp, 'score record(s)')

    def test_superuser_sees_delete_button_in_staff_list(self):
        self.client.force_login(self.superadmin)
        resp = self.client.get(reverse('school_admin:staff_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse('school_admin:staff_delete', args=[self.teacher.pk]))

    def test_regular_admin_does_not_see_delete_button(self):
        self.client.force_login(self.regular_admin)
        resp = self.client.get(reverse('school_admin:staff_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, reverse('school_admin:staff_delete', args=[self.teacher.pk]))


class SetupChecksTest(TestCase):
    """Tests for dashboard setup status checks."""

    def setUp(self):
        self.school = School.objects.create(name='Test School', short_code='test')
        self.admin_user = User.objects.create_user(
            username='admin1', email='admin@test.com', password='testpass123',
            school=self.school, role=Roles.ADMIN,
        )
        self.client.force_login(self.admin_user)

    def test_all_checks_trigger_on_bare_school(self):
        """When nothing is configured, only the top 5 priority alerts show."""
        from school_admin.setup_checks import run_setup_checks
        alerts = run_setup_checks(self.school)
        self.assertEqual(len(alerts), 5)
        keys = [a['key'] for a in alerts]
        self.assertEqual(keys, [
            'school_profile', 'no_session', 'no_term',
            'no_classes', 'no_subjects',
        ])

    def test_max_alerts_limit(self):
        """No more than MAX_DASHBOARD_ALERTS alerts are returned."""
        from school_admin.setup_checks import run_setup_checks, MAX_DASHBOARD_ALERTS
        alerts = run_setup_checks(self.school)
        self.assertLessEqual(len(alerts), MAX_DASHBOARD_ALERTS)

    def test_priority_ordering(self):
        """Alerts are sorted by priority (ascending)."""
        from school_admin.setup_checks import run_setup_checks
        alerts = run_setup_checks(self.school)
        priorities = [a['priority'] for a in alerts]
        self.assertEqual(priorities, sorted(priorities))

    def test_fee_prices_check_without_term(self):
        """FeePrice check does not trigger when there is no current term."""
        from school_admin.setup_checks import check_fee_prices
        alert = check_fee_prices(self.school)
        self.assertIsNone(alert)

    def test_teacher_assignments_check_without_session(self):
        """TeacherAssignment check does not trigger when there is no current session."""
        from school_admin.setup_checks import check_teacher_assignments
        alert = check_teacher_assignments(self.school)
        self.assertIsNone(alert)

    def test_fee_prices_check_triggers_with_term(self):
        """FeePrice check triggers when there is a current term but no prices."""
        session = AcademicSession.objects.create(
            school=self.school, name='2025/2026',
            start_date=date(2025, 9, 1), end_date=date(2026, 8, 31),
            is_current=True,
        )
        Term.objects.create(
            school=self.school, session=session, name='First Term',
            start_date=date(2025, 9, 1), end_date=date(2025, 12, 15),
            is_current=True,
        )
        from school_admin.setup_checks import check_fee_prices
        alert = check_fee_prices(self.school)
        self.assertIsNotNone(alert)
        self.assertEqual(alert['key'], 'no_fee_prices')

    def test_setup_complete_shows_no_alerts(self):
        """When everything is configured, run_setup_checks returns []."""
        session = AcademicSession.objects.create(
            school=self.school, name='2025/2026',
            start_date=date(2025, 9, 1), end_date=date(2026, 8, 31),
            is_current=True,
        )
        term = Term.objects.create(
            school=self.school, session=session, name='First Term',
            start_date=date(2025, 9, 1), end_date=date(2025, 12, 15),
            is_current=True,
        )
        school_class = SchoolClass.objects.create(
            school=self.school, name='JSS1A', level='JSS1',
        )
        subject = Subject.objects.create(
            school=self.school, name='Math', code='MTH',
        )
        category = FeeCategory.objects.create(school=self.school, name='School Fees')
        FeePrice.objects.create(
            school=self.school, category=category,
            amount=Decimal('50000.00'), term=term,
            scope=FeePrice.SCOPE_SCHOOL_WIDE,
        )
        teacher = User.objects.create_user(
            username='teacher1', email='teacher@test.com', password='testpass123',
            school=self.school, role=Roles.TEACHER,
        )
        TeacherAssignment.objects.create(
            school=self.school, teacher=teacher, subject=subject,
            school_class=school_class, session=session,
        )
        student_user = User.objects.create_user(
            username='stu1', email='stu@test.com', password='testpass123',
            school=self.school, role=Roles.STUDENT, first_name='Kid', last_name='One',
        )
        Student.objects.create(
            school=self.school, user=student_user, admission_number='M001',
            date_of_birth=date(2012, 1, 1), gender='MALE',
            admission_date=date(2025, 9, 1), status='ACTIVE',
        )
        StaffProfile.objects.create(
            school=self.school, user=self.admin_user, employee_id='E001',
            bank_name='Test Bank', bank_account_number='1234567890',
            bank_account_name='Test Account', hire_date=date(2025, 1, 1),
        )
        self.school.phone = '0123456789'
        self.school.email = 'test@test.com'
        self.school.bank_name = 'Test Bank'
        self.school.account_name = 'Test Account'
        self.school.account_number = '1234567890'
        self.school.save()

        from school_admin.setup_checks import run_setup_checks
        alerts = run_setup_checks(self.school)
        self.assertEqual(alerts, [])

    def test_dashboard_includes_setup_alerts(self):
        """Dashboard view passes setup_alerts in context."""
        resp = self.client.get(reverse('school_admin:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('setup_alerts', resp.context)
        self.assertGreater(len(resp.context['setup_alerts']), 0)

    def test_all_action_urls_resolve(self):
        """Every alert's action_url must resolve to a real URL."""
        from school_admin.setup_checks import run_setup_checks
        alerts = run_setup_checks(self.school)
        self.assertGreater(len(alerts), 0)
        for alert in alerts:
            url = reverse(alert['action_url'])
            self.assertTrue(url.startswith('/'))

    def test_school_profile_alert_disappears_when_fixed(self):
        """School profile check returns None once contact and bank details are filled."""
        from school_admin.setup_checks import check_school_profile
        # Bare school: missing phone, email, bank details
        self.assertIsNotNone(check_school_profile(self.school))
        # Fix the school
        self.school.phone = '0123456789'
        self.school.email = 'test@test.com'
        self.school.bank_name = 'Test Bank'
        self.school.account_name = 'Test Account'
        self.school.account_number = '1234567890'
        self.school.save()
        self.assertIsNone(check_school_profile(self.school))

    def test_session_alert_disappears_when_fixed(self):
        """Session check returns None once a current session exists."""
        from school_admin.setup_checks import check_current_session
        self.assertIsNotNone(check_current_session(self.school))
        AcademicSession.objects.create(
            school=self.school, name='2025/2026',
            start_date=date(2025, 9, 1), end_date=date(2026, 8, 31),
            is_current=True,
        )
        self.assertIsNone(check_current_session(self.school))

    def test_term_alert_disappears_when_fixed(self):
        """Term check returns None once a current term exists."""
        from school_admin.setup_checks import check_current_term
        self.assertIsNotNone(check_current_term(self.school))
        session = AcademicSession.objects.create(
            school=self.school, name='2025/2026',
            start_date=date(2025, 9, 1), end_date=date(2026, 8, 31),
            is_current=True,
        )
        Term.objects.create(
            school=self.school, session=session, name='First Term',
            start_date=date(2025, 9, 1), end_date=date(2025, 12, 15),
            is_current=True,
        )
        self.assertIsNone(check_current_term(self.school))

    def test_classes_alert_disappears_when_fixed(self):
        """Classes check returns None once an active class exists."""
        from school_admin.setup_checks import check_active_classes
        self.assertIsNotNone(check_active_classes(self.school))
        SchoolClass.objects.create(school=self.school, name='JSS1', level='JSS1', is_active=True)
        self.assertIsNone(check_active_classes(self.school))

    def test_subjects_alert_disappears_when_fixed(self):
        """Subjects check returns None once a subject exists."""
        from school_admin.setup_checks import check_subjects
        self.assertIsNotNone(check_subjects(self.school))
        Subject.objects.create(school=self.school, name='Math', code='MTH')
        self.assertIsNone(check_subjects(self.school))

    def test_fee_categories_alert_disappears_when_fixed(self):
        """FeeCategory check returns None once a category exists."""
        from school_admin.setup_checks import check_fee_categories
        self.assertIsNotNone(check_fee_categories(self.school))
        FeeCategory.objects.create(school=self.school, name='School Fees')
        self.assertIsNone(check_fee_categories(self.school))

    def test_students_alert_disappears_when_fixed(self):
        """Students check returns None once an active student exists."""
        from school_admin.setup_checks import check_students
        self.assertIsNotNone(check_students(self.school))
        student_user = User.objects.create_user(
            username='stu1', email='stu@test.com', password='testpass123',
            school=self.school, role=Roles.STUDENT,
        )
        Student.objects.create(
            school=self.school, user=student_user, admission_number='M001',
            date_of_birth=date(2012, 1, 1), gender='MALE',
            admission_date=date(2025, 9, 1), status='ACTIVE',
        )
        self.assertIsNone(check_students(self.school))

    def test_staff_alert_disappears_when_fixed(self):
        """StaffProfile check returns None once a staff profile exists."""
        from school_admin.setup_checks import check_staff_profiles
        self.assertIsNotNone(check_staff_profiles(self.school))
        StaffProfile.objects.create(
            school=self.school, user=self.admin_user, employee_id='E001',
            bank_name='Test Bank', bank_account_number='1234567890',
            bank_account_name='Test Account', hire_date=date(2025, 1, 1),
        )
        self.assertIsNone(check_staff_profiles(self.school))

    def test_teacher_assignments_alert_disappears_when_fixed(self):
        """TeacherAssignment check returns None once an assignment exists for the current session."""
        from school_admin.setup_checks import check_teacher_assignments
        session = AcademicSession.objects.create(
            school=self.school, name='2025/2026',
            start_date=date(2025, 9, 1), end_date=date(2026, 8, 31),
            is_current=True,
        )
        self.assertIsNotNone(check_teacher_assignments(self.school))
        school_class = SchoolClass.objects.create(school=self.school, name='JSS1', level='JSS1')
        subject = Subject.objects.create(school=self.school, name='Math', code='MTH')
        teacher = User.objects.create_user(
            username='t1', email='t@test.com', password='testpass123',
            school=self.school, role=Roles.TEACHER,
        )
        TeacherAssignment.objects.create(
            school=self.school, teacher=teacher, subject=subject,
            school_class=school_class, session=session,
        )
        self.assertIsNone(check_teacher_assignments(self.school))

    def test_fee_prices_alert_disappears_when_fixed(self):
        """FeePrice check returns None once a price exists for the current term."""
        from school_admin.setup_checks import check_fee_prices
        session = AcademicSession.objects.create(
            school=self.school, name='2025/2026',
            start_date=date(2025, 9, 1), end_date=date(2026, 8, 31),
            is_current=True,
        )
        term = Term.objects.create(
            school=self.school, session=session, name='First Term',
            start_date=date(2025, 9, 1), end_date=date(2025, 12, 15),
            is_current=True,
        )
        self.assertIsNotNone(check_fee_prices(self.school))
        category = FeeCategory.objects.create(school=self.school, name='School Fees')
        FeePrice.objects.create(
            school=self.school, category=category,
            amount=Decimal('50000.00'), term=term,
            scope=FeePrice.SCOPE_SCHOOL_WIDE,
        )
        self.assertIsNone(check_fee_prices(self.school))

    def test_fee_prices_alert_uses_available_icon(self):
        """Fee pricing alerts use an icon supported by the vendored Lucide set."""
        from school_admin.setup_checks import check_fee_prices
        session = AcademicSession.objects.create(
            school=self.school, name='2025/2026',
            start_date=date(2025, 9, 1), end_date=date(2026, 8, 31),
            is_current=True,
        )
        Term.objects.create(
            school=self.school, session=session, name='First Term',
            start_date=date(2025, 9, 1), end_date=date(2025, 12, 15),
            is_current=True,
        )

        alert = check_fee_prices(self.school)

        self.assertEqual(alert['icon'], 'tag')

    def test_dashboard_renders_setup_alerts_template(self):
        """Dashboard page shows setup alert titles when checks fire."""
        resp = self.client.get(reverse('school_admin:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Set up sessions')
        self.assertContains(resp, 'No active academic session')
        self.assertContains(resp, 'href="/school-admin/settings/"')
        self.assertNotContains(resp, 'href="school_admin:school_settings"')
