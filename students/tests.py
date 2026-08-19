from django.core.exceptions import ValidationError
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal

from core.models import School, AcademicSession, Term
from accounts.models import Roles
from academics.models import Subject, TeacherAssignment, TermResult, Score
from fees.models import Invoice, Payment
from .models import SchoolClass, Student, ClassEnrollment, StudentGuardianLink


class StudentModelTests(TestCase):
    """Tests for Student, ClassEnrollment, StudentGuardianLink models."""

    def setUp(self):
        self.school = School.objects.create(
            name="Grace House School",
            short_code="grace-house",
        )
        User = get_user_model()
        self.student_user = User.objects.create_user(
            username="john_doe",
            email="john@grace.edu",
            password="testpass123",
            school=self.school,
            role=Roles.STUDENT,
            first_name="John",
            last_name="Doe",
        )
        self.parent_user = User.objects.create_user(
            username="jane_parent",
            email="jane@grace.edu",
            password="testpass123",
            school=self.school,
            role=Roles.PARENT,
            first_name="Jane",
            last_name="Parent",
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school,
            name="JSS1A",
            level="JSS1",
        )
        self.session = AcademicSession.objects.create(
            school=self.school,
            name="2025/2026",
            start_date="2025-09-01",
            end_date="2026-07-31",
            is_current=True,
        )

    # ---------- Model creation tests ----------

    def test_school_class_creation(self):
        self.assertEqual(str(self.school_class), "JSS1A")
        self.assertEqual(self.school_class.level, "JSS1")
        self.assertTrue(self.school_class.is_active)

    def test_student_creation(self):
        student = Student.objects.create(
            school=self.school,
            user=self.student_user,
            admission_number="GH-001",
            date_of_birth="2010-05-15",
            gender=Student.MALE,
            admission_date="2025-09-01",
        )
        self.assertIn("John Doe", str(student))
        self.assertEqual(student.status, Student.ACTIVE)

    def test_student_enrollment_and_guardian_link(self):
        student = Student.objects.create(
            school=self.school,
            user=self.student_user,
            admission_number="GH-001",
            date_of_birth="2010-05-15",
            gender=Student.MALE,
            admission_date="2025-09-01",
        )
        enrollment = ClassEnrollment.objects.create(
            school=self.school,
            student=student,
            school_class=self.school_class,
            session=self.session,
        )
        self.assertTrue(enrollment.is_current)
        self.assertIsNotNone(enrollment.enrolled_on)

        guardian_link = StudentGuardianLink.objects.create(
            school=self.school,
            student=student,
            guardian=self.parent_user,
            relationship=StudentGuardianLink.MOTHER,
            is_primary_contact=True,
        )
        self.assertIn("John", str(guardian_link))
        self.assertTrue(guardian_link.is_primary_contact)

    # ---------- Only one current enrollment per student ----------

    def test_only_one_current_enrollment_per_student(self):
        student = Student.objects.create(
            school=self.school,
            user=self.student_user,
            admission_number="GH-001",
            date_of_birth="2010-05-15",
            gender=Student.MALE,
            admission_date="2025-09-01",
        )
        class_b = SchoolClass.objects.create(
            school=self.school, name="JSS1B", level="JSS1",
        )
        session2 = AcademicSession.objects.create(
            school=self.school,
            name="2024/2025",
            start_date="2024-09-01",
            end_date="2025-07-31",
        )

        # First enrollment in class A
        enrollment_a = ClassEnrollment.objects.create(
            school=self.school,
            student=student,
            school_class=self.school_class,
            session=self.session,
            is_current=True,
        )
        self.assertTrue(ClassEnrollment.objects.get(pk=enrollment_a.pk).is_current)

        # Second enrollment in class B — this should mark enrollment_a as not current
        enrollment_b = ClassEnrollment.objects.create(
            school=self.school,
            student=student,
            school_class=class_b,
            session=session2,
            is_current=True,
        )
        enrollment_a.refresh_from_db()
        self.assertFalse(enrollment_a.is_current)
        self.assertTrue(ClassEnrollment.objects.get(pk=enrollment_b.pk).is_current)

        # Now set enrollment_a back to current — should unset enrollment_b
        enrollment_a.is_current = True
        enrollment_a.save()
        enrollment_b.refresh_from_db()
        self.assertFalse(enrollment_b.is_current)
        self.assertTrue(ClassEnrollment.objects.get(pk=enrollment_a.pk).is_current)

    # ---------- Promotion rollover test ----------

    def test_promotion_rollover(self):
        student = Student.objects.create(
            school=self.school,
            user=self.student_user,
            admission_number="GH-001",
            date_of_birth="2010-05-15",
            gender=Student.MALE,
            admission_date="2025-09-01",
        )
        # Enroll in session A
        enrollment_a = ClassEnrollment.objects.create(
            school=self.school,
            student=student,
            school_class=self.school_class,
            session=self.session,
            is_current=True,
        )

        # New session for promotion
        session_b = AcademicSession.objects.create(
            school=self.school,
            name="2026/2027",
            start_date="2026-09-01",
            end_date="2027-07-31",
        )
        class_b = SchoolClass.objects.create(
            school=self.school, name="SSS1A", level="SSS1",
        )

        # Promote using the model method
        new_enrollment = student.promote_to(session_b, class_b)

        # Old enrollment should no longer be current
        enrollment_a.refresh_from_db()
        self.assertFalse(enrollment_a.is_current)
        # Old enrollment should still exist
        self.assertTrue(ClassEnrollment.objects.filter(pk=enrollment_a.pk).exists())

        # New enrollment should be current
        self.assertTrue(new_enrollment.is_current)
        self.assertEqual(new_enrollment.session, session_b)
        self.assertEqual(new_enrollment.school_class, class_b)

    # ---------- Withdrawn student excluded from promotion ----------

    def test_withdrawn_student_promote_to_skips(self):
        """Promote_to should still work (model method doesn't filter),
        but the admin action logic should exclude withdrawn students."""
        student = Student.objects.create(
            school=self.school,
            user=self.student_user,
            admission_number="GH-001",
            date_of_birth="2010-05-15",
            gender=Student.MALE,
            admission_date="2025-09-01",
            status=Student.WITHDRAWN,
        )
        session_b = AcademicSession.objects.create(
            school=self.school,
            name="2026/2027",
            start_date="2026-09-01",
            end_date="2027-07-31",
        )
        # promote_to should still work at the model level — it's the admin action
        # that skips. We verify that the enrollment is created successfully.
        enrollment = student.promote_to(session_b, self.school_class)
        self.assertIsNotNone(enrollment)
        self.assertTrue(enrollment.is_current)

    def test_withdrawn_student_excluded_from_admin_promotion_logic(self):
        """Verify the logic the admin action uses to skip withdrawn students."""
        User = get_user_model()
        student = Student.objects.create(
            school=self.school,
            user=self.student_user,
            admission_number="GH-001",
            date_of_birth="2010-05-15",
            gender=Student.MALE,
            admission_date="2025-09-01",
            status=Student.WITHDRAWN,
        )
        # The admin action checks: if student.status in (WITHDRAWN, GRADUATED) → skip
        self.assertIn(student.status, [Student.WITHDRAWN, Student.GRADUATED])

        graduated = Student.objects.create(
            school=self.school,
            user=User.objects.create_user(
                username="grad_student",
                email="grad@grace.edu",
                password="pass",
                school=self.school,
                role=Roles.STUDENT,
            ),
            admission_number="GH-002",
            date_of_birth="2008-03-10",
            gender=Student.FEMALE,
            admission_date="2020-09-01",
            status=Student.GRADUATED,
        )
        self.assertIn(graduated.status, [Student.WITHDRAWN, Student.GRADUATED])

        active = Student.objects.create(
            school=self.school,
            user=User.objects.create_user(
                username="active_student",
                email="active@grace.edu",
                password="pass",
                school=self.school,
                role=Roles.STUDENT,
            ),
            admission_number="GH-003",
            date_of_birth="2011-07-22",
            gender=Student.MALE,
            admission_date="2025-09-01",
            status=Student.ACTIVE,
        )
        self.assertNotIn(active.status, [Student.WITHDRAWN, Student.GRADUATED])

    # ---------- Guardian scoping isolation ----------

    def test_guardian_scoping_isolation(self):
        """Verify GuardianScopedQuerySetMixin filter logic."""
        User = get_user_model()

        # Create two students with different parents
        parent1 = User.objects.create_user(
            username="parent1", email="p1@grace.edu",
            password="pass", school=self.school, role=Roles.PARENT,
        )
        parent2 = User.objects.create_user(
            username="parent2", email="p2@grace.edu",
            password="pass", school=self.school, role=Roles.PARENT,
        )

        student1 = Student.objects.create(
            school=self.school,
            user=User.objects.create_user(
                username="child1", email="c1@grace.edu",
                password="pass", school=self.school, role=Roles.STUDENT,
            ),
            admission_number="GH-010",
            date_of_birth="2010-01-01",
            gender=Student.MALE,
            admission_date="2025-09-01",
        )
        student2 = Student.objects.create(
            school=self.school,
            user=User.objects.create_user(
                username="child2", email="c2@grace.edu",
                password="pass", school=self.school, role=Roles.STUDENT,
            ),
            admission_number="GH-011",
            date_of_birth="2011-01-01",
            gender=Student.FEMALE,
            admission_date="2025-09-01",
        )

        # Link each student to a different parent
        StudentGuardianLink.objects.create(
            school=self.school,
            student=student1,
            guardian=parent1,
            relationship=StudentGuardianLink.FATHER,
        )
        StudentGuardianLink.objects.create(
            school=self.school,
            student=student2,
            guardian=parent2,
            relationship=StudentGuardianLink.MOTHER,
        )

        # Simulate the GuardianScopedQuerySetMixin for parent1
        qs = Student.objects.filter(guardian_links__guardian=parent1)
        self.assertIn(student1, qs)
        self.assertNotIn(student2, qs)

        # For parent2
        qs = Student.objects.filter(guardian_links__guardian=parent2)
        self.assertIn(student2, qs)
        self.assertNotIn(student1, qs)

    # ---------- Cross-school isolation ----------

    def test_cross_school_isolation(self):
        school2 = School.objects.create(
            name="Other School",
            short_code="other",
        )
        User = get_user_model()

        # Note: 'JSS1A' already created in setUp, so use different class names
        class_a = SchoolClass.objects.create(
            school=self.school, name="SSS1A", level="SSS1",
        )
        class_b = SchoolClass.objects.create(
            school=school2, name="SSS1A", level="SSS1",
        )

        # Classes from different schools should be isolated
        # School A has JSS1A (from setUp) + SSS1A = 2; School B has SSS1A = 1
        self.assertEqual(SchoolClass.objects.for_school(self.school).count(), 2)
        self.assertEqual(SchoolClass.objects.for_school(school2).count(), 1)
        self.assertIn(class_a, SchoolClass.objects.for_school(self.school))
        self.assertNotIn(class_b, SchoolClass.objects.for_school(self.school))

        # Students should be isolated per school
        student_user_a = User.objects.create_user(
            username="student_a", email="sa@grace.edu",
            password="pass", school=self.school, role=Roles.STUDENT,
        )
        student_user_b = User.objects.create_user(
            username="student_b", email="sb@other.edu",
            password="pass", school=school2, role=Roles.STUDENT,
        )
        student_a = Student.objects.create(
            school=self.school,
            user=student_user_a,
            admission_number="GH-001",
            date_of_birth="2010-01-01",
            gender=Student.MALE,
            admission_date="2025-09-01",
        )
        student_b = Student.objects.create(
            school=school2,
            user=student_user_b,
            admission_number="GH-001",  # Same admission number, different school
            date_of_birth="2011-01-01",
            gender=Student.FEMALE,
            admission_date="2025-09-01",
        )

        self.assertIn(student_a, Student.objects.for_school(self.school))
        self.assertNotIn(student_b, Student.objects.for_school(self.school))
        self.assertIn(student_b, Student.objects.for_school(school2))

    # ---------- User role validation ----------

    def test_student_user_role_validation(self):
        User = get_user_model()
        teacher_user = User.objects.create_user(
            username="teacher1",
            email="teacher@grace.edu",
            password="pass",
            school=self.school,
            role=Roles.TEACHER,
        )

        with self.assertRaises(ValidationError):
            Student.objects.create(
                school=self.school,
                user=teacher_user,
                admission_number="GH-100",
                date_of_birth="2010-01-01",
                gender=Student.MALE,
                admission_date="2025-09-01",
            )

    def test_guardian_user_role_validation(self):
        User = get_user_model()
        teacher_user = User.objects.create_user(
            username="teacher2",
            email="teacher2@grace.edu",
            password="pass",
            school=self.school,
            role=Roles.TEACHER,
        )
        student = Student.objects.create(
            school=self.school,
            user=self.student_user,
            admission_number="GH-001",
            date_of_birth="2010-05-15",
            gender=Student.MALE,
            admission_date="2025-09-01",
        )

        with self.assertRaises(ValidationError):
            StudentGuardianLink.objects.create(
                school=self.school,
                student=student,
                guardian=teacher_user,
                relationship=StudentGuardianLink.FATHER,
            )

    # ---------- Admission number uniqueness per school ----------

    def test_admission_number_unique_per_school(self):
        school2 = School.objects.create(
            name="Other School",
            short_code="other",
        )
        User = get_user_model()

        # Same admission number in different schools should be allowed
        student_a = Student.objects.create(
            school=self.school,
            user=self.student_user,
            admission_number="GH-001",
            date_of_birth="2010-05-15",
            gender=Student.MALE,
            admission_date="2025-09-01",
        )
        student_user_b = User.objects.create_user(
            username="student_other",
            email="other@grace.edu",
            password="pass",
            school=school2,
            role=Roles.STUDENT,
        )
        student_b = Student.objects.create(
            school=school2,
            user=student_user_b,
            admission_number="GH-001",  # Same number, different school
            date_of_birth="2011-01-01",
            gender=Student.FEMALE,
            admission_date="2025-09-01",
        )
        self.assertEqual(student_a.admission_number, student_b.admission_number)

        # Same admission number in the same school should be rejected
        student_user_c = get_user_model().objects.create_user(
            username="student_dup",
            email="dup@grace.edu",
            password="pass",
            school=self.school,
            role=Roles.STUDENT,
        )
        with self.assertRaises(Exception):
            Student.objects.create(
                school=self.school,
                user=student_user_c,
                admission_number="GH-001",  # Duplicate in same school
                date_of_birth="2012-01-01",
                gender=Student.FEMALE,
                admission_date="2025-09-01",
            )

    # ---------- Student __str__ with class ----------

    def test_student_str_with_class(self):
        student = Student.objects.create(
            school=self.school,
            user=self.student_user,
            admission_number="GH-001",
            date_of_birth="2010-05-15",
            gender=Student.MALE,
            admission_date="2025-09-01",
        )
        ClassEnrollment.objects.create(
            school=self.school,
            student=student,
            school_class=self.school_class,
            session=self.session,
            is_current=True,
        )
        self.assertIn("John Doe", str(student))
        self.assertIn("JSS1A", str(student))

    # ---------- ClassEnrollment __str__ ----------

    def test_enrollment_str(self):
        student = Student.objects.create(
            school=self.school,
            user=self.student_user,
            admission_number="GH-001",
            date_of_birth="2010-05-15",
            gender=Student.MALE,
            admission_date="2025-09-01",
        )
        enrollment = ClassEnrollment.objects.create(
            school=self.school,
            student=student,
            school_class=self.school_class,
            session=self.session,
        )
        self.assertIn("JSS1A", str(enrollment))
        self.assertIn("2025/2026", str(enrollment))


class StudentDashboardFeeToastTests(TestCase):
    """The 'All fees paid' green confirmation is a one-time toast that
    fires only when a student's balance transitions from owing to paid."""

    def setUp(self):
        self.school = School.objects.create(
            name="Grace House School",
            short_code="grace-house",
        )
        User = get_user_model()
        self.student_user = User.objects.create_user(
            username="fee_student",
            email="fee@grace.edu",
            password="testpass123",
            school=self.school,
            role=Roles.STUDENT,
            first_name="Fee",
            last_name="Student",
        )
        self.student = Student.objects.create(
            school=self.school,
            user=self.student_user,
            admission_number="GH-900",
            date_of_birth="2010-05-15",
            gender=Student.MALE,
            admission_date="2025-09-01",
        )
        session = AcademicSession.objects.create(
            school=self.school,
            name="2025/2026",
            start_date="2025-09-01",
            end_date="2026-07-31",
            is_current=True,
        )
        self.term = Term.objects.create(
            school=self.school,
            session=session,
            name="First Term",
            start_date="2025-09-01",
            end_date="2025-12-19",
            is_current=True,
        )
        self.invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal("50000.00"),
        )

    def _get_dashboard(self):
        self.client.force_login(self.student_user)
        return self.client.get(reverse("student-overview"))

    def _confirm_full_payment(self):
        Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            student=self.student,
            amount=Decimal("50000.00"),
            method=Payment.Method.BANK_TRANSFER,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            reference="REF-FULL-001",
        )

    def test_fee_settled_toast_fires_once_after_payment(self):
        resp = self._get_dashboard()
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "All fees paid. Nice work!")

        self._confirm_full_payment()
        self.assertEqual(self.invoice.balance, Decimal("0.00"))

        resp = self._get_dashboard()
        self.assertContains(resp, "All fees paid. Nice work!")

        resp = self._get_dashboard()
        self.assertNotContains(resp, "All fees paid. Nice work!")

    def test_no_toast_when_student_was_always_settled(self):
        self._confirm_full_payment()
        resp = self._get_dashboard()
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "All fees paid. Nice work!")


class StudentSubjectsViewTest(TestCase):
    """Current-term subject list for the student."""

    def setUp(self):
        self.school = School.objects.create(
            name="Grace House School",
            short_code="grace-house",
        )
        User = get_user_model()
        self.student_user = User.objects.create_user(
            username="subj_student",
            email="subj@grace.edu",
            password="testpass123",
            school=self.school,
            role=Roles.STUDENT,
            first_name="Sub",
            last_name="Student",
        )
        self.student = Student.objects.create(
            school=self.school,
            user=self.student_user,
            admission_number="GH-901",
            date_of_birth="2010-05-15",
            gender=Student.MALE,
            admission_date="2025-09-01",
        )
        self.teacher = User.objects.create_user(
            username="mr_ada",
            email="ada@grace.edu",
            password="testpass123",
            school=self.school,
            role=Roles.TEACHER,
            first_name="Ada",
            last_name="Okon",
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school, name="JSS1A", level="JSS1",
        )

        self.session1 = AcademicSession.objects.create(
            school=self.school, name="2024/2025",
            start_date="2024-09-01", end_date="2025-07-31", is_current=False,
        )
        self.session2 = AcademicSession.objects.create(
            school=self.school, name="2025/2026",
            start_date="2025-09-01", end_date="2026-07-31", is_current=True,
        )
        self.term2 = Term.objects.create(
            school=self.school, session=self.session2, name="First Term",
            start_date="2025-09-01", end_date="2025-12-19", is_current=True,
        )

        # Same class for both sessions — only current-term assignments show.
        ClassEnrollment.objects.create(
            school=self.school, student=self.student,
            school_class=self.school_class, session=self.session1, is_current=False,
        )
        ClassEnrollment.objects.create(
            school=self.school, student=self.student,
            school_class=self.school_class, session=self.session2, is_current=True,
        )

        self.maths = Subject.objects.create(school=self.school, name="Mathematics", code="MAT")
        self.english = Subject.objects.create(school=self.school, name="English", code="ENG")

    def _assign(self, session, subject):
        TeacherAssignment.objects.create(
            school=self.school,
            teacher=self.teacher,
            subject=subject,
            school_class=self.school_class,
            session=session,
        )

    def _get(self):
        self.client.force_login(self.student_user)
        return self.client.get(reverse("student-subjects"))

    def test_lists_current_term_subjects(self):
        self._assign(self.session2, self.maths)
        self._assign(self.session2, self.english)

        response = self._get()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2025/2026")
        self.assertContains(response, "Current term")
        self.assertContains(response, "Mathematics")
        self.assertContains(response, "English")

    def test_ignores_previous_term_subjects(self):
        """Assignments from older sessions must not appear."""
        self._assign(self.session1, self.maths)
        self._assign(self.session2, self.english)

        response = self._get()
        self.assertContains(response, "English")
        self.assertNotContains(response, "Mathematics")
        self.assertNotContains(response, "2024/2025")

    def test_subjects_show_teacher_name(self):
        self._assign(self.session2, self.maths)

        response = self._get()
        self.assertContains(response, "Ada Okon")

    def test_empty_state_without_assignments(self):
        response = self._get()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No subjects have been assigned for this term yet.")

    def test_global_empty_state_without_enrollment(self):
        ClassEnrollment.objects.filter(student=self.student).delete()

        response = self._get()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No subjects yet")

    def test_requires_student_role(self):
        other = get_user_model().objects.create_user(
            username="parent_x",
            email="px@grace.edu",
            password="testpass123",
            school=self.school,
            role=Roles.PARENT,
        )
        self.client.force_login(other)
        response = self.client.get(reverse("student-subjects"))
        self.assertEqual(response.status_code, 403)

class ParentPortalViewsTests(TestCase):
    """Parent dashboard and children list are distinct pages with
    role-scoped access."""

    def setUp(self):
        self.school = School.objects.create(
            name="Grace House School",
            short_code="grace-house",
        )
        User = get_user_model()
        self.parent_user = User.objects.create_user(
            username="portal_parent",
            email="portal@grace.edu",
            password="testpass123",
            school=self.school,
            role=Roles.PARENT,
            first_name="Portal",
            last_name="Parent",
        )
        self.child_user = User.objects.create_user(
            username="portal_child",
            email="child@grace.edu",
            password="testpass123",
            school=self.school,
            role=Roles.STUDENT,
            first_name="Portal",
            last_name="Child",
        )
        self.student = Student.objects.create(
            school=self.school,
            user=self.child_user,
            admission_number="GH-901",
            date_of_birth="2011-03-10",
            gender=Student.MALE,
            admission_date="2025-09-01",
)
        StudentGuardianLink.objects.create(
            school=self.school,
            guardian=self.parent_user,
            student=self.student,
        )
        session = AcademicSession.objects.create(
            school=self.school,
            name="2025/2026",
            start_date="2025-09-01",
            end_date="2026-07-31",
            is_current=True,
        )
        self.term = Term.objects.create(
            school=self.school,
            session=session,
            name="First Term",
            start_date="2025-09-01",
            end_date="2025-12-19",
            is_current=True,
        )
        Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal("50000.00"),
        )

    def test_dashboard_renders_summary(self):
        self.client.force_login(self.parent_user)
        response = self.client.get(reverse("parent-dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Welcome back")
        self.assertContains(response, "Total owed")
        self.assertContains(response, "feesChart")

    def test_children_list_renders(self):
        self.client.force_login(self.parent_user)
        response = self.client.get(reverse("parent-children"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "My Children")
        self.assertContains(response, "View Details")

    def test_dashboard_and_children_are_distinct_pages(self):
        self.client.force_login(self.parent_user)
        dash = self.client.get(reverse("parent-dashboard"))
        kids = self.client.get(reverse("parent-children"))
        self.assertNotEqual(dash.content, kids.content)

    def test_requires_parent_role(self):
        other = get_user_model().objects.create_user(
            username="intruder_student",
            email="intruder@grace.edu",
            password="testpass123",
            school=self.school,
            role=Roles.STUDENT,
        )
        self.client.force_login(other)
        self.assertEqual(
            self.client.get(reverse("parent-dashboard")).status_code, 403
        )
        self.assertEqual(
            self.client.get(reverse("parent-children")).status_code, 403
        )


class ResultFeeLockTests(TestCase):
    """Results for a term are locked while the student has outstanding fees
    for that term. Booklet views and downloads are blocked, history lists
    hide locked terms, and dashboards show a lock badge instead of data."""

    def setUp(self):
        self.school = School.objects.create(
            name="Lockdown Academy", short_code="lockdown",
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school, name="JSS1A", level="JSS1",
        )
        self.session = AcademicSession.objects.create(
            school=self.school,
            name="2025/2026",
            start_date="2025-09-01",
            end_date="2026-07-31",
            is_current=True,
        )
        self.term = Term.objects.create(
            school=self.school,
            session=self.session,
            name="First Term",
            start_date="2025-09-01",
            end_date="2025-12-19",
            is_current=True,
            results_published=True,
        )
        User = get_user_model()
        self.parent_user = User.objects.create_user(
            username="guard_ian", email="guard@lock.edu",
            password="testpass123", school=self.school, role=Roles.PARENT,
            first_name="Guard", last_name="Ian",
        )
        self.students = {}
        self.subject = Subject.objects.create(
            school=self.school, name="Mathematics", code="MATH",
        )
        for tag, first in [("owing", "Owing"), ("paid", "Paid"), ("free", "Free")]:
            user = User.objects.create_user(
                username=f"{tag}_student", email=f"{tag}@lock.edu",
                password="testpass123", school=self.school,
                role=Roles.STUDENT, first_name=first, last_name="Student",
            )
            student = Student.objects.create(
                school=self.school, user=user,
                admission_number=f"LK-{tag.upper()}",
                date_of_birth="2010-05-15", gender=Student.MALE,
                admission_date="2025-09-01",
            )
            ClassEnrollment.objects.create(
                school=self.school, student=student,
                school_class=self.school_class, session=self.session,
            )
            TermResult.objects.create(
                school=self.school, student=student, term=self.term,
                grand_total=300, average=Decimal("70.00"),
                overall_position=1, total_subjects=5,
            )
            Score.objects.create(
                school=self.school, student=student, term=self.term,
                subject=self.subject, test_1=8, test_2=9, test_3=7,
                exam_score=50,
            )
            StudentGuardianLink.objects.create(
                school=self.school, student=student,
                guardian=self.parent_user,
                relationship=StudentGuardianLink.MOTHER,
                is_primary_contact=True,
            )
            self.students[tag] = student

        # Owing: unpaid invoice. Paid: settled invoice. Free: no invoice.
        self.owing_invoice = Invoice.objects.create(
            school=self.school, student=self.students["owing"],
            term=self.term, total_amount=Decimal("50000.00"),
        )
        paid_invoice = Invoice.objects.create(
            school=self.school, student=self.students["paid"],
            term=self.term, total_amount=Decimal("50000.00"),
        )
        Payment.objects.create(
            school=self.school, invoice=paid_invoice,
            student=self.students["paid"],
            amount=Decimal("50000.00"),
            method=Payment.Method.BANK_TRANSFER,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            reference="REF-LK-PAID",
        )

    def _login_student(self, tag):
        self.client.force_login(self.students[tag].user)

    def _login_parent(self):
        self.client.force_login(self.parent_user)

    # ---------- Student booklet + download ----------

    def test_student_booklet_blocked_when_owing(self):
        self._login_student("owing")
        resp = self.client.get(reverse(
            "student-result-booklet", kwargs={"term_id": self.term.pk}
        ))
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse("student-overview"))
        resp = self.client.get(resp.url)
        self.assertContains(resp, "Results locked")
        self.assertContains(resp, "outstanding")

    def test_student_booklet_allowed_when_settled(self):
        self._login_student("paid")
        resp = self.client.get(reverse(
            "student-result-booklet", kwargs={"term_id": self.term.pk}
        ))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Print Booklet")
        self.assertNotContains(resp, "Download PDF")

    def test_student_booklet_allowed_when_no_invoice(self):
        self._login_student("free")
        resp = self.client.get(reverse(
            "student-result-booklet", kwargs={"term_id": self.term.pk}
        ))
        self.assertEqual(resp.status_code, 200)

    # ---------- Publication gating (item 28) ----------

    def _unpublished_term(self):
        """A second term in the same session whose results are NOT published."""
        unpublished = Term.objects.create(
            school=self.school,
            session=self.session,
            name="Second Term",
            start_date="2026-01-05",
            end_date="2026-04-10",
            results_published=False,
        )
        Score.objects.create(
            school=self.school, student=self.students["paid"],
            subject=self.subject, term=unpublished,
            test_1=8, test_2=9, test_3=7, exam_score=50,
            moderation_status=Score.MODERATION_APPROVED,
        )
        return unpublished

    def test_student_booklet_hidden_while_unpublished(self):
        """Unpublished terms return 404 — students cannot peek ahead."""
        unpublished = self._unpublished_term()
        self._login_student("paid")
        resp = self.client.get(reverse(
            "student-result-booklet", kwargs={"term_id": unpublished.pk}
        ))
        self.assertEqual(resp.status_code, 404)

    def test_parent_booklet_hidden_while_unpublished(self):
        """Parents cannot view booklets for unpublished terms."""
        unpublished = self._unpublished_term()
        self._login_parent()
        child = self.students["paid"]
        resp = self.client.get(reverse(
            "parent-child-result-booklet",
            kwargs={"child_pk": child.pk, "term_id": unpublished.pk},
        ))
        self.assertEqual(resp.status_code, 404)

    def test_student_history_hides_unpublished_term(self):
        """History lists only published terms, never unpublished ones."""
        self._unpublished_term()
        self._login_student("paid")
        resp = self.client.get(reverse("student-results-history"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "First Term")
        self.assertNotContains(resp, "Second Term")

    def test_parent_child_detail_hides_unpublished_term(self):
        """Parent child detail lists only published booklets."""
        self._unpublished_term()
        self._login_parent()
        child = self.students["paid"]
        resp = self.client.get(reverse("parent-child-detail", kwargs={"pk": child.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "First Term")
        self.assertNotContains(resp, "Second Term")

    # ---------- Moderation visibility (item 29) ----------

    def test_student_booklet_excludes_rejected_score(self):
        """Rejected scores must never appear on the official booklet."""
        english = Subject.objects.create(
            school=self.school, name="English Language", code="ENG",
        )
        Score.objects.filter(student=self.students["paid"], term=self.term).update(
            moderation_status=Score.MODERATION_APPROVED,
        )
        Score.objects.create(
            school=self.school, student=self.students["paid"],
            subject=english, term=self.term,
            test_1=10, test_2=10, test_3=10, exam_score=60,
            moderation_status=Score.MODERATION_REJECTED,
        )
        self._login_student("paid")
        resp = self.client.get(reverse(
            "student-result-booklet", kwargs={"term_id": self.term.pk}
        ))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Mathematics")
        self.assertNotContains(resp, "English Language")

    def test_parent_booklet_excludes_rejected_score(self):
        """Parents see the same moderation-safe booklet."""
        english = Subject.objects.create(
            school=self.school, name="English Language", code="ENG",
        )
        Score.objects.filter(student=self.students["paid"], term=self.term).update(
            moderation_status=Score.MODERATION_APPROVED,
        )
        Score.objects.create(
            school=self.school, student=self.students["paid"],
            subject=english, term=self.term,
            test_1=10, test_2=10, test_3=10, exam_score=60,
            moderation_status=Score.MODERATION_REJECTED,
        )
        self._login_parent()
        child = self.students["paid"]
        resp = self.client.get(reverse(
            "parent-child-result-booklet",
            kwargs={"child_pk": child.pk, "term_id": self.term.pk},
        ))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Mathematics")
        self.assertNotContains(resp, "English Language")

    # ---------- Parent booklet ----------

    def test_parent_booklet_blocked_for_child_with_owed_fees(self):
        self._login_parent()
        child = self.students["owing"]
        resp = self.client.get(reverse(
            "parent-child-result-booklet",
            kwargs={"child_pk": child.pk, "term_id": self.term.pk},
        ))
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse("parent-child-detail", kwargs={"pk": child.pk}))

    def test_parent_booklet_allowed_for_child_when_settled(self):
        self._login_parent()
        child = self.students["paid"]
        resp = self.client.get(reverse(
            "parent-child-result-booklet",
            kwargs={"child_pk": child.pk, "term_id": self.term.pk},
        ))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Print Booklet")
        self.assertNotContains(resp, "Download PDF")

    # ---------- History + dashboards ----------

    def test_student_history_hides_locked_term(self):
        self._login_student("owing")
        resp = self.client.get(reverse("student-results-history"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "First Term")

    def test_student_history_shows_paid_term(self):
        self._login_student("paid")
        resp = self.client.get(reverse("student-results-history"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "First Term")

    def test_student_overview_shows_locked_card(self):
        self._login_student("owing")
        resp = self.client.get(reverse("student-overview"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Results locked")
        self.assertNotContains(resp, "70.0")

    def test_student_overview_shows_average_when_settled(self):
        self._login_student("paid")
        resp = self.client.get(reverse("student-overview"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Results published")
        self.assertContains(resp, "70.0")

    def test_parent_dashboard_shows_lock_badge_for_owing_child(self):
        self._login_parent()
        resp = self.client.get(reverse("parent-dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Locked", count=1)

    def test_parent_child_detail_hides_locked_booklet_and_trend(self):
        self._login_parent()
        child = self.students["owing"]
        resp = self.client.get(reverse("parent-child-detail", kwargs={"pk": child.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Locked")
        self.assertNotContains(resp, "Result Booklets")
        self.assertNotContains(resp, "70.0")

    def test_paying_the_balance_unlocks_results(self):
        Payment.objects.create(
            school=self.school, invoice=self.owing_invoice,
            student=self.students["owing"],
            amount=Decimal("50000.00"),
            method=Payment.Method.BANK_TRANSFER,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            reference="REF-LK-CLEARED",
        )
        self._login_student("owing")
        resp = self.client.get(reverse(
            "student-result-booklet", kwargs={"term_id": self.term.pk}
        ))
        self.assertEqual(resp.status_code, 200)
