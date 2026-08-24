"""End-to-end bulk credential generation tests.

Verifies that generated passwords work for login and force a password change.
"""
import re
from django.test import TestCase
from django.urls import reverse

from accounts.models import Roles
from core.models import School, AcademicSession, Term
from students.models import SchoolClass, Student, ClassEnrollment
from accounts.models import User


User = User


class CredentialEndToEndTest(TestCase):
    """Two chained test methods for batch + single credential generation."""

    def setUp(self):
        self.school = School.objects.create(name='E2E Cred School', short_code='e2ecred')
        self.session = AcademicSession.objects.create(
            school=self.school,
            name='2026/2027',
            start_date='2026-09-01',
            end_date='2027-08-31',
            is_current=True,
        )
        self.term = Term.objects.create(
            school=self.school,
            session=self.session,
            name='First Term',
            start_date='2026-09-01',
            end_date='2026-12-15',
            is_current=True,
        )

        self.school_class = SchoolClass.objects.create(
            school=self.school, name='JSS1', level='JSS1',
        )

        self.admin = User.objects.create_user(
            username='e2ecred_admin', email='admin@e2ecred.com', password='pass123',
            school=self.school, role=Roles.ADMIN,
        )

        # Student 1: pre-existing, must_change_password=False initially
        self.student1_user = User.objects.create_user(
            username='e2ecred_stu1', email='stu1@e2ecred.com', password='oldpass123',
            school=self.school, role=Roles.STUDENT,
            must_change_password=False,
        )
        self.student1 = Student.objects.create(
            school=self.school, user=self.student1_user, admission_number='E2ECRED-1',
            date_of_birth='2012-01-01', gender=Student.MALE,
            admission_date='2026-09-01', status=Student.ACTIVE,
        )
        ClassEnrollment.objects.create(
            school=self.school, student=self.student1,
            school_class=self.school_class, session=self.session,
            is_current=True,
        )

        # Student 2: pre-existing, must_change_password=False initially
        self.student2_user = User.objects.create_user(
            username='e2ecred_stu2', email='stu2@e2ecred.com', password='oldpass123',
            school=self.school, role=Roles.STUDENT,
            must_change_password=False,
        )
        self.student2 = Student.objects.create(
            school=self.school, user=self.student2_user, admission_number='E2ECRED-2',
            date_of_birth='2012-02-02', gender=Student.FEMALE,
            admission_date='2026-09-01', status=Student.ACTIVE,
        )
        ClassEnrollment.objects.create(
            school=self.school, student=self.student2,
            school_class=self.school_class, session=self.session,
            is_current=True,
        )

        self.client.login(username='e2ecred_admin', password='pass123')

    def _extract_password_from_html(self, html):
        """Parse the raw password from the credential slip HTML."""
        # The copy button carries data-password="RAW_PASSWORD"
        match = re.search(r'data-password="([A-Za-z0-9]{10})"', html)
        self.assertIsNotNone(match, 'Could not find generated password in HTML')
        return match.group(1)

    def test_batch_generated_password_works_for_login(self):
        """Batch generate passwords -> parse from print page -> login -> forced change."""

        # Step 1: Admin POSTs to credential_batch with group=students
        resp = self.client.post(
            reverse('school_admin:credential_batch'), {'group': 'students'}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse('school_admin:credential_batch_print'))

        # All student users must have must_change_password=True
        self.student1_user.refresh_from_db()
        self.student2_user.refresh_from_db()
        self.assertTrue(self.student1_user.must_change_password)
        self.assertTrue(self.student2_user.must_change_password)

        # Step 2: Admin GETs credential_batch_print -> slips visible
        print_resp = self.client.get(reverse('school_admin:credential_batch_print'))
        self.assertEqual(print_resp.status_code, 200)
        self.assertContains(print_resp, self.student1_user.username)
        self.assertContains(print_resp, self.student2_user.username)

        # Step 3: Extract ONE student password from the HTML
        raw_password = self._extract_password_from_html(print_resp.content.decode())

        # Step 4: Logout admin, login as that student with generated password
        self.client.logout()
        login_resp = self.client.post(
            reverse('login'),
            {'username': self.student1_user.username, 'password': raw_password},
        )
        # Login should succeed (redirect)
        self.assertEqual(login_resp.status_code, 302)

        # Step 5: GET /student/ -> redirected to forced-password-change
        self.client.force_login(self.student1_user)
        overview_resp = self.client.get('/student/')
        self.assertRedirects(overview_resp, reverse('forced_password_change'))

        # Step 6: POST to forced-password-change with generated password as current
        change_resp = self.client.post(
            reverse('forced_password_change'),
            {
                'current_password': raw_password,
                'new_password': 'newsecure123',
                'confirm_password': 'newsecure123',
            },
        )
        self.assertEqual(change_resp.status_code, 302)
        self.assertRedirects(change_resp, reverse('post_login_redirect'))

        # Flag cleared
        self.student1_user.refresh_from_db()
        self.assertFalse(self.student1_user.must_change_password)

        # New password works
        self.client.logout()
        login_again = self.client.post(
            reverse('login'),
            {'username': self.student1_user.username, 'password': 'newsecure123'},
        )
        self.assertEqual(login_again.status_code, 302)

    def test_single_reset_password_works_for_login(self):
        """Single reset password -> parse from slip -> login -> forced change."""

        # Step 1: Admin POSTs to credential_single_reset for student2
        reset_resp = self.client.post(
            reverse('school_admin:credential_single_reset', args=[self.student2_user.pk])
        )
        self.assertEqual(reset_resp.status_code, 302)
        self.assertRedirects(reset_resp, reverse('school_admin:credential_slip', args=[self.student2_user.pk]))

        # must_change_password=True
        self.student2_user.refresh_from_db()
        self.assertTrue(self.student2_user.must_change_password)

        # Step 2: GET credential_slip -> password in HTML
        slip_resp = self.client.get(
            reverse('school_admin:credential_slip', args=[self.student2_user.pk])
        )
        self.assertEqual(slip_resp.status_code, 200)
        raw_password = self._extract_password_from_html(slip_resp.content.decode())

        # Step 3: Logout admin, login as student2 with generated password
        self.client.logout()
        login_resp = self.client.post(
            reverse('login'),
            {'username': self.student2_user.username, 'password': raw_password},
        )
        self.assertEqual(login_resp.status_code, 302)

        # Step 4: Forced password change
        self.client.force_login(self.student2_user)
        overview_resp = self.client.get('/student/')
        self.assertRedirects(overview_resp, reverse('forced_password_change'))

        change_resp = self.client.post(
            reverse('forced_password_change'),
            {
                'current_password': raw_password,
                'new_password': 'newsecure456',
                'confirm_password': 'newsecure456',
            },
        )
        self.assertEqual(change_resp.status_code, 302)
        self.assertRedirects(change_resp, reverse('post_login_redirect'))

        self.student2_user.refresh_from_db()
        self.assertFalse(self.student2_user.must_change_password)
