from django.test import TestCase, RequestFactory
from django.core.exceptions import PermissionDenied
from django.contrib.auth import get_user_model
from django.views import View
from core.models import School
from .models import Roles
from .mixins import RoleRequiredMixin


class UserModelTests(TestCase):
    """Tests for the custom User model."""

    def setUp(self):
        self.school = School.objects.create(
            name="Grace House School",
            short_code="grace-house",
        )
        User = get_user_model()
        self.user = User.objects.create_user(
            username="john",
            email="john@grace.edu",
            password="testpass123",
            school=self.school,
            role=Roles.TEACHER,
            first_name="John",
            last_name="Doe",
        )

    def test_user_creation(self):
        self.assertEqual(self.user.username, "john")
        self.assertEqual(self.user.school, self.school)
        self.assertEqual(self.user.role, Roles.TEACHER)
        self.assertEqual(self.user.email, "john@grace.edu")

    def test_user_str(self):
        self.assertEqual(str(self.user), "John Doe")

    def test_user_str_fallback_to_username(self):
        User = get_user_model()
        user2 = User.objects.create_user(
            username="jane",
            email="jane@grace.edu",
            password="testpass123",
            school=self.school,
            role=Roles.STUDENT,
        )
        self.assertEqual(str(user2), "jane")

    def test_required_fields(self):
        User = get_user_model()
        self.assertIn('email', User.REQUIRED_FIELDS)
        self.assertIn('school', User.REQUIRED_FIELDS)
        self.assertIn('role', User.REQUIRED_FIELDS)


class AdminCanCreateFullFixtureTest(TestCase):
    """Integration test: admin can create school, session, term, and users."""

    def setUp(self):
        self.school = School.objects.create(
            name="Grace House School",
            short_code="grace-house",
        )
        self.session = self.school.academicsession_set.create(
            name="2025/2026",
            start_date="2025-09-01",
            end_date="2026-07-31",
            is_current=True,
        )
        self.term = self.school.term_set.create(
            session=self.session,
            name="First Term",
            start_date="2025-09-01",
            end_date="2025-12-20",
            is_current=True,
        )
        User = get_user_model()
        self.admin_user = User.objects.create_user(
            username="admin", email="admin@grace.edu",
            password="pass123", school=self.school, role=Roles.ADMIN,
        )
        self.teacher_user = User.objects.create_user(
            username="teacher", email="teacher@grace.edu",
            password="pass123", school=self.school, role=Roles.TEACHER,
        )
        self.student_user = User.objects.create_user(
            username="student", email="student@grace.edu",
            password="pass123", school=self.school, role=Roles.STUDENT,
        )
        self.parent_user = User.objects.create_user(
            username="parent", email="parent@grace.edu",
            password="pass123", school=self.school, role=Roles.PARENT,
        )

    def test_all_entities_created(self):
        self.assertEqual(School.objects.count(), 1)
        self.assertEqual(self.school.academicsession_set.count(), 1)
        self.assertEqual(self.school.term_set.count(), 1)
        User = get_user_model()
        self.assertEqual(User.objects.count(), 4)

    def test_all_roles_present(self):
        User = get_user_model()
        roles = set(User.objects.values_list('role', flat=True))
        self.assertEqual(roles, {Roles.ADMIN, Roles.TEACHER, Roles.STUDENT, Roles.PARENT})


class RoleRequiredMixinTests(TestCase):
    """Tests for RoleRequiredMixin."""

    class MockView(RoleRequiredMixin, View):
        allowed_roles = [Roles.ADMIN, Roles.TEACHER]

        def get(self, request, *args, **kwargs):
            return "allowed"

    class MockViewStudentOnly(RoleRequiredMixin, View):
        allowed_roles = [Roles.STUDENT]

        def get(self, request, *args, **kwargs):
            return "allowed"

    def setUp(self):
        self.factory = RequestFactory()
        self.school = School.objects.create(
            name="Grace House", short_code="grace",
        )
        User = get_user_model()
        self.admin_user = User.objects.create_user(
            username="admin", email="a@b.com",
            password="pass", school=self.school, role=Roles.ADMIN,
        )
        self.student_user = User.objects.create_user(
            username="student", email="s@b.com",
            password="pass", school=self.school, role=Roles.STUDENT,
        )

    def test_admin_allowed(self):
        request = self.factory.get('/')
        request.user = self.admin_user
        view = self.MockView()
        view.setup(request)
        response = view.dispatch(request)
        self.assertEqual(response, "allowed")

    def test_student_blocked(self):
        request = self.factory.get('/')
        request.user = self.student_user
        view = self.MockView()
        view.setup(request)
        with self.assertRaises(PermissionDenied):
            view.dispatch(request)

    def test_student_allowed_for_student_view(self):
        request = self.factory.get('/')
        request.user = self.student_user
        view = self.MockViewStudentOnly()
        view.setup(request)
        response = view.dispatch(request)
        self.assertEqual(response, "allowed")

    def test_admin_blocked_for_student_view(self):
        request = self.factory.get('/')
        request.user = self.admin_user
        view = self.MockViewStudentOnly()
        view.setup(request)
        with self.assertRaises(PermissionDenied):
            view.dispatch(request)

    def test_unauthenticated_redirected(self):
        from django.contrib.auth.models import AnonymousUser
        request = self.factory.get('/')
        request.user = AnonymousUser()
        view = self.MockView()
        view.setup(request)
        response = view.dispatch(request)
        self.assertEqual(response.status_code, 302)


class SchoolScopingIsolationTest(TestCase):
    """Critical test: two schools with overlapping data must not leak."""

    def setUp(self):
        self.school_a = School.objects.create(
            name="School A", short_code="school-a",
        )
        self.school_b = School.objects.create(
            name="School B", short_code="school-b",
        )
        User = get_user_model()
        self.user_a = User.objects.create_user(
            username="user_a", email="a@a.com",
            password="pass", school=self.school_a, role=Roles.TEACHER,
        )
        self.user_b = User.objects.create_user(
            username="user_b", email="b@b.com",
            password="pass", school=self.school_b, role=Roles.TEACHER,
        )

    def test_user_scoping_isolation(self):
        """Users from school A should not be visible when querying school B."""
        User = get_user_model()
        users_a = User.objects.filter(school=self.school_a)
        users_b = User.objects.filter(school=self.school_b)
        self.assertIn(self.user_a, users_a)
        self.assertNotIn(self.user_b, users_a)
        self.assertIn(self.user_b, users_b)
        self.assertNotIn(self.user_a, users_b)

    def test_school_scoping_middleware(self):
        """Test complete isolation through middleware-like behavior."""
        from core.middleware import SchoolMiddleware
        factory = RequestFactory()

        request = factory.get('/')
        request.user = self.user_a
        middleware = SchoolMiddleware(lambda req: None)
        middleware(request)
        self.assertEqual(request.school, self.school_a)
        self.assertNotEqual(request.school, self.school_b)
