"""Tests for teacher search on the assignment management page."""

from django.test import TestCase
from django.urls import reverse

from accounts.models import Roles, User
from core.models import School


class TeacherAssignmentSearchTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(
            name="Test School",
            short_code="test",
        )
        self.admin = User.objects.create_user(
            username="admin",
            password="testpass123",
            school=self.school,
            role=Roles.ADMIN,
        )
        self.ada = User.objects.create_user(
            username="ada",
            email="ada@example.com",
            password="testpass123",
            first_name="Ada",
            last_name="Lovelace",
            school=self.school,
            role=Roles.TEACHER,
        )
        self.grace = User.objects.create_user(
            username="grace",
            email="grace@example.com",
            password="testpass123",
            first_name="Grace",
            last_name="Hopper",
            school=self.school,
            role=Roles.TEACHER,
        )
        self.client.force_login(self.admin)

    def test_search_api_returns_only_current_school_teachers(self):
        school2 = School.objects.create(name="Other School", short_code="other")
        User.objects.create_user(
            username="evil",
            email="evil@other.com",
            password="testpass123",
            first_name="Evil",
            last_name="Teacher",
            school=school2,
            role=Roles.TEACHER,
        )

        response = self.client.get(reverse("school_admin:teacher_search_api"))
        self.assertEqual(response.status_code, 200)
        names = [d["name"] for d in response.json()]
        self.assertIn("Ada Lovelace", names)
        self.assertIn("Grace Hopper", names)
        self.assertNotIn("Evil Teacher", names)
