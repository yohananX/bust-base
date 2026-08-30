"""End-to-end payment pipeline tests.

Chains the full Paystack lifecycle: initiate -> webhook -> idempotency ->
verify fallback -> charge.failed rejection.
"""
import json
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.test.client import RequestFactory
from django.urls import reverse
from django.utils import timezone

from accounts.models import Roles
from core.models import School, AcademicSession, Term
from fees.models import (
    FeeCategory, FeeStructure, Invoice, Payment, FeeReceipt, WebhookLog,
)
from fees.paystack import (
    handle_webhook as webhook_view,
    confirm_payment_from_verify,
)
from notifications.models import NotificationLog
from students.models import (
    SchoolClass, Student, ClassEnrollment, StudentGuardianLink,
)
from academics.models import Subject, TeacherAssignment
from accounts.models import User


User = User


class PaymentEndToEndTest(TestCase):
    """One chained test method covering the full Paystack payment pipeline."""

    def setUp(self):
        # School, session, term
        self.school = School.objects.create(name='E2E School', short_code='e2e')
        self.session = AcademicSession.objects.create(
            school=self.school,
            name='2025/2026',
            start_date='2025-09-01',
            end_date='2026-08-31',
            is_current=True,
        )
        self.term = Term.objects.create(
            school=self.school,
            session=self.session,
            name='First Term',
            start_date='2025-09-01',
            end_date='2025-12-15',
            is_current=True,
        )

        # Class and subject
        self.school_class = SchoolClass.objects.create(
            school=self.school, name='JSS1A', level='JSS1',
        )
        self.subject = Subject.objects.create(
            school=self.school, name='Mathematics', code='MTH',
            school_class=self.school_class,
        )

        # Users
        self.admin_user = User.objects.create_user(
            username='e2e_admin', email='admin@e2e.com', password='testpass123',
            school=self.school, role=Roles.ADMIN,
        )
        self.teacher_user = User.objects.create_user(
            username='e2e_teacher', email='teacher@e2e.com', password='testpass123',
            school=self.school, role=Roles.TEACHER,
        )
        self.student_user = User.objects.create_user(
            username='e2e_student', email='student@e2e.com', password='testpass123',
            school=self.school, role=Roles.STUDENT,
        )
        self.parent_user = User.objects.create_user(
            username='e2e_parent', email='parent@e2e.com', password='testpass123',
            school=self.school, role=Roles.PARENT,
        )

        # Student profile + guardian link
        self.student = Student.objects.create(
            school=self.school, user=self.student_user,
            admission_number='E2E-001',
            date_of_birth='2010-01-01', gender=Student.MALE,
            admission_date='2025-09-01', status=Student.ACTIVE,
        )
        ClassEnrollment.objects.create(
            school=self.school, student=self.student,
            school_class=self.school_class, session=self.session,
            is_current=True,
        )
        StudentGuardianLink.objects.create(
            school=self.school, student=self.student, guardian=self.parent_user,
            relationship=StudentGuardianLink.FATHER, is_primary_contact=True,
        )

        # Teacher assignment
        TeacherAssignment.objects.create(
            school=self.school, teacher=self.teacher_user,
            subject=self.subject, school_class=self.school_class,
            session=self.session,
        )

        # Fee structure and invoice
        self.tuition_category = FeeCategory.objects.create(
            school=self.school, name='Tuition',
        )
        FeeStructure.objects.create(
            school=self.school, school_class=self.school_class,
            term=self.term, category=self.tuition_category,
            amount=Decimal('60000.00'),
        )
        self.invoice = Invoice.objects.create(
            school=self.school, student=self.student, term=self.term,
            total_amount=Decimal('60000.00'),
        )

    def _post_webhook(self, event='charge.success', reference='E2E_REF_001',
                      amount_kobo=6000000, **extra_data):
        """Simulate a Paystack webhook event via RequestFactory."""
        data = {
            'reference': reference,
            'amount': amount_kobo,
            'paid_at': '2026-01-15T10:30:00.000Z',
            'metadata': {'invoice_id': self.invoice.id, 'school_id': self.school.id},
        }
        data.update(extra_data)

        payload = json.dumps({'event': event, 'data': data})
        factory = RequestFactory()
        request = factory.post(
            '/fees/api/paystack-webhook/',
            data=payload,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE='test_signature',
        )
        with patch('fees.paystack.verify_webhook_signature', return_value=True):
            return webhook_view(request)

    def test_full_payment_pipeline(self):
        """Chain: initiate -> webhook confirm -> idempotency -> verify fallback -> charge.failed."""

        # ------------------------------------------------------------------
        # Step 1 -- Initiate Paystack payment
        # ------------------------------------------------------------------
        class FakePaystackResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    'status': True,
                    'data': {
                        'authorization_url': 'https://paystack.test/start',
                        'access_code': 'ACC_E2E',
                        'reference': 'E2E_INIT_001',
                    },
                }

        def _fake_post(url, json=None, headers=None, timeout=None):
            return FakePaystackResponse()

        with patch('fees.paystack.http_requests.post', side_effect=_fake_post):
            self.client.force_login(self.parent_user)
            response = self.client.post(
                reverse('fees:initiate-payment'),
                {
                    'invoice_id': self.invoice.id,
                    'amount': '60000.00',
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response, 'https://paystack.test/start', fetch_redirect_response=False,
        )

        # Verify a PENDING Payment row exists
        payment = Payment.objects.filter(status=Payment.Status.PENDING).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.amount, Decimal('60000.00'))
        self.assertEqual(payment.invoice, self.invoice)
        self.assertEqual(payment.method, Payment.Method.PAYSTACK)
        init_ref = payment.reference

        # ------------------------------------------------------------------
        # Step 2 -- Webhook fires: charge.success
        # ------------------------------------------------------------------
        webhook_ref = 'E2E_WEBHOOK_001'
        webhook_response = self._post_webhook(reference=webhook_ref, amount_kobo=6000000)

        self.assertEqual(webhook_response.status_code, 200)

        webhook_payment = Payment.objects.get(reference=webhook_ref)
        self.assertEqual(webhook_payment.status, Payment.Status.CONFIRMED)
        self.assertTrue(webhook_payment.webhook_processed)

        # WebhookLog row created
        self.assertEqual(WebhookLog.objects.count(), 1)
        log = WebhookLog.objects.first()
        self.assertEqual(log.event, 'charge.success')
        self.assertIsNotNone(log.ip_address)

        # FeeReceipt issued
        self.assertTrue(FeeReceipt.objects.filter(payment=webhook_payment).exists())

        # NotificationLog for student + guardian with reference payment-confirm:{id}
        confirm_logs = NotificationLog.objects.filter(
            reference=f'payment-confirm:{webhook_payment.id}'
        )
        self.assertEqual(confirm_logs.count(), 2)
        self.assertTrue(confirm_logs.filter(recipient=self.student_user).exists())
        self.assertTrue(confirm_logs.filter(recipient=self.parent_user).exists())
        for log in confirm_logs:
            self.assertEqual(log.channel, NotificationLog.Channel.IN_APP)
            self.assertEqual(log.status, NotificationLog.Status.QUEUED)

        # ------------------------------------------------------------------
        # Step 3 -- Verify idempotency: same webhook again
        # ------------------------------------------------------------------
        balance_before = self.invoice.balance
        receipt_count_before = FeeReceipt.objects.count()

        webhook_response2 = self._post_webhook(reference=webhook_ref, amount_kobo=6000000)
        self.assertEqual(webhook_response2.status_code, 200)

        webhook_payment.refresh_from_db()
        self.assertEqual(webhook_payment.status, Payment.Status.CONFIRMED)
        self.assertEqual(Payment.objects.count(), 2)  # initiate + webhook
        self.assertEqual(FeeReceipt.objects.count(), receipt_count_before)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.balance, balance_before)

        # No duplicate notifications
        confirm_logs_after = NotificationLog.objects.filter(
            reference=f'payment-confirm:{webhook_payment.id}'
        )
        self.assertEqual(confirm_logs_after.count(), 2)

        # ------------------------------------------------------------------
        # Step 4 -- Verify fallback path: confirm_payment_from_verify
        # ------------------------------------------------------------------
        verify_ref = 'E2E_VERIFY_001'
        verify_payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            student=self.student,
            amount=Decimal('60000.00'),
            method=Payment.Method.PAYSTACK,
            reference=verify_ref,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )

        verify_data = {
            'status': 'success',
            'amount': 6000000,
            'currency': 'NGN',
            'fees': 15000,
            'authorization': {'channel': 'card', 'last4': '4242', 'card_type': 'visa'},
            'customer': {'email': 'p@x.com', 'first_name': 'Ada', 'last_name': 'Lovelace'},
        }

        confirm_payment_from_verify(verify_payment, verify_data)

        verify_payment.refresh_from_db()
        self.assertEqual(verify_payment.status, Payment.Status.CONFIRMED)
        self.assertEqual(verify_payment.channel, 'card')
        self.assertEqual(verify_payment.card_last4, '4242')
        self.assertEqual(verify_payment.card_brand, 'visa')
        self.assertTrue(FeeReceipt.objects.filter(payment=verify_payment).exists())

        # Notification reference payment-confirm:{id}
        verify_confirm_logs = NotificationLog.objects.filter(
            reference=f'payment-confirm:{verify_payment.id}'
        )
        self.assertEqual(verify_confirm_logs.count(), 2)
        self.assertTrue(verify_confirm_logs.filter(recipient=self.student_user).exists())
        self.assertTrue(verify_confirm_logs.filter(recipient=self.parent_user).exists())

        # ------------------------------------------------------------------
        # Step 5 -- Verify rejection path: charge.failed webhook
        # ------------------------------------------------------------------
        fail_ref = 'E2E_FAIL_001'
        fail_payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            student=self.student,
            amount=Decimal('60000.00'),
            method=Payment.Method.PAYSTACK,
            reference=fail_ref,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )

        fail_response = self._post_webhook(event='charge.failed', reference=fail_ref)
        self.assertEqual(fail_response.status_code, 200)

        fail_payment.refresh_from_db()
        self.assertEqual(fail_payment.status, Payment.Status.FAILED)

        # Invoice balance unchanged (still has the confirmed payment from step 2)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('60000.00'))

        # No receipt for failed payment
        self.assertFalse(FeeReceipt.objects.filter(payment=fail_payment).exists())

        # Notification reference payment-fail:{id} for student + guardian + admin
        fail_logs = NotificationLog.objects.filter(
            reference=f'payment-fail:{fail_payment.id}'
        )
        self.assertEqual(fail_logs.count(), 3)
        self.assertTrue(fail_logs.filter(recipient=self.student_user).exists())
        self.assertTrue(fail_logs.filter(recipient=self.parent_user).exists())
        self.assertTrue(fail_logs.filter(recipient=self.admin_user).exists())
        for log in fail_logs:
            self.assertEqual(log.channel, NotificationLog.Channel.IN_APP)
            self.assertIn('Payment failed', log.subject)
