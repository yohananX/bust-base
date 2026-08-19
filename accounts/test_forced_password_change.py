
from django.test import TestCase
from django.contrib.auth import get_user_model
from core.models import School
from accounts.models import Roles


class ForcedPasswordChangeTests(TestCase):
    """First-login password change (item 49): middleware funnel + change flow."""

    def setUp(self):
        self.school = School.objects.create(
            name="Grace House School",
            short_code="grace-house",
        )
        User = get_user_model()
        self.user = User.objects.create_user(
            username="jane",
            email="jane@grace.edu",
            password="temp-pass-123",
            school=self.school,
            role=Roles.STUDENT,
            must_change_password=True,
        )

    def _login(self):
        self.client.login(username="jane", password="temp-pass-123")

    def test_middleware_funnels_flagged_user(self):
        self._login()
        response = self.client.get("/student/")
        self.assertRedirects(response, "/accounts/forced-password-change/")

    def test_middleware_bypasses_change_page_and_logout(self):
        self._login()
        response = self.client.get("/accounts/forced-password-change/")
        self.assertEqual(response.status_code, 200)
        response = self.client.post("/accounts/logout/")
        self.assertEqual(response.status_code, 302)

    def test_cleared_flag_roams_free(self):
        self.user.must_change_password = False
        self.user.save(update_fields=["must_change_password"])
        self._login()
        response = self.client.get("/student/")
        self.assertNotEqual(response.status_code, 302)
        self.assertNotEqual(response.url if hasattr(response, "url") else None,
                            "/accounts/forced-password-change/")

    def test_forced_page_redirects_when_not_flagged(self):
        self.user.must_change_password = False
        self.user.save(update_fields=["must_change_password"])
        self._login()
        response = self.client.get("/accounts/forced-password-change/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/accounts/redirect/")

    def test_wrong_current_password_rejected(self):
        self._login()
        response = self.client.post("/accounts/forced-password-change/", {
            "current_password": "nope",
            "new_password": "brand-new-pass",
            "confirm_password": "brand-new-pass",
        })
        self.assertRedirects(response, "/accounts/forced-password-change/")
        self.user.refresh_from_db()
        self.assertTrue(self.user.must_change_password)
        self.assertTrue(self.user.check_password("temp-pass-123"))

    def test_short_new_password_rejected(self):
        self._login()
        response = self.client.post("/accounts/forced-password-change/", {
            "current_password": "temp-pass-123",
            "new_password": "short",
            "confirm_password": "short",
        })
        self.assertRedirects(response, "/accounts/forced-password-change/")
        self.user.refresh_from_db()
        self.assertTrue(self.user.must_change_password)

    def test_mismatched_confirm_rejected(self):
        self._login()
        response = self.client.post("/accounts/forced-password-change/", {
            "current_password": "temp-pass-123",
            "new_password": "brand-new-pass",
            "confirm_password": "different-pass",
        })
        self.assertRedirects(response, "/accounts/forced-password-change/")
        self.user.refresh_from_db()
        self.assertTrue(self.user.must_change_password)

    def test_same_as_current_rejected(self):
        self._login()
        response = self.client.post("/accounts/forced-password-change/", {
            "current_password": "temp-pass-123",
            "new_password": "temp-pass-123",
            "confirm_password": "temp-pass-123",
        })
        self.assertRedirects(response, "/accounts/forced-password-change/")
        self.user.refresh_from_db()
        self.assertTrue(self.user.must_change_password)

    def test_success_clears_flag_and_redirects_to_dashboard(self):
        self._login()
        response = self.client.post("/accounts/forced-password-change/", {
            "current_password": "temp-pass-123",
            "new_password": "brand-new-pass",
            "confirm_password": "brand-new-pass",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/accounts/redirect/")
        self.user.refresh_from_db()
        self.assertFalse(self.user.must_change_password)
        self.assertTrue(self.user.check_password("brand-new-pass"))
        self.assertFalse(self.user.check_password("temp-pass-123"))
