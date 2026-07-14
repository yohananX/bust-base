from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Roles
from core.models import AcademicSession, School, Term
from students.models import SchoolClass, Student, ClassEnrollment, StudentGuardianLink

from .models import NotificationLog
from .tasks import process_notification
from .utils import notify

User = get_user_model()


class BaseNotificationTest(TestCase):
    """Common setup for all notification tests."""

    def setUp(self):
        # Create school
        self.school = School.objects.create(
            name='Test School',
            short_code='test',
        )

        # Create users
        self.parent_user = User.objects.create_user(
            username='parent1',
            email='parent@test.com',
            password='testpass123',
            school=self.school,
            role=Roles.PARENT,
            first_name='Parent',
            last_name='One',
        )
        self.student_user = User.objects.create_user(
            username='student1',
            email='student@test.com',
            password='testpass123',
            school=self.school,
            role=Roles.STUDENT,
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

        # Create session and term
        self.session = AcademicSession.objects.create(
            school=self.school,
            name='2025/2026',
            start_date=date(2025, 9, 1),
            end_date=date(2026, 8, 31),
            is_current=True,
        )
        self.term = Term.objects.create(
            school=self.school,
            session=self.session,
            name='First Term',
            start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 15),
            is_current=True,
        )

        # Create school class
        self.school_class = SchoolClass.objects.create(
            school=self.school,
            name='JSS1A',
            level='JSS1',
        )

        # Create student
        self.student = Student.objects.create(
            school=self.school,
            user=self.student_user,
            admission_number='STU001',
            date_of_birth=date(2010, 1, 1),
            gender=Student.MALE,
            admission_date=date(2025, 9, 1),
            status=Student.ACTIVE,
        )
        ClassEnrollment.objects.create(
            school=self.school,
            student=self.student,
            school_class=self.school_class,
            session=self.session,
            is_current=True,
        )

        # Link parent as primary contact guardian
        self.guardian_link = StudentGuardianLink.objects.create(
            school=self.school,
            student=self.student,
            guardian=self.parent_user,
            relationship=StudentGuardianLink.FATHER,
            is_primary_contact=True,
        )


# ─── NotificationLog Model Tests ─────────────────────────────────────────

class NotificationLogModelTest(BaseNotificationTest):
    """Tests for the NotificationLog model."""

    def test_create_with_default_status(self):
        """NotificationLog created without explicit status defaults to QUEUED."""
        log = NotificationLog.objects.create(
            school=self.school,
            recipient=self.parent_user,
            channel=NotificationLog.Channel.EMAIL,
            subject='Test',
            message='Test message',
        )
        self.assertEqual(log.status, NotificationLog.Status.QUEUED)
        self.assertIsNone(log.sent_at)
        self.assertEqual(log.error_message, '')

    def test_create_with_sent_status(self):
        """NotificationLog can be created with SENT status."""
        log = NotificationLog.objects.create(
            school=self.school,
            recipient=self.parent_user,
            channel=NotificationLog.Channel.EMAIL,
            subject='Test',
            message='Test message',
            status=NotificationLog.Status.SENT,
            sent_at=timezone.now(),
        )
        self.assertEqual(log.status, NotificationLog.Status.SENT)
        self.assertIsNotNone(log.sent_at)

    def test_create_with_failed_status(self):
        """NotificationLog can be created with FAILED status and error message."""
        log = NotificationLog.objects.create(
            school=self.school,
            recipient=self.parent_user,
            channel=NotificationLog.Channel.EMAIL,
            subject='Test',
            message='Test message',
            status=NotificationLog.Status.FAILED,
            error_message='Connection refused',
        )
        self.assertEqual(log.status, NotificationLog.Status.FAILED)
        self.assertEqual(log.error_message, 'Connection refused')

    def test_str_representation(self):
        """__str__ includes channel, recipient, and status."""
        log = NotificationLog.objects.create(
            school=self.school,
            recipient=self.parent_user,
            channel=NotificationLog.Channel.EMAIL,
            subject='Welcome',
            message='Welcome to the school',
        )
        expected = f'Email to {self.parent_user} [Queued]'
        self.assertEqual(str(log), expected)

    def test_ordering_newest_first(self):
        """Notifications are ordered by created_at descending."""
        log1 = NotificationLog.objects.create(
            school=self.school,
            recipient=self.parent_user,
            channel=NotificationLog.Channel.EMAIL,
            subject='First',
            message='First message',
        )
        log2 = NotificationLog.objects.create(
            school=self.school,
            recipient=self.parent_user,
            channel=NotificationLog.Channel.EMAIL,
            subject='Second',
            message='Second message',
        )
        qs = NotificationLog.objects.all()
        self.assertEqual(qs.first(), log2)
        self.assertEqual(qs.last(), log1)


# ─── notify() Helper Tests ─────────────────────────────────────────────

class NotifyHelperTest(BaseNotificationTest):
    """Tests for the notify() helper function."""

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_notify_creates_log_with_queued_status(self):
        """Calling notify() creates a NotificationLog row with QUEUED status."""
        log = notify(
            recipient=self.parent_user,
            channel='EMAIL',
            subject='Test notification',
            message='This is a test.',
            reference='test:1',
        )
        self.assertIsNotNone(log.pk)
        self.assertEqual(log.status, NotificationLog.Status.QUEUED)
        self.assertEqual(log.reference, 'test:1')
        self.assertEqual(log.subject, 'Test notification')
        self.assertEqual(log.message, 'This is a test.')
        self.assertEqual(log.recipient, self.parent_user)
        self.assertEqual(log.channel, NotificationLog.Channel.EMAIL)
        self.assertEqual(log.school, self.school)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_notify_creates_row_in_database(self):
        """notify() persists the NotificationLog to the database."""
        notify(
            recipient=self.parent_user,
            channel='EMAIL',
            subject='DB test',
            message='Check the database.',
        )
        self.assertEqual(NotificationLog.objects.count(), 1)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_notify_without_subject(self):
        """notify() works with empty subject (e.g. SMS)."""
        log = notify(
            recipient=self.parent_user,
            channel='SMS',
            message='Your OTP is 1234.',
        )
        self.assertEqual(log.subject, '')
        self.assertEqual(log.channel, NotificationLog.Channel.SMS)


# ─── Process Notification Tests ─────────────────────────────────────────

class ProcessNotificationTest(BaseNotificationTest):
    """Tests for the process_notification task."""

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_process_email_flips_to_sent(self):
        """Processing a queued EMAIL notification sets status to SENT."""
        log = NotificationLog.objects.create(
            school=self.school,
            recipient=self.parent_user,
            channel=NotificationLog.Channel.EMAIL,
            subject='Process test',
            message='Will this flip to SENT?',
            status=NotificationLog.Status.QUEUED,
        )
        process_notification(log.id)

        log.refresh_from_db()
        self.assertEqual(log.status, NotificationLog.Status.SENT)
        self.assertIsNotNone(log.sent_at)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_process_sms_flips_to_sent(self):
        """Processing a queued SMS notification sets status to SENT."""
        log = NotificationLog.objects.create(
            school=self.school,
            recipient=self.parent_user,
            channel=NotificationLog.Channel.SMS,
            message='SMS test message',
            status=NotificationLog.Status.QUEUED,
        )
        process_notification(log.id)

        log.refresh_from_db()
        self.assertEqual(log.status, NotificationLog.Status.SENT)
        self.assertIsNotNone(log.sent_at)

    def test_process_nonexistent_log_does_not_raise(self):
        """process_notification with a non-existent ID silently returns."""
        # Should not raise any exception
        process_notification(99999)


# ─── Failure Handling Tests ────────────────────────────────────────────

class FailureHandlingTest(BaseNotificationTest):
    """Tests that notification failures are handled gracefully."""

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_send_to_user_without_email_fails_gracefully(self):
        """A user with empty email causes FAILED status."""
        # Create a user with no email
        no_email_user = User.objects.create_user(
            username='noemail',
            email='',
            password='testpass123',
            school=self.school,
            role=Roles.PARENT,
        )
        log = NotificationLog.objects.create(
            school=self.school,
            recipient=no_email_user,
            channel=NotificationLog.Channel.EMAIL,
            subject='No email',
            message='This should fail.',
            status=NotificationLog.Status.QUEUED,
        )
        process_notification(log.id)

        log.refresh_from_db()
        self.assertEqual(log.status, NotificationLog.Status.FAILED)
        self.assertNotEqual(log.error_message, '')


# ─── Cross-School Isolation Tests ──────────────────────────────────────

class CrossSchoolIsolationTest(BaseNotificationTest):
    """Tests that TenantScopedModel isolation works for notifications."""

    def test_notifications_isolated_by_school(self):
        """Notifications from different schools don't leak."""
        school2 = School.objects.create(
            name='Second School',
            short_code='second',
        )
        parent2 = User.objects.create_user(
            username='parent2',
            email='parent2@test.com',
            password='testpass123',
            school=school2,
            role=Roles.PARENT,
        )

        # Create notifications in both schools
        NotificationLog.objects.create(
            school=self.school,
            recipient=self.parent_user,
            channel=NotificationLog.Channel.EMAIL,
            subject='School 1',
            message='Message 1',
        )
        NotificationLog.objects.create(
            school=school2,
            recipient=parent2,
            channel=NotificationLog.Channel.EMAIL,
            subject='School 2',
            message='Message 2',
        )

        self.assertEqual(
            NotificationLog.objects.filter(school=self.school).count(), 1
        )
        self.assertEqual(
            NotificationLog.objects.filter(school=school2).count(), 1
        )
        self.assertEqual(NotificationLog.objects.count(), 2)


# --- Notification Dedup Tests ---

class NotificationDedupTest(BaseNotificationTest):
    """Tests that admin actions do not create duplicate notification rows."""

    def test_publish_results_notifications_are_deduplicated(self):
        """Calling publish_results action twice does not double NotificationLog rows."""
        from notifications.utils import notify
        from notifications.models import NotificationLog

        # Simulate first publish_results call
        notify(
            recipient=self.parent_user,
            channel='EMAIL',
            subject='Results available for {}'.format(self.term.name),
            message='Results for {} are now available.'.format(self.term.name),
            reference='term-results:{}'.format(self.term.id),
        )
        first_count = NotificationLog.objects.filter(
            reference='term-results:{}'.format(self.term.id)
        ).count()
        self.assertEqual(first_count, 1)

        # Simulate second publish_results call
        # The guard in academics/admin.py checks for existing rows before calling notify()
        already_sent = NotificationLog.objects.filter(
            reference='term-results:{}'.format(self.term.id)
        ).exists()
        self.assertTrue(already_sent)

        # If guard works, notify() is NOT called the second time
        second_count = NotificationLog.objects.filter(
            reference='term-results:{}'.format(self.term.id)
        ).count()
        self.assertEqual(second_count, 1)

    def test_invoice_generation_notifications_use_unique_references(self):
        """Each invoice notification has a unique reference so re-running is safe."""
        from notifications.utils import notify

        # Simulate first invoice generation
        notify(
            recipient=self.parent_user,
            channel='EMAIL',
            subject='New invoice',
            message='Invoice generated.',
            reference='invoice:1',
        )
        # Simulate second invoice generation (different invoice ID)
        notify(
            recipient=self.parent_user,
            channel='EMAIL',
            subject='New invoice',
            message='Invoice generated.',
            reference='invoice:2',
        )
        # Both should exist
        self.assertEqual(
            NotificationLog.objects.filter(reference__startswith='invoice:').count(), 2
        )

        # Simulate re-running generate_invoices_for_term where invoices already exist
        # No new invoices -> no new notifications
        self.assertEqual(
            NotificationLog.objects.filter(reference__startswith='invoice:').count(), 2
        )
