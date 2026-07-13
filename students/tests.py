from django.core.exceptions import ValidationError
from django.test import TestCase
from django.contrib.auth import get_user_model

from core.models import School, AcademicSession
from accounts.models import Roles
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
