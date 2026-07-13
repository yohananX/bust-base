from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from .models import School, AcademicSession, Term
from .middleware import SchoolMiddleware


class SchoolModelTests(TestCase):
    """Tests for the School model."""

    def setUp(self):
        self.school = School.objects.create(
            name="Grace House School",
            short_code="grace-house",
            address="123 Main St",
            phone="555-0100",
            email="info@gracehouse.edu",
        )

    def test_school_creation(self):
        self.assertEqual(self.school.name, "Grace House School")
        self.assertEqual(self.school.short_code, "grace-house")
        self.assertTrue(self.school.is_active)
        self.assertIsNotNone(self.school.created_at)

    def test_school_str(self):
        self.assertEqual(str(self.school), "Grace House School")

    def test_school_is_active_default(self):
        school2 = School.objects.create(name="Test School", short_code="test")
        self.assertTrue(school2.is_active)


class AcademicSessionModelTests(TestCase):
    """Tests for AcademicSession model."""

    def setUp(self):
        self.school = School.objects.create(
            name="Grace House School",
            short_code="grace-house",
        )

    def test_session_creation(self):
        session = AcademicSession.objects.create(
            school=self.school,
            name="2025/2026",
            start_date="2025-09-01",
            end_date="2026-07-31",
            is_current=True,
        )
        self.assertEqual(str(session), "2025/2026 (Grace House School)")

    def test_only_one_current_session_per_school(self):
        session1 = AcademicSession.objects.create(
            school=self.school,
            name="2024/2025",
            start_date="2024-09-01",
            end_date="2025-07-31",
            is_current=True,
        )
        session2 = AcademicSession.objects.create(
            school=self.school,
            name="2025/2026",
            start_date="2025-09-01",
            end_date="2026-07-31",
            is_current=True,
        )
        session1.refresh_from_db()
        self.assertFalse(session1.is_current)
        self.assertTrue(session2.is_current)

    def test_unique_session_name_per_school(self):
        AcademicSession.objects.create(
            school=self.school,
            name="2025/2026",
            start_date="2025-09-01",
            end_date="2026-07-31",
        )
        with self.assertRaises(Exception):
            AcademicSession.objects.create(
                school=self.school,
                name="2025/2026",
                start_date="2025-09-01",
                end_date="2026-07-31",
            )

    def test_current_session_independent_across_schools(self):
        school2 = School.objects.create(name="Other School", short_code="other")
        session_a = AcademicSession.objects.create(
            school=self.school, name="2025/2026",
            start_date="2025-09-01", end_date="2026-07-31", is_current=True,
        )
        session_b = AcademicSession.objects.create(
            school=school2, name="2025/2026",
            start_date="2025-09-01", end_date="2026-07-31", is_current=True,
        )
        session_a.refresh_from_db()
        session_b.refresh_from_db()
        self.assertTrue(session_a.is_current)
        self.assertTrue(session_b.is_current)


class TermModelTests(TestCase):
    """Tests for Term model."""

    def setUp(self):
        self.school = School.objects.create(
            name="Grace House School",
            short_code="grace-house",
        )
        self.session = AcademicSession.objects.create(
            school=self.school,
            name="2025/2026",
            start_date="2025-09-01",
            end_date="2026-07-31",
        )

    def test_term_creation(self):
        term = Term.objects.create(
            school=self.school,
            session=self.session,
            name="First Term",
            start_date="2025-09-01",
            end_date="2025-12-20",
        )
        self.assertIn("First Term", str(term))
        self.assertIn("2025/2026", str(term))

    def test_only_one_current_term_per_school(self):
        """Spec says: only one term total can be current across all sessions for a school."""
        term1 = Term.objects.create(
            school=self.school, session=self.session,
            name="First Term", start_date="2025-09-01", end_date="2025-12-20",
            is_current=True,
        )
        term2 = Term.objects.create(
            school=self.school, session=self.session,
            name="Second Term", start_date="2026-01-10", end_date="2026-04-10",
            is_current=True,
        )
        term1.refresh_from_db()
        term2.refresh_from_db()
        self.assertFalse(term1.is_current)
        self.assertTrue(term2.is_current)

    def test_unique_term_name_per_session(self):
        Term.objects.create(
            school=self.school, session=self.session,
            name="First Term", start_date="2025-09-01", end_date="2025-12-20",
        )
        with self.assertRaises(Exception):
            Term.objects.create(
                school=self.school, session=self.session,
                name="First Term", start_date="2025-09-01", end_date="2025-12-20",
            )


class SchoolScopingTests(TestCase):
    """Critical multi-tenant isolation tests."""

    def setUp(self):
        self.school_a = School.objects.create(
            name="School A", short_code="school-a",
        )
        self.school_b = School.objects.create(
            name="School B", short_code="school-b",
        )

        self.session_a = AcademicSession.objects.create(
            school=self.school_a, name="2025/2026",
            start_date="2025-09-01", end_date="2026-07-31",
        )
        self.session_b = AcademicSession.objects.create(
            school=self.school_b, name="2025/2026",
            start_date="2025-09-01", end_date="2026-07-31",
        )

        self.term_a = Term.objects.create(
            school=self.school_a, session=self.session_a,
            name="First Term", start_date="2025-09-01", end_date="2025-12-20",
        )
        self.term_b = Term.objects.create(
            school=self.school_b, session=self.session_b,
            name="First Term", start_date="2025-09-01", end_date="2025-12-20",
        )

    def test_session_scoping_isolation(self):
        """School A's sessions should not include School B's sessions."""
        sessions_a = list(AcademicSession.objects.for_school(self.school_a))
        self.assertIn(self.session_a, sessions_a)
        self.assertNotIn(self.session_b, sessions_a)

    def test_term_scoping_isolation(self):
        """School A's terms should not include School B's terms."""
        terms_a = list(Term.objects.for_school(self.school_a))
        self.assertIn(self.term_a, terms_a)
        self.assertNotIn(self.term_b, terms_a)

    def test_session_name_collision_across_schools(self):
        """Different schools can have sessions with the same name."""
        sessions_a = AcademicSession.objects.for_school(self.school_a)
        sessions_b = AcademicSession.objects.for_school(self.school_b)
        self.assertEqual(sessions_a.count(), 1)
        self.assertEqual(sessions_b.count(), 1)
        self.assertEqual(sessions_a.first().name, sessions_b.first().name)

    def test_current_session_independence(self):
        """Setting a session current in school A should not affect school B."""
        session_a2 = AcademicSession.objects.create(
            school=self.school_a, name="2024/2025",
            start_date="2024-09-01", end_date="2025-07-31", is_current=True,
        )
        session_b2 = AcademicSession.objects.create(
            school=self.school_b, name="2024/2025",
            start_date="2024-09-01", end_date="2025-07-31",
        )
        session_b2.refresh_from_db()
        self.assertFalse(session_b2.is_current)


class SchoolMiddlewareTests(TestCase):
    """Tests for the SchoolMiddleware."""

    def setUp(self):
        self.factory = RequestFactory()
        self.school = School.objects.create(
            name="Grace House", short_code="grace",
        )
        User = get_user_model()
        self.user = User.objects.create_user(
            username="admin",
            email="admin@grace.edu",
            password="testpass123",
            school=self.school,
            role="ADMIN",
        )

    def test_middleware_sets_school_for_authenticated_user(self):
        request = self.factory.get('/')
        request.user = self.user
        middleware = SchoolMiddleware(lambda req: None)
        middleware(request)
        self.assertEqual(request.school, self.school)

    def test_middleware_sets_none_for_anonymous(self):
        from django.contrib.auth.models import AnonymousUser
        request = self.factory.get('/')
        request.user = AnonymousUser()
        middleware = SchoolMiddleware(lambda req: None)
        middleware(request)
        self.assertIsNone(request.school)
