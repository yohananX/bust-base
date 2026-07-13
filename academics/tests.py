from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from accounts.models import Roles, User
from academics.models import Score, Subject, TeacherAssignment
from academics.permissions import teacher_can_access
from academics.ranking import compute_positions
from core.models import AcademicSession, School, Term
from students.models import (
    ClassEnrollment,
    SchoolClass,
    Student as StudentProfile,
)


class BaseTest(TestCase):
    """Shared setup for most test cases."""

    def setUp(self):
        self.school = School.objects.create(name="Test School", short_code="test")
        self.session = AcademicSession.objects.create(
            school=self.school, name="2025/2026",
            start_date="2025-09-01", end_date="2026-07-31", is_current=True,
        )
        self.term = Term.objects.create(
            school=self.school, session=self.session,
            name="First Term", start_date="2025-09-01", end_date="2025-12-20",
            is_current=True,
        )
        self.teacher_user = User.objects.create_user(
            username="teacher", email="t@t.com", password="pass",
            school=self.school, role=Roles.TEACHER,
        )
        self.student_user = User.objects.create_user(
            username="student", email="s@s.com", password="pass",
            school=self.school, role=Roles.STUDENT,
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school, name="JSS1A", level="JSS1",
        )
        self.subject = Subject.objects.create(
            school=self.school, name="Mathematics", code="MTH",
        )
        self.student_profile = StudentProfile.objects.create(
            school=self.school, user=self.student_user,
            admission_number="001", date_of_birth="2010-01-01",
            gender=StudentProfile.MALE, admission_date="2025-09-01",
        )
        self.enrollment = ClassEnrollment.objects.create(
            school=self.school, student=self.student_profile,
            school_class=self.school_class, session=self.session,
            is_current=True,
        )
        self.assignment = TeacherAssignment.objects.create(
            school=self.school, teacher=self.teacher_user,
            subject=self.subject, school_class=self.school_class,
            session=self.session,
        )


# ---------------------------------------------------------------------------
# Subject model tests
# ---------------------------------------------------------------------------

class SubjectModelTests(TestCase):
    """Tests for the Subject model."""

    def setUp(self):
        self.school = School.objects.create(
            name="Grace House School",
            short_code="grace-house",
        )

    def test_subject_creation(self):
        """Subject should be created with correct default pass_mark."""
        subject = Subject.objects.create(
            school=self.school,
            name="Mathematics",
            code="MTH",
        )
        self.assertEqual(subject.name, "Mathematics")
        self.assertEqual(subject.code, "MTH")
        self.assertEqual(subject.pass_mark, 40)

    def test_subject_unique_code_per_school(self):
        """Same school cannot have two subjects with the same code.

        Two different schools CAN have the same code.
        """
        Subject.objects.create(
            school=self.school, name="Mathematics", code="MTH",
        )
        # Same school, same code → IntegrityError
        with self.assertRaises(IntegrityError):
            Subject.objects.create(
                school=self.school, name="Maths", code="MTH",
            )

    def test_same_code_different_schools(self):
        """Two different schools can have subjects with the same code."""
        school2 = School.objects.create(name="Other School", short_code="other")

        Subject.objects.create(
            school=self.school, name="Mathematics", code="MTH",
        )
        Subject.objects.create(
            school=school2, name="Mathematics", code="MTH",
        )

        self.assertEqual(Subject.objects.for_school(self.school).count(), 1)
        self.assertEqual(Subject.objects.for_school(school2).count(), 1)

    def test_cross_school_isolation(self):
        """Subjects from different schools should not interfere with each other."""
        school2 = School.objects.create(name="Other School", short_code="other")

        Subject.objects.create(
            school=self.school, name="Mathematics", code="MTH",
        )
        Subject.objects.create(
            school=school2, name="Mathematics", code="MTH",
        )

        self.assertEqual(Subject.objects.for_school(self.school).count(), 1)
        self.assertEqual(Subject.objects.for_school(school2).count(), 1)


# ---------------------------------------------------------------------------
# TeacherAssignment model tests
# ---------------------------------------------------------------------------

class TeacherAssignmentModelTests(TestCase):
    """Tests for the TeacherAssignment model."""

    def setUp(self):
        self.school = School.objects.create(
            name="Grace House School",
            short_code="grace-house",
        )
        self.teacher_user = User.objects.create_user(
            username="mr_smith",
            email="smith@grace.edu",
            password="testpass123",
            school=self.school,
            role=Roles.TEACHER,
            first_name="John",
            last_name="Smith",
        )
        self.admin_user = User.objects.create_user(
            username="admin",
            email="admin@grace.edu",
            password="testpass123",
            school=self.school,
            role=Roles.ADMIN,
        )
        self.subject = Subject.objects.create(
            school=self.school, name="Mathematics", code="MTH",
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school, name="JSS1A", level="JSS1",
        )
        self.session = AcademicSession.objects.create(
            school=self.school,
            name="2025/2026",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 7, 31),
        )

    def test_teacher_assignment_creation(self):
        """A valid TeacherAssignment should be created successfully."""
        assignment = TeacherAssignment.objects.create(
            school=self.school,
            teacher=self.teacher_user,
            subject=self.subject,
            school_class=self.school_class,
            session=self.session,
        )
        self.assertIsNotNone(assignment.pk)
        self.assertEqual(
            str(assignment),
            f"{self.teacher_user} - {self.subject} ({self.school_class}, {self.session})",
        )

    def test_teacher_assignment_role_validation(self):
        """Creating a TeacherAssignment with a non-TEACHER user should raise ValidationError."""
        with self.assertRaises(ValidationError):
            TeacherAssignment.objects.create(
                school=self.school,
                teacher=self.admin_user,
                subject=self.subject,
                school_class=self.school_class,
                session=self.session,
            )

    def test_teacher_can_access_assigned(self):
        """teacher_can_access should return True for an assigned teacher."""
        TeacherAssignment.objects.create(
            school=self.school,
            teacher=self.teacher_user,
            subject=self.subject,
            school_class=self.school_class,
            session=self.session,
        )
        self.assertTrue(
            teacher_can_access(
                self.teacher_user, self.subject, self.school_class, self.session,
            )
        )

    def test_teacher_can_access_unassigned(self):
        """teacher_can_access should return False for a different teacher."""
        other_teacher = User.objects.create_user(
            username="other_teacher",
            email="other@grace.edu",
            password="testpass123",
            school=self.school,
            role=Roles.TEACHER,
        )
        TeacherAssignment.objects.create(
            school=self.school,
            teacher=self.teacher_user,
            subject=self.subject,
            school_class=self.school_class,
            session=self.session,
        )
        self.assertFalse(
            teacher_can_access(
                other_teacher, self.subject, self.school_class, self.session,
            )
        )


# ---------------------------------------------------------------------------
# Score model tests
# ---------------------------------------------------------------------------

class ScoreModelTests(BaseTest):
    """Tests for the Score model fields, computed properties, and constraints."""

    def test_score_creation_and_validation(self):
        """Score with partial fields should compute total_score correctly.

        Verify test_1=15 raises ValidationError and exam_score=75 raises
        ValidationError via full_clean.
        """
        score = Score.objects.create(
            school=self.school,
            student=self.student_profile,
            subject=self.subject,
            term=self.term,
            test_1=8,
            exam_score=65,
            entered_by=self.teacher_user,
        )
        self.assertEqual(score.total_score, 73)

        # test_1 above 10 → ValidationError
        invalid_score = Score(
            school=self.school,
            student=self.student_profile,
            subject=self.subject,
            term=self.term,
            test_1=15,
            entered_by=self.teacher_user,
        )
        with self.assertRaises(ValidationError):
            invalid_score.full_clean()

        # exam_score above 70 → ValidationError
        invalid_exam = Score(
            school=self.school,
            student=self.student_profile,
            subject=self.subject,
            term=self.term,
            exam_score=75,
            entered_by=self.teacher_user,
        )
        with self.assertRaises(ValidationError):
            invalid_exam.full_clean()

    def test_score_computed_properties_complete_and_passing(self):
        """A fully filled Score above pass_mark should have is_complete=True, passed=True."""
        score = Score.objects.create(
            school=self.school,
            student=self.student_profile,
            subject=self.subject,
            term=self.term,
            test_1=8,
            test_2=7,
            test_3=9,
            exam_score=60,
            entered_by=self.teacher_user,
        )
        self.assertEqual(score.total_score, 84)
        self.assertTrue(score.is_complete)
        self.assertTrue(score.passed)

    def test_score_computed_properties_complete_and_failing(self):
        """A fully filled Score below pass_mark should have is_complete=True, passed=False."""
        score = Score.objects.create(
            school=self.school,
            student=self.student_profile,
            subject=self.subject,
            term=self.term,
            test_1=2,
            test_2=3,
            test_3=1,
            exam_score=10,
            entered_by=self.teacher_user,
        )
        self.assertEqual(score.total_score, 16)
        self.assertTrue(score.is_complete)
        self.assertFalse(score.passed)

    def test_score_computed_properties_incomplete(self):
        """An incomplete Score should have is_complete=False, passed=None.

        total_score should still sum the non-None values.
        """
        score = Score.objects.create(
            school=self.school,
            student=self.student_profile,
            subject=self.subject,
            term=self.term,
            test_1=5,
            entered_by=self.teacher_user,
        )
        self.assertEqual(score.total_score, 5)
        self.assertFalse(score.is_complete)
        self.assertIsNone(score.passed)

    def test_score_computed_properties_partial_sum(self):
        """Partial scores sum non-None values correctly."""
        score = Score.objects.create(
            school=self.school,
            student=self.student_profile,
            subject=self.subject,
            term=self.term,
            test_1=8,
            test_2=7,
            exam_score=50,
            entered_by=self.teacher_user,
        )
        # test_3 is None → treated as 0
        self.assertEqual(score.total_score, 65)
        self.assertFalse(score.is_complete)
        self.assertIsNone(score.passed)

    def test_score_unique_constraint(self):
        """Creating a duplicate (student, subject, term) should raise IntegrityError."""
        Score.objects.create(
            school=self.school,
            student=self.student_profile,
            subject=self.subject,
            term=self.term,
            entered_by=self.teacher_user,
        )
        with self.assertRaises(IntegrityError):
            Score.objects.create(
                school=self.school,
                student=self.student_profile,
                subject=self.subject,
                term=self.term,
                entered_by=self.teacher_user,
            )

    def test_cross_school_isolation(self):
        """Scores from different schools should not interfere with each other."""
        # School B with identical setup
        school2 = School.objects.create(name="Other School", short_code="other")
        session2 = AcademicSession.objects.create(
            school=school2, name="2025/2026",
            start_date="2025-09-01", end_date="2026-07-31", is_current=True,
        )
        term2 = Term.objects.create(
            school=school2, session=session2,
            name="First Term", start_date="2025-09-01", end_date="2025-12-20",
            is_current=True,
        )
        subject2 = Subject.objects.create(
            school=school2, name="Mathematics", code="MTH",
        )
        student_user2 = User.objects.create_user(
            username="student2", email="s2@s2.com", password="pass",
            school=school2, role=Roles.STUDENT,
        )
        student_profile2 = StudentProfile.objects.create(
            school=school2, user=student_user2,
            admission_number="002", date_of_birth="2010-01-01",
            gender=StudentProfile.MALE, admission_date="2025-09-01",
        )

        teacher2 = User.objects.create_user(
            username="teacher2", email="t2@t2.com", password="pass",
            school=school2, role=Roles.TEACHER,
        )

        # Create score in School A
        Score.objects.create(
            school=self.school,
            student=self.student_profile,
            subject=self.subject,
            term=self.term,
            test_1=8,
            test_2=7,
            test_3=9,
            exam_score=60,
            entered_by=self.teacher_user,
        )

        # Create score in School B
        Score.objects.create(
            school=school2,
            student=student_profile2,
            subject=subject2,
            term=term2,
            test_1=5,
            test_2=5,
            test_3=5,
            exam_score=30,
            entered_by=teacher2,
        )

        # School A should have 1 score, School B should have 1 score
        self.assertEqual(Score.objects.for_school(self.school).count(), 1)
        self.assertEqual(Score.objects.for_school(school2).count(), 1)

        # The School A score should NOT appear in School B's queryset
        score_a = Score.objects.for_school(self.school).first()
        score_b = Score.objects.for_school(school2).first()
        self.assertNotEqual(score_a.pk, score_b.pk)
        self.assertNotEqual(score_a.total_score, score_b.total_score)


# ---------------------------------------------------------------------------
# Ranking tests
# ---------------------------------------------------------------------------

class RankingTests(TestCase):
    """Tests for compute_positions with Olympic/dense ranking."""

    def setUp(self):
        self.school = School.objects.create(
            name="Grace House School",
            short_code="grace-house",
        )
        self.teacher_user = User.objects.create_user(
            username="mr_smith",
            email="smith@grace.edu",
            password="testpass123",
            school=self.school,
            role=Roles.TEACHER,
        )
        self.subject = Subject.objects.create(
            school=self.school, name="Mathematics", code="MTH", pass_mark=40,
        )
        self.session = AcademicSession.objects.create(
            school=self.school,
            name="2025/2026",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 7, 31),
        )
        self.term = Term.objects.create(
            school=self.school,
            session=self.session,
            name="First Term",
            start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 20),
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school, name="JSS1A", level="JSS1",
        )

    # -- helpers -----------------------------------------------------------

    def _create_student(self, username, admission_number):
        """Create a student user + profile."""
        user = User.objects.create_user(
            username=username,
            email=f"{username}@grace.edu",
            password="testpass123",
            school=self.school,
            role=Roles.STUDENT,
        )
        return StudentProfile.objects.create(
            school=self.school,
            user=user,
            admission_number=admission_number,
            date_of_birth=date(2010, 1, 1),
            gender=StudentProfile.MALE,
            admission_date=date(2025, 9, 1),
        )

    def _enroll(self, student):
        """Enroll a student in the test class."""
        return ClassEnrollment.objects.create(
            school=self.school,
            student=student,
            school_class=self.school_class,
            session=self.session,
            is_current=True,
        )

    def _score(self, student, test_1, test_2, test_3, exam_score):
        """Create a Score record."""
        return Score.objects.create(
            school=self.school,
            student=student,
            subject=self.subject,
            term=self.term,
            test_1=test_1,
            test_2=test_2,
            test_3=test_3,
            exam_score=exam_score,
            entered_by=self.teacher_user,
        )

    # -- tests -------------------------------------------------------------

    def test_tied_ranking(self):
        """Olympic/dense ranking: tied scores share same position, next skips.

        Scores:   90  85  85  70  → total_score
        Expected:  1   2   2   4  → position
        """
        # Student A: total=90
        stu_a = self._create_student("stu_a", "A001")
        self._enroll(stu_a)
        self._score(stu_a, test_1=10, test_2=10, test_3=10, exam_score=60)

        # Student B: total=85
        stu_b = self._create_student("stu_b", "A002")
        self._enroll(stu_b)
        self._score(stu_b, test_1=8, test_2=9, test_3=8, exam_score=60)

        # Student C: total=85 (tied with B)
        stu_c = self._create_student("stu_c", "A003")
        self._enroll(stu_c)
        self._score(stu_c, test_1=9, test_2=8, test_3=8, exam_score=60)

        # Student D: total=70
        stu_d = self._create_student("stu_d", "A004")
        self._enroll(stu_d)
        self._score(stu_d, test_1=5, test_2=5, test_3=10, exam_score=50)

        compute_positions(self.school_class, self.subject, self.term)

        positions = {
            s.student.user.username: s.position
            for s in Score.objects.filter(subject=self.subject, term=self.term)
        }

        self.assertEqual(positions["stu_a"], 1)
        self.assertEqual(positions["stu_b"], 2)
        self.assertEqual(positions["stu_c"], 2)
        self.assertEqual(positions["stu_d"], 4)

    def test_incomplete_excluded_from_ranking(self):
        """Scores with any component missing should have position=None and not affect ranking.

        Student A: complete (total 84) → position 1
        Student B: complete (total 68) → position 2
        Student C: incomplete (test_1 only) → position None
        """
        stu_a = self._create_student("stu_a", "B001")
        self._enroll(stu_a)
        self._score(stu_a, test_1=8, test_2=7, test_3=9, exam_score=60)

        stu_b = self._create_student("stu_b", "B002")
        self._enroll(stu_b)
        self._score(stu_b, test_1=5, test_2=6, test_3=7, exam_score=50)

        # Incomplete: test_2, test_3, and exam_score are None
        stu_c = self._create_student("stu_c", "B003")
        self._enroll(stu_c)
        Score.objects.create(
            school=self.school,
            student=stu_c,
            subject=self.subject,
            term=self.term,
            test_1=5,
            entered_by=self.teacher_user,
        )

        compute_positions(self.school_class, self.subject, self.term)

        scores = Score.objects.filter(subject=self.subject, term=self.term)
        positions = {s.student.user.username: s.position for s in scores}

        self.assertEqual(positions["stu_a"], 1)
        self.assertEqual(positions["stu_b"], 2)
        self.assertIsNone(positions["stu_c"])

    def test_ranking_all_tied(self):
        """All students with the same total_score should get position 1."""
        for username, adm_no in [("stu_a", "C001"), ("stu_b", "C002"), ("stu_c", "C003")]:
            student = self._create_student(username, adm_no)
            self._enroll(student)
            self._score(student, test_1=8, test_2=7, test_3=9, exam_score=60)

        compute_positions(self.school_class, self.subject, self.term)

        positions = {
            s.student.user.username: s.position
            for s in Score.objects.filter(subject=self.subject, term=self.term)
        }

        self.assertEqual(positions["stu_a"], 1)
        self.assertEqual(positions["stu_b"], 1)
        self.assertEqual(positions["stu_c"], 1)

    def test_ranking_single_student(self):
        """A single student should get position 1."""
        student = self._create_student("only_stu", "D001")
        self._enroll(student)
        self._score(student, test_1=8, test_2=7, test_3=9, exam_score=60)

        result = compute_positions(self.school_class, self.subject, self.term)

        self.assertEqual(result, 1)
        score = Score.objects.get(student=student)
        self.assertEqual(score.position, 1)

    def test_ranking_no_complete_scores(self):
        """When no scores are complete, compute_positions should return 0."""
        student = self._create_student("incomplete", "E001")
        self._enroll(student)
        Score.objects.create(
            school=self.school,
            student=student,
            subject=self.subject,
            term=self.term,
            test_1=5,
            entered_by=self.teacher_user,
        )

        result = compute_positions(self.school_class, self.subject, self.term)

        self.assertEqual(result, 0)
        score = Score.objects.get(student=student)
        self.assertIsNone(score.position)
