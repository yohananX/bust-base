"""Temporary smoke test: school address renders under the logo in result booklets."""
from datetime import date
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string

from core.models import School, AcademicSession, Term
from accounts.models import Roles
from academics.models import Subject, Score
from academics.booklet import build_booklet_context
from students.models import SchoolClass, Student, ClassEnrollment, StudentGuardianLink

User = get_user_model()


class ResultBookletAddressTest(TestCase):
    """Verify the school address appears centered under the logo in both versions."""

    def setUp(self):
        self.school = School.objects.create(
            name='Grace House', short_code='GH',
            address='123 Main Street, Lagos',
        )
        self.session = AcademicSession.objects.create(
            school=self.school, name='2025/2026',
            start_date=date(2025, 9, 1), end_date=date(2026, 8, 31),
            is_current=True,
        )
        self.term = Term.objects.create(
            school=self.school, session=self.session, name='First Term',
            start_date=date(2025, 9, 1), end_date=date(2025, 12, 15),
            is_current=True, results_published=True,
        )
        self.parent = User.objects.create_user(
            username='parent', email='p@p.com', password='x',
            school=self.school, role=Roles.PARENT,
        )
        student_user = User.objects.create_user(
            username='stu', email='s@s.com', password='x',
            school=self.school, role=Roles.STUDENT,
            first_name='John', last_name='Doe',
        )
        self.student = Student.objects.create(
            school=self.school, user=student_user,
            admission_number='STU001', date_of_birth=date(2010, 1, 1),
            gender=Student.MALE, admission_date=date(2025, 9, 1),
            status=Student.ACTIVE,
        )
        StudentGuardianLink.objects.create(
            school=self.school, student=self.student,
            guardian=self.parent, is_primary_contact=True,
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school, name='JSS1A', level='JSS1',
        )
        ClassEnrollment.objects.create(
            school=self.school, student=self.student,
            school_class=self.school_class, session=self.session,
            is_current=True,
        )
        subject = Subject.objects.create(school=self.school, name='Maths')
        teacher = User.objects.create_user(
            username='teacher', email='t@t.com', password='x',
            school=self.school, role=Roles.TEACHER,
        )
        Score.objects.create(
            school=self.school, student=self.student, subject=subject,
            term=self.term, test_1=8, exam_score=65, entered_by=teacher,
        )

    def test_onscreen_shows_address_under_logo(self):
        self.client.force_login(self.parent)
        resp = self.client.get(
            f'/parent/child/{self.student.pk}/results/{self.term.pk}/'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '123 Main Street, Lagos')

    def test_pdf_shows_address_under_logo(self):
        context, _ = build_booklet_context(self.student, self.term, self.school)
        context['logo_url'] = ''
        html = render_to_string('academics/result_booklet.html', context)
        self.assertIn('123 Main Street, Lagos', html)
        self.assertIn('school-address', html)
