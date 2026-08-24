"""End-to-end bank transfer tests.

Covers the happy path (checkout -> admin confirm -> receipt -> invoice detail)
and the rejection path (checkout -> admin reject -> FAILED).
"""
from decimal import Decimal
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Roles
from core.models import School, AcademicSession, Term
from fees.models import (
    FeeCategory, FeeStructure, Invoice, Payment, FeeReceipt,
)
from students.models import SchoolClass, Student, ClassEnrollment, StudentGuardianLink
from notifications.models import NotificationLog
from accounts.models import User


User = User


class BankTransferEndToEndTest(TestCase):
    """Two chained test methods for bank transfer happy + reject paths."""

    def setUp(self):
        self.school = School.objects.create(name='E2E Bank School', short_code='e2ebank')
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

        self.school_class = SchoolClass.objects.create(
            school=self.school, name='JSS1A', level='JSS1',
        )

        self.admin_user = User.objects.create_user(
            username='e2ebank_admin', email='admin@e2ebank.com', password='testpass123',
            school=self.school, role=Roles.ADMIN,
        )
        self.student_user = User.objects.create_user(
            username='e2ebank_student', email='student@e2ebank.com', password='testpass123',
            school=self.school, role=Roles.STUDENT,
        )
        self.parent_user = User.objects.create_user(
            username='e2ebank_parent', email='parent@e2ebank.com', password='testpass123',
            school=self.school, role=Roles.PARENT,
        )

        self.student = Student.objects.create(
            school=self.school, user=self.student_user,
            admission_number='E2EBANK-001',
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

    def _post_checkout(self, **extra):
        """POST to checkout-submit with bank_transfer + proof image."""
        proof = SimpleUploadedFile(
            'proof.png', b'\x89PNG\r\n\x1a\nfake-image-bytes', content_type='image/png'
        )
        data = {
            'student_id': str(self.student.pk),
            'item': ['outstanding'],
            'amount': '60000.00',
            'method': 'bank_transfer',
            'proof_image': proof,
            'paid_by_name': 'Papa E2E',
            'paid_by_relation': 'Father',
        }
        data.update(extra)
        self.client.force_login(self.parent_user)
        return self.client.post(reverse('fees:checkout-submit'), data, follow=True)

    def test_bank_transfer_full_happy_path(self):
        """Checkout -> admin confirm -> parent views receipt -> invoice detail -> notifications."""

        # Step 1: Parent submits bank transfer with proof
        response = self._post_checkout()
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'before submitting')

        payment = Payment.objects.get(method=Payment.Method.BANK_TRANSFER)
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.paid_by_name, 'Papa E2E')
        self.assertEqual(payment.paid_by_relation, 'Father')
        self.assertTrue(payment.proof_image)
        # Pending transfer does not reduce balance
        self.assertEqual(self.invoice.balance, Decimal('60000.00'))

        # Step 2: Admin confirms the transfer
        self.client.force_login(self.admin_user)
        confirm_resp = self.client.post(
            reverse('school_admin:pending_transfer_confirm', args=[payment.pk])
        )
        self.assertEqual(confirm_resp.status_code, 302)

        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)
        self.assertIsNotNone(payment.confirmed_by)
        self.assertEqual(payment.confirmed_by, self.admin_user)
        self.assertIsNotNone(payment.confirmed_at)

        # FeeReceipt issued
        self.assertTrue(FeeReceipt.objects.filter(payment=payment).exists())

        # Balance reduced
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.balance, Decimal('0.00'))

        # Step 3: Parent views receipt
        self.client.force_login(self.parent_user)
        receipt_resp = self.client.get(
            reverse('fees:payment-receipt', args=[payment.pk])
        )
        self.assertEqual(receipt_resp.status_code, 200)
        self.assertContains(receipt_resp, 'Transfer Proof')
        self.assertContains(receipt_resp, payment.proof_image.url)

        # Step 4: Admin views invoice detail with reduced balance
        self.client.force_login(self.admin_user)
        invoice_resp = self.client.get(
            reverse('school_admin:invoice_detail', args=[self.invoice.pk])
        )
        self.assertEqual(invoice_resp.status_code, 200)
        self.assertContains(invoice_resp, '0.00')

        # Step 5: NotificationLog for student + guardian with transfer-confirm:{id}
        confirm_logs = NotificationLog.objects.filter(
            reference=f'transfer-confirm:{payment.id}'
        )
        self.assertEqual(confirm_logs.count(), 2)
        self.assertTrue(confirm_logs.filter(recipient=self.student_user).exists())
        self.assertTrue(confirm_logs.filter(recipient=self.parent_user).exists())
        for log in confirm_logs:
            self.assertEqual(log.channel, NotificationLog.Channel.IN_APP)
            self.assertIn('Bank transfer confirmed', log.subject)

    def test_bank_transfer_reject_path(self):
        """Checkout -> admin reject -> payment FAILED -> notifications."""

        # Step 1: Parent submits bank transfer with proof
        response = self._post_checkout()
        self.assertEqual(response.status_code, 200)

        payment = Payment.objects.get(method=Payment.Method.BANK_TRANSFER)
        self.assertEqual(payment.status, Payment.Status.PENDING)

        # Step 2: Admin rejects the transfer
        self.client.force_login(self.admin_user)
        reject_resp = self.client.post(
            reverse('school_admin:pending_transfer_reject', args=[payment.pk])
        )
        self.assertEqual(reject_resp.status_code, 302)

        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.FAILED)

        # Balance unchanged
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.balance, Decimal('60000.00'))

        # Step 3: NotificationLog transfer-reject:{id} for student + guardian
        reject_logs = NotificationLog.objects.filter(
            reference=f'transfer-reject:{payment.id}'
        )
        self.assertEqual(reject_logs.count(), 2)
        self.assertTrue(reject_logs.filter(recipient=self.student_user).exists())
        self.assertTrue(reject_logs.filter(recipient=self.parent_user).exists())
        for log in reject_logs:
            self.assertEqual(log.channel, NotificationLog.Channel.IN_APP)
            self.assertIn('Bank transfer rejected', log.subject)

        # Step 4: Admin notification transfer-pending:{student}:{ts} from submission
        pending_logs = NotificationLog.objects.filter(
            reference__startswith='transfer-pending:',
        )
        self.assertTrue(pending_logs.exists())
        admin_pending = pending_logs.filter(recipient=self.admin_user)
        self.assertTrue(admin_pending.exists())
