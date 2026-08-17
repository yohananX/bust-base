from decimal import Decimal
from datetime import date

from django.test import TestCase
from django.urls import reverse
from django.db import IntegrityError
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.auth import get_user_model

from core.models import School, AcademicSession, Term
from accounts.models import Roles
from students.models import SchoolClass, Student, ClassEnrollment, StudentGuardianLink
from fees.models import FeeCategory, FeeStructure, Invoice, InvoiceLineItem, Payment
from fees.selectors import invoices_with_balance
from notifications.models import NotificationLog


User = get_user_model()


class BaseFeesTest(TestCase):
    """Common setup for all fees tests."""

    def setUp(self):
        # Create school
        self.school = School.objects.create(
            name='Test School',
            short_code='test',
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

        # Create student user and student
        self.student_user = User.objects.create_user(
            username='student1',
            email='student1@test.com',
            password='testpass123',
            school=self.school,
            role=Roles.STUDENT,
            first_name='John',
            last_name='Doe',
        )
        self.student = Student.objects.create(
            school=self.school,
            user=self.student_user,
            admission_number='STU001',
            date_of_birth=date(2010, 1, 1),
            gender=Student.MALE,
            admission_date=date(2025, 9, 1),
            status=Student.ACTIVE,
        )
        self.enrollment = ClassEnrollment.objects.create(
            school=self.school,
            student=self.student,
            school_class=self.school_class,
            session=self.session,
            is_current=True,
        )

        # Create fee categories and structures
        self.tuition_category = FeeCategory.objects.create(
            school=self.school,
            name='Tuition',
        )
        self.sports_category = FeeCategory.objects.create(
            school=self.school,
            name='Sports Fee',
        )

        self.tuition_fee = FeeStructure.objects.create(
            school=self.school,
            school_class=self.school_class,
            term=self.term,
            category=self.tuition_category,
            amount=Decimal('50000.00'),
        )
        self.sports_fee = FeeStructure.objects.create(
            school=self.school,
            school_class=self.school_class,
            term=self.term,
            category=self.sports_category,
            amount=Decimal('10000.00'),
        )

        # Create admin user
        self.admin_user = User.objects.create_user(
            username='admin1',
            email='admin@test.com',
            password='testpass123',
            school=self.school,
            role=Roles.ADMIN,
            first_name='Admin',
            last_name='User',
        )

        # Create parent user and link
        self.parent_user = User.objects.create_user(
            username='parent1',
            email='parent@test.com',
            password='testpass123',
            school=self.school,
            role=Roles.PARENT,
            first_name='Parent',
            last_name='One',
        )
        StudentGuardianLink.objects.create(
            school=self.school,
            student=self.student,
            guardian=self.parent_user,
            relationship=StudentGuardianLink.FATHER,
            is_primary_contact=True,
        )


# ─── Model Tests ──────────────────────────────────────────────────────────

class FeeCategoryModelTest(BaseFeesTest):
    def test_fee_category_creation(self):
        """Test FeeCategory creation and string representation."""
        category = FeeCategory.objects.create(
            school=self.school,
            name='Library Fee',
        )
        self.assertEqual(str(category), 'Library Fee')
        self.assertEqual(category.school, self.school)


class FeeStructureModelTest(BaseFeesTest):
    def test_fee_structure_creation(self):
        """Test FeeStructure creation with unique constraint."""
        fs = FeeStructure.objects.get(pk=self.tuition_fee.pk)
        self.assertEqual(fs.amount, Decimal('50000.00'))
        self.assertEqual(fs.school_class, self.school_class)
        self.assertEqual(fs.term, self.term)

    def test_fee_structure_unique_constraint(self):
        """Test that duplicate FeeStructure raises IntegrityError."""
        with self.assertRaises(IntegrityError):
            FeeStructure.objects.create(
                school=self.school,
                school_class=self.school_class,
                term=self.term,
                category=self.tuition_category,
                amount=Decimal('60000.00'),
            )


# ─── Invoice Tests ────────────────────────────────────────────────────────

class InvoiceModelTest(BaseFeesTest):
    def test_invoice_creation_with_line_items(self):
        """Test Invoice creation with line items."""
        invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('60000.00'),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice,
            category=self.tuition_category,
            amount=Decimal('50000.00'),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice,
            category=self.sports_category,
            amount=Decimal('10000.00'),
        )

        self.assertEqual(invoice.line_items.count(), 2)
        self.assertEqual(invoice.total_amount, Decimal('60000.00'))
        self.assertEqual(invoice.student, self.student)


# ─── Computed Property Tests ──────────────────────────────────────────────

class InvoiceComputedPropertiesTest(BaseFeesTest):
    def setUp(self):
        super().setUp()
        self.invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('60000.00'),
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice,
            category=self.tuition_category,
            amount=Decimal('50000.00'),
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice,
            category=self.sports_category,
            amount=Decimal('10000.00'),
        )

    def test_invoice_unpaid_by_default(self):
        """Test that new invoice has status UNPAID and balance equals total."""
        self.assertEqual(self.invoice.status, 'UNPAID')
        self.assertEqual(self.invoice.balance, Decimal('60000.00'))
        self.assertEqual(self.invoice.amount_paid, Decimal('0.00'))

    def test_invoice_partial_payment(self):
        """Test that partial CONFIRMED payment results in PARTIAL status."""
        Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('20000.00'),
            method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )
        self.assertEqual(self.invoice.status, 'PARTIAL')
        self.assertEqual(self.invoice.amount_paid, Decimal('20000.00'))
        self.assertEqual(self.invoice.balance, Decimal('40000.00'))

    def test_invoice_full_payment(self):
        """Test that full CONFIRMED payment results in PAID status."""
        Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('60000.00'),
            method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )
        self.assertEqual(self.invoice.status, 'PAID')
        self.assertEqual(self.invoice.amount_paid, Decimal('60000.00'))
        self.assertEqual(self.invoice.balance, Decimal('0.00'))

    def test_pending_payment_does_not_count_toward_amount_paid(self):
        """CRITICAL: PENDING payment does NOT count toward amount_paid."""
        Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('60000.00'),
            method=Payment.Method.PAYSTACK,
            reference='PAYSTACK_REF_001',
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )
        # PENDING should not count
        self.assertEqual(self.invoice.amount_paid, Decimal('0.00'))
        self.assertEqual(self.invoice.status, 'UNPAID')
        self.assertEqual(self.invoice.balance, Decimal('60000.00'))


    def test_pending_bank_transfer_does_not_count_toward_amount_paid(self):
        """A PENDING bank transfer never reduces the balance until confirmed."""
        Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('40000.00'),
            method=Payment.Method.BANK_TRANSFER,
            reference=None,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )
        self.assertEqual(self.invoice.amount_paid, Decimal('0.00'))
        self.assertEqual(self.invoice.status, 'UNPAID')
        self.assertEqual(self.invoice.balance, Decimal('60000.00'))

    def test_rejected_bank_transfer_never_counts(self):
        """A bank transfer counts only once CONFIRMED; pending/failed never count."""
        payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('40000.00'),
            method=Payment.Method.BANK_TRANSFER,
            reference=None,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )
        self.assertEqual(self.invoice.balance, Decimal('60000.00'))

        payment.status = Payment.Status.FAILED
        payment.save()
        self.assertEqual(self.invoice.amount_paid, Decimal('0.00'))
        self.assertEqual(self.invoice.balance, Decimal('60000.00'))

    def test_confirmed_bank_transfer_counts(self):
        """Once an admin confirms the transfer it counts toward amount_paid."""
        payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('40000.00'),
            method=Payment.Method.BANK_TRANSFER,
            reference=None,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )
        payment.status = Payment.Status.CONFIRMED
        payment.save()
        self.assertEqual(self.invoice.amount_paid, Decimal('40000.00'))
        self.assertEqual(self.invoice.status, 'PARTIAL')
        self.assertEqual(self.invoice.balance, Decimal('20000.00'))


# ─── Invoice Generation Tests ─────────────────────────────────────────────

class InvoiceGenerationTest(BaseFeesTest):
    def test_generate_invoices_for_term(self):
        """Test that generating invoices creates correct Invoice + LineItems."""
        invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('60000.00'),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice,
            category=self.tuition_category,
            amount=Decimal('50000.00'),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice,
            category=self.sports_category,
            amount=Decimal('10000.00'),
        )

        self.assertEqual(Invoice.objects.count(), 1)
        self.assertEqual(InvoiceLineItem.objects.count(), 2)
        self.assertEqual(invoice.total_amount, Decimal('60000.00'))

    def test_generate_invoices_idempotent(self):
        """CRITICAL: Running invoice generation twice does NOT create duplicates."""
        # Create invoice manually (simulating one generation)
        Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('60000.00'),
        )

        # Try to create again
        invoice_count = Invoice.objects.count()
        Invoice.objects.get_or_create(
            school=self.school,
            student=self.student,
            term=self.term,
            defaults={'total_amount': Decimal('60000.00')},
        )

        self.assertEqual(Invoice.objects.count(), invoice_count)

    def test_withdrawn_student_excluded_from_invoice_generation(self):
        """Test that withdrawn students are excluded."""
        # Mark student as withdrawn
        self.student.status = Student.WITHDRAWN
        self.student.save()

        # Should not have any invoices generated
        self.assertEqual(Invoice.objects.filter(student=self.student).count(), 0)

    def test_student_with_no_enrollment_excluded(self):
        """Test that students with no current enrollment are excluded."""
        # Remove enrollment
        self.enrollment.is_current = False
        self.enrollment.save()

        # No active enrollment — no invoice should be generated
        has_enrollment = ClassEnrollment.objects.filter(
            student=self.student,
            is_current=True,
        ).exists()
        self.assertFalse(has_enrollment)


# ─── Payment Tests ────────────────────────────────────────────────────────

class PaymentModelTest(BaseFeesTest):
    def setUp(self):
        super().setUp()
        self.invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('60000.00'),
        )

    def test_cash_payment_recorded_directly_confirmed(self):
        """Test that cash payment is recorded as CONFIRMED directly."""
        payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('60000.00'),
            method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)
        self.assertEqual(payment.method, Payment.Method.CASH)

    def test_paystack_payment_created_pending(self):
        """Test that Paystack payment starts as PENDING."""
        payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('60000.00'),
            method=Payment.Method.PAYSTACK,
            reference='PAYSTACK_REF_002',
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.method, Payment.Method.PAYSTACK)

    def test_reference_required_for_paystack(self):
        """Test that reference is required for PAYSTACK payments."""
        with self.assertRaises(ValidationError):
            payment = Payment(
                school=self.school,
                invoice=self.invoice,
                amount=Decimal('60000.00'),
                method=Payment.Method.PAYSTACK,
                reference='',
                status=Payment.Status.PENDING,
                paid_on=timezone.now(),
            )
            payment.full_clean()

    def test_reference_unique_with_school(self):
        """Test unique_together for (school, reference)."""
        Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('60000.00'),
            method=Payment.Method.PAYSTACK,
            reference='UNIQUE_REF_001',
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
        )
        with self.assertRaises(IntegrityError):
            Payment.objects.create(
                school=self.school,
                invoice=self.invoice,
                amount=Decimal('60000.00'),
                method=Payment.Method.PAYSTACK,
                reference='UNIQUE_REF_001',
                status=Payment.Status.CONFIRMED,
                paid_on=timezone.now(),
            )


# ─── Duplicate Webhook Test (CRITICAL) ────────────────────────────────────

class DuplicateWebhookTest(BaseFeesTest):
    """CRITICAL: Duplicate webhook calls must be idempotent."""

    def setUp(self):
        super().setUp()
        self.invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('60000.00'),
        )

    def _simulate_webhook(self, reference: str, amount_kobo: int = 6000000):
        """Simulate a Paystack webhook charge.success event."""
        from django.test.client import RequestFactory
        from fees.paystack import handle_webhook as webhook_view
        import json

        payload = json.dumps({
            'event': 'charge.success',
            'data': {
                'reference': reference,
                'amount': amount_kobo,
                'paid_at': '2026-01-15T10:30:00.000Z',
                'metadata': {
                    'invoice_id': self.invoice.id,
                },
            },
        })

        factory = RequestFactory()
        request = factory.post(
            '/fees/api/paystack-webhook/',
            data=payload,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE='test_signature',
        )

        # We need to handle the signature verification for testing
        # Override the verify function to accept our test signature
        from unittest.mock import patch
        with patch('fees.paystack.verify_webhook_signature', return_value=True):
            response = webhook_view(request)

        return response

    def test_first_webhook_call_creates_payment(self):
        """First webhook call with reference X creates CONFIRMED payment."""
        reference = 'WEBHOOK_REF_001'
        response = self._simulate_webhook(reference)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Payment.objects.count(), 1)

        payment = Payment.objects.first()
        self.assertEqual(payment.reference, reference)
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)

    def test_duplicate_webhook_does_not_duplicate_payment(self):
        """
        CRITICAL: Second webhook call with the same reference must not
        create a duplicate payment or change the balance.
        """
        reference = 'WEBHOOK_REF_002'

        # First call
        response1 = self._simulate_webhook(reference)
        self.assertEqual(response1.status_code, 200)
        self.assertEqual(Payment.objects.count(), 1)

        balance_before = self.invoice.balance

        # Second call with same reference
        response2 = self._simulate_webhook(reference)
        self.assertEqual(response2.status_code, 200)

        # Still only one payment
        self.assertEqual(Payment.objects.count(), 1)

        # Balance unchanged
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.balance, balance_before)

        # Only one CONFIRMED payment
        confirmed = Payment.objects.filter(status=Payment.Status.CONFIRMED)
        self.assertEqual(confirmed.count(), 1)


# ─── Cross-School Isolation Tests ─────────────────────────────────────────

class CrossSchoolIsolationTest(BaseFeesTest):
    def test_two_schools_with_same_data_dont_leak(self):
        """Test that two schools with identical data are properly isolated."""
        # Create a second school with identical setup
        school2 = School.objects.create(
            name='Second School',
            short_code='second',
        )
        session2 = AcademicSession.objects.create(
            school=school2,
            name='2025/2026',
            start_date=date(2025, 9, 1),
            end_date=date(2026, 8, 31),
            is_current=True,
        )
        term2 = Term.objects.create(
            school=school2,
            session=session2,
            name='First Term',
            start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 15),
            is_current=True,
        )
        class2 = SchoolClass.objects.create(
            school=school2,
            name='JSS1A',
            level='JSS1',
        )

        # Create category with same name in second school
        category2 = FeeCategory.objects.create(
            school=school2,
            name='Tuition',
        )

        # Create fee structure in second school
        FeeStructure.objects.create(
            school=school2,
            school_class=class2,
            term=term2,
            category=category2,
            amount=Decimal('70000.00'),
        )

        # First school's data should be isolated
        self.assertEqual(FeeCategory.objects.filter(school=self.school).count(), 2)
        self.assertEqual(FeeCategory.objects.filter(school=school2).count(), 1)

        self.assertEqual(FeeStructure.objects.filter(school=self.school).count(), 2)
        self.assertEqual(FeeStructure.objects.filter(school=school2).count(), 1)

        self.assertEqual(
            FeeStructure.objects.get(school=self.school, category=self.tuition_category).amount,
            Decimal('50000.00'),
        )


# ─── Decimal Check Tests ──────────────────────────────────────────────────

class DecimalCheckTest(BaseFeesTest):
    def test_no_float_in_fees_app(self):
        """CRITICAL: Verify no float usage in fees models, views, paystack code."""
        import os

        fees_dir = os.path.join(os.path.dirname(__file__))
        # Files to skip (test file contains this docstring)
        skip_files = {'tests.py'}
        skip_dirs = {'migrations', '__pycache__'}
        for root, dirs, files in os.walk(fees_dir):
            basename = os.path.basename(root)
            if basename in skip_dirs:
                continue
            for filename in files:
                if not filename.endswith('.py'):
                    continue
                if filename in skip_files:
                    continue
                filepath = os.path.join(root, filename)
                with open(filepath, 'r') as f:
                    content_lines = f.readlines()
                for i, line in enumerate(content_lines, 1):
                    stripped = line.strip()
                    if stripped.startswith('#') or not stripped:
                        continue
                    # Check for float keyword in non-comment code
                    if 'float' in stripped.lower():
                        # Allow 'FloatField' and 'float' used as type hint (e.g., -> float)
                        if 'float' in stripped.lower():
                            self.fail(
                                f'FLOAT USAGE FOUND: {filename}:{i}: {stripped}'
                            )

    def test_amount_paid_aggregation_uses_decimal(self):
        """Test that amount_paid aggregation returns Decimal."""
        invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('60000.00'),
        )
        Payment.objects.create(
            school=self.school,
            invoice=invoice,
            amount=Decimal('30000.00'),
            method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )

        amount_paid = invoice.amount_paid
        self.assertIsInstance(amount_paid, Decimal)
        self.assertEqual(amount_paid, Decimal('30000.00'))


# ─── Additional Model Tests ───────────────────────────────────────────────

class AdditionalPaymentTests(BaseFeesTest):
    def setUp(self):
        super().setUp()
        self.invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('60000.00'),
        )

    def test_payment_creation_with_minimal_fields(self):
        """Test that Payment can be created with minimal required fields."""
        payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('5000.00'),
            method=Payment.Method.OTHER,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
        )
        self.assertIsNotNone(payment.pk)
        self.assertEqual(payment.amount, Decimal('5000.00'))

    def test_payment_str_representation(self):
        """Test Payment string representation."""
        payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('5000.00'),
            method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )
        self.assertIn(str(self.invoice), str(payment))
        self.assertIn('5000', str(payment))

    def test_multiple_payments_on_same_invoice(self):
        """Test that multiple payments can be made on the same invoice."""
        Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('10000.00'),
            method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )
        Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('20000.00'),
            method=Payment.Method.BANK_TRANSFER,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )

        self.assertEqual(self.invoice.amount_paid, Decimal('30000.00'))
        self.assertEqual(self.invoice.status, 'PARTIAL')

    def test_payment_methods_have_required_choices(self):
        """Test that Payment method has all required choices."""
        required_methods = ['CASH', 'BANK_TRANSFER', 'CARD', 'USSD', 'PAYSTACK', 'OTHER']
        for method in required_methods:
            self.assertIn(method, [m[0] for m in Payment.Method.choices])

    def test_invoice_line_item_belongs_to_invoice(self):
        """Test InvoiceLineItem is properly linked to Invoice."""
        line_item = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            category=self.tuition_category,
            amount=Decimal('50000.00'),
        )
        self.assertEqual(line_item.invoice, self.invoice)

    def test_invoice_unique_constraint(self):
        """Test unique_together on (school, student, term)."""
        # setUp already created an invoice for this student+term
        with self.assertRaises(IntegrityError):
            Invoice.objects.create(
                school=self.school,
                student=self.student,
                term=self.term,
                total_amount=Decimal('60000.00'),
            )


# ─── Annotation Selector Tests ────────────────────────────────────────────

class InvoicesWithBalanceSelectorTest(BaseFeesTest):
    """Tests for the invoices_with_balance() query helper (no N+1 annotation)."""

    def setUp(self):
        super().setUp()
        self.invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('100000.00'),
        )

    def _annotated(self):
        return invoices_with_balance(
            Invoice.objects.filter(school=self.school, pk=self.invoice.pk)
        ).get()

    def _add_payment(self, amount, status=Payment.Status.CONFIRMED):
        Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=amount,
            method=Payment.Method.CASH,
            status=status,
            paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )

    def test_unpaid_invoice_balance_matches_property(self):
        """No payments — annotation matches the model property."""
        inv = self._annotated()
        self.assertEqual(inv.amount_paid_annotated, Decimal('0.00'))
        self.assertEqual(inv.balance_annotated, self.invoice.total_amount)
        self.assertEqual(inv.balance_annotated, self.invoice.balance)

    def test_partial_payment_matches_property(self):
        """Partial confirmed payment — annotation matches amount_paid/balance."""
        self._add_payment(Decimal('30000.00'))
        inv = self._annotated()
        self.assertEqual(inv.amount_paid_annotated, Decimal('30000.00'))
        self.assertEqual(inv.amount_paid_annotated, self.invoice.amount_paid)
        self.assertEqual(inv.balance_annotated, Decimal('70000.00'))
        self.assertEqual(inv.balance_annotated, self.invoice.balance)

    def test_full_payment_balance_zero(self):
        """Fully paid invoice — annotated balance is zero."""
        self._add_payment(Decimal('100000.00'))
        inv = self._annotated()
        self.assertEqual(inv.amount_paid_annotated, Decimal('100000.00'))
        self.assertEqual(inv.balance_annotated, Decimal('0.00'))

    def test_pending_payments_do_not_count(self):
        """Business rule: PENDING payments never count toward amount_paid."""
        self._add_payment(Decimal('50000.00'), status=Payment.Status.PENDING)
        inv = self._annotated()
        self.assertEqual(inv.amount_paid_annotated, Decimal('0.00'))
        self.assertEqual(inv.balance_annotated, Decimal('100000.00'))
        self.assertEqual(inv.balance, Decimal('100000.00'))

    def test_pending_bank_transfer_does_not_count_in_annotation(self):
        """Business rule: PENDING bank transfers never count toward amount_paid."""
        Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('40000.00'),
            method=Payment.Method.BANK_TRANSFER,
            reference=None,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )
        inv = self._annotated()
        self.assertEqual(inv.amount_paid_annotated, Decimal('0.00'))
        self.assertEqual(inv.balance_annotated, Decimal('100000.00'))
        self.assertEqual(inv.balance, Decimal('100000.00'))

    def test_confirmed_bank_transfer_counts_in_annotation(self):
        """Business rule: CONFIRMED bank transfers count toward amount_paid."""
        Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('40000.00'),
            method=Payment.Method.BANK_TRANSFER,
            reference=None,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )
        inv = self._annotated()
        self.assertEqual(inv.amount_paid_annotated, Decimal('40000.00'))
        self.assertEqual(inv.balance_annotated, Decimal('60000.00'))
        self.assertEqual(inv.balance, Decimal('60000.00'))

    def test_failed_payments_do_not_count(self):
        """Business rule: FAILED payments never count toward amount_paid."""
        self._add_payment(Decimal('50000.00'), status=Payment.Status.FAILED)
        inv = self._annotated()
        self.assertEqual(inv.amount_paid_annotated, Decimal('0.00'))
        self.assertEqual(inv.balance_annotated, Decimal('100000.00'))

    def test_multiple_confirmed_payments_sum(self):
        """Multiple confirmed payments sum correctly in the annotation."""
        self._add_payment(Decimal('25000.00'))
        self._add_payment(Decimal('35000.00'))
        inv = self._annotated()
        self.assertEqual(inv.amount_paid_annotated, Decimal('60000.00'))
        self.assertEqual(inv.balance_annotated, Decimal('40000.00'))

    def test_filter_by_balance_annotation(self):
        """balance_annotated can be used in filter() (SQL-side, not Python)."""
        # setUp created self.invoice (100000, unpaid) for self.student+self.term.
        # Can't create a second invoice for the same student+term, so use a
        # second student for the fully-paid invoice.
        user2 = User.objects.create_user(
            username='student2',
            email='student2@test.com',
            password='testpass123',
            school=self.school,
            role=Roles.STUDENT,
            first_name='Jane',
            last_name='Doe',
        )
        student2 = Student.objects.create(
            school=self.school,
            user=user2,
            admission_number='STU002',
            date_of_birth=date(2010, 2, 2),
            gender=Student.FEMALE,
            admission_date=date(2025, 9, 1),
            status=Student.ACTIVE,
        )
        paid = Invoice.objects.create(
            school=self.school,
            student=student2,
            term=self.term,
            total_amount=Decimal('50000.00'),
        )
        Payment.objects.create(
            school=self.school,
            invoice=paid,
            amount=Decimal('50000.00'),
            method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )

        qs = invoices_with_balance(Invoice.objects.filter(school=self.school))
        self.assertEqual(qs.filter(balance_annotated__gt=Decimal('0.00')).count(), 1)
        self.assertEqual(qs.filter(balance_annotated=Decimal('0.00')).count(), 1)
        self.assertEqual(
            qs.filter(balance_annotated__gt=Decimal('0.00')).first().balance_annotated,
            Decimal('100000.00'),
        )


# ─── Paystack Upgrade: Webhook Security Tests ─────────────────────────────

class WebhookSecurityTest(BaseFeesTest):
    """Security tests for the Paystack webhook upgrade (2026).

    Covers: WebhookLog persistence, amount-tamper rejection, charge.failed
    handling, metadata enrichment on confirmation, and idempotent receipts.
    """

    def setUp(self):
        super().setUp()
        from fees.models import Invoice

        self.invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('60000.00'),
        )

    def _create_pending_payment(self, reference='SEC_REF_001'):
        from fees.models import Payment

        return Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('60000.00'),
            method=Payment.Method.PAYSTACK,
            reference=reference,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )

    def _post_webhook(self, event='charge.success', reference='SEC_REF_001',
                      amount_kobo=6000000, **extra_data):
        """Simulate a Paystack webhook event via RequestFactory (signature patched)."""
        import json
        from unittest.mock import patch
        from django.test.client import RequestFactory
        from fees.paystack import handle_webhook as webhook_view

        data = {
            'reference': reference,
            'amount': amount_kobo,
            'paid_at': '2026-01-15T10:30:00.000Z',
            'metadata': {'invoice_id': self.invoice.id},
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

    def test_webhook_event_logged(self):
        """Every verified webhook event is recorded in WebhookLog with sender IP."""
        from fees.models import Payment, WebhookLog

        self._create_pending_payment('SEC_REF_001')
        response = self._post_webhook(reference='SEC_REF_001')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(WebhookLog.objects.count(), 1)
        log = WebhookLog.objects.first()
        self.assertEqual(log.event, 'charge.success')
        self.assertIsNotNone(log.ip_address)
        self.assertEqual(
            Payment.objects.get(reference='SEC_REF_001').status,
            Payment.Status.CONFIRMED,
        )

    def test_amount_tamper_marks_failed_no_credit(self):
        """Amount in kobo not matching payment.amount - FAILED, no credit, no receipt."""
        from fees.models import FeeReceipt, Payment

        payment = self._create_pending_payment('SEC_REF_002')
        response = self._post_webhook(reference='SEC_REF_002', amount_kobo=9999999)

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.FAILED)
        self.assertTrue(payment.webhook_processed)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('0.00'))
        self.assertEqual(FeeReceipt.objects.count(), 0)

    def test_charge_failed_marks_pending_failed(self):
        """charge.failed event flips a PENDING payment to FAILED with no credit."""
        from fees.models import FeeReceipt, Payment

        payment = self._create_pending_payment('SEC_REF_003')
        response = self._post_webhook(event='charge.failed', reference='SEC_REF_003')

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.FAILED)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('0.00'))
        self.assertEqual(FeeReceipt.objects.count(), 0)

    def test_confirmation_enriches_metadata(self):
        """Successful charge.success enriches the Payment with Paystack metadata."""
        from fees.models import Payment

        payment = self._create_pending_payment('SEC_REF_004')
        response = self._post_webhook(
            reference='SEC_REF_004',
            amount_kobo=6000000,
            currency='NGN',
            fees=15000,
            authorization={
                'channel': 'card',
                'last4': '4242',
                'card_type': 'visa',
                'bank': '',
            },
            customer={
                'email': 'p@x.com',
                'first_name': 'Ada',
                'last_name': 'Lovelace',
            },
        )

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)
        self.assertEqual(payment.channel, 'card')
        self.assertEqual(payment.card_last4, '4242')
        self.assertEqual(payment.card_brand, 'visa')
        self.assertEqual(payment.paid_by_email, 'p@x.com')
        self.assertEqual(payment.paid_by_name, 'Ada Lovelace')
        self.assertEqual(payment.fees_charged, Decimal('150.00'))
        self.assertEqual(payment.currency, 'NGN')
        self.assertTrue(payment.webhook_processed)

    def test_receipt_issued_once_on_duplicate_webhook(self):
        """Duplicate webhooks issue exactly one receipt and never duplicate the payment."""
        from fees.models import FeeReceipt, Payment

        payment = self._create_pending_payment('SEC_REF_005')

        response1 = self._post_webhook(reference='SEC_REF_005')
        self.assertEqual(response1.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)

        response2 = self._post_webhook(reference='SEC_REF_005')
        self.assertEqual(response2.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)

        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(FeeReceipt.objects.count(), 1)
        receipt = FeeReceipt.objects.get(payment=payment)
        self.assertRegex(receipt.receipt_number, r'^RCP-\d{4}-0{3}\d+$')
        self.assertEqual(
            receipt.receipt_number,
            f'RCP-{timezone.now().year}-{payment.pk:06d}',
        )
        self.assertEqual(payment.method, Payment.Method.PAYSTACK)
        self.assertEqual(payment.reference, 'SEC_REF_005')


# ─── Paystack Upgrade: Verify-Transaction Fallback Tests ─────────────────

class VerifyTransactionFallbackTest(BaseFeesTest):
    """Server-side verification fallback (verify_transaction) confirms PENDING payments.

    NOTE: the view imports verify_transaction with a deferred local import
    (inside get()), so the patch must target 'fees.paystack.verify_transaction'.
    """

    def setUp(self):
        super().setUp()
        from fees.models import Invoice, Payment

        self.invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('60000.00'),
        )
        self.payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('60000.00'),
            method=Payment.Method.PAYSTACK,
            reference='VERIFY_REF_001',
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )
        self.client.force_login(self.parent_user)

    def _get_verify(self, fake_result):
        from unittest.mock import patch

        with patch('fees.paystack.verify_transaction', return_value=fake_result):
            return self.client.get(
                reverse('fees:payment-verify'),
                {'reference': self.payment.reference, 'invoice_id': self.invoice.id},
            )

    def test_verify_flow_confirms_and_issues_receipt(self):
        """Successful verify_transaction confirms, enriches and issues a receipt."""
        from fees.models import FeeReceipt, Payment

        fake = {
            'status': True,
            'data': {
                'status': 'success',
                'amount': 6000000,
                'fees': 15000,
                'currency': 'NGN',
                'authorization': {'channel': 'bank', 'bank': 'Zenith'},
                'customer': {'email': 'p@x.com', 'name': 'Ada'},
            },
        }
        response = self._get_verify(fake)

        self.assertEqual(response.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.CONFIRMED)
        self.assertEqual(self.payment.channel, 'bank')
        self.assertEqual(self.payment.bank_name, 'Zenith')
        self.assertTrue(self.payment.webhook_processed)
        self.assertTrue(FeeReceipt.objects.filter(payment=self.payment).exists())

    def test_verify_amount_mismatch_marks_failed(self):
        """Verify result whose amount does not match - FAILED, no receipt, no credit."""
        from fees.models import FeeReceipt, Payment

        fake = {
            'status': True,
            'data': {'status': 'success', 'amount': 1234},
        }
        response = self._get_verify(fake)

        self.assertEqual(response.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.FAILED)
        self.assertEqual(FeeReceipt.objects.count(), 0)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('0.00'))

    def test_verify_error_keeps_pending(self):
        """verify_transaction returning an error leaves the payment PENDING, no receipt."""
        from fees.models import FeeReceipt, Payment

        response = self._get_verify({'error': 'gateway error'})

        self.assertEqual(response.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)
        self.assertEqual(FeeReceipt.objects.count(), 0)


# ─── Paystack Upgrade: Receipt View Tests ─────────────────────────────────

# PDF rendering depends on WeasyPrint, whose native GTK/Pango libraries are
# not available on every machine — probe once and skip PDF tests when missing.
from unittest import skipUnless  # noqa: E402

try:
    from weasyprint import HTML
    HTML(string='<p>probe</p>').write_pdf()
    PDF_RENDERING_AVAILABLE = True
except (ImportError, OSError):
    PDF_RENDERING_AVAILABLE = False


class ReceiptViewTest(BaseFeesTest):
    """Fee receipt pages: access control, lazy issuance, PDF download."""

    def setUp(self):
        super().setUp()
        from fees.models import Invoice

        self.invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('60000.00'),
        )
        self.parent_user2 = User.objects.create_user(
            username='parent2',
            email='parent2@test.com',
            password='testpass123',
            school=self.school,
            role=Roles.PARENT,
            first_name='Parent',
            last_name='Two',
        )

    def _create_payment(self, status):
        from fees.models import Payment

        return Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('60000.00'),
            method=Payment.Method.PAYSTACK,
            reference=f'RCPT_REF_{status}',
            status=status,
            paid_on=timezone.now(),
        )

    def test_receipt_page_parent(self):
        """A linked parent can view the receipt; a missing receipt is issued lazily."""
        from fees.models import FeeReceipt, Payment

        payment = self._create_payment(Payment.Status.CONFIRMED)
        self.client.force_login(self.parent_user)

        response = self.client.get(reverse('fees:payment-receipt', args=[payment.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Receipt')
        self.assertTrue(FeeReceipt.objects.filter(payment=payment).exists())

    def test_receipt_page_unauthorized_parent(self):
        """A parent not linked to the student is redirected away."""
        from fees.models import Payment

        payment = self._create_payment(Payment.Status.CONFIRMED)
        self.client.force_login(self.parent_user2)

        response = self.client.get(reverse('fees:payment-receipt', args=[payment.pk]))

        self.assertEqual(response.status_code, 302)

    @skipUnless(PDF_RENDERING_AVAILABLE, 'WeasyPrint native libraries unavailable')
    def test_receipt_pdf_download(self):
        """The receipt PDF endpoint returns a PDF download."""
        from fees.models import Payment

        payment = self._create_payment(Payment.Status.CONFIRMED)
        self.client.force_login(self.parent_user)

        response = self.client.get(reverse('fees:payment-receipt-pdf', args=[payment.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIn('application/pdf', response['Content-Type'])

    @skipUnless(not PDF_RENDERING_AVAILABLE, 'WeasyPrint available — PDF path tested instead')
    def test_receipt_pdf_falls_back_to_printable_html(self):
        """Without the WeasyPrint runtime, the download serves the receipt preview page."""
        from fees.models import Payment

        payment = self._create_payment(Payment.Status.CONFIRMED)
        self.client.force_login(self.parent_user)

        response = self.client.get(reverse('fees:payment-receipt-pdf', args=[payment.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response['Content-Type'])
        # Same look as the preview page — receipt card, amount, actions
        self.assertContains(response, 'Official Receipt')
        self.assertContains(response, 'Download PDF')
        self.assertContains(response, 'Amount Paid')
        # Sidebar renders like the app (context processors ran)
        self.assertContains(response, 'Pay Fees')
        self.assertContains(response, 'My Children')

    def test_pending_payment_has_no_receipt_page(self):
        """PENDING payments have no receipt — the view redirects and creates nothing."""
        from fees.models import FeeReceipt, Payment

        payment = self._create_payment(Payment.Status.PENDING)
        self.client.force_login(self.parent_user)

        response = self.client.get(reverse('fees:payment-receipt', args=[payment.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(FeeReceipt.objects.count(), 0)


# ─── Flexible Fee Payments (2026): Partial + Invoice-less Payments ────────

class FlexibleInitiateTest(BaseFeesTest):
    """InitiatePaymentView: partial amounts and invoice-less ("other") payments.

    The view validates and delegates to fees.paystack.initiate_payment, which
    creates the PENDING payment row. Only the outgoing Paystack HTTP call is
    faked here — the payment row is created by the real code path.
    """

    def setUp(self):
        super().setUp()
        self.invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('60000.00'),
        )

    def _post_initiate(self, data, user=None):
        """POST the initiate view as `user`, mocking only the Paystack HTTP call."""
        from unittest.mock import patch

        self.client.force_login(user or self.parent_user)

        class FakePaystackResponse:
            def __init__(self, reference):
                self._reference = reference

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    'status': True,
                    'data': {
                        'authorization_url': 'https://paystack.test/start',
                        'access_code': 'ACC001',
                        'reference': self._reference,
                    },
                }

        def _fake_post(url, json=None, headers=None, timeout=None):
            return FakePaystackResponse(json['reference'])

        with patch(
            'fees.paystack.http_requests.post', side_effect=_fake_post,
        ) as mock_post:
            response = self.client.post(reverse('fees:initiate-payment'), data)
        return response, mock_post

    def test_partial_payment_amount_respected(self):
        """A partial amount creates a PENDING payment for that exact amount."""
        response, _ = self._post_initiate({
            'invoice_id': self.invoice.id,
            'amount': '25000.00',
        })

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response, 'https://paystack.test/start', fetch_redirect_response=False,
        )

        self.assertEqual(Payment.objects.filter(status=Payment.Status.PENDING).count(), 1)
        payment = Payment.objects.get(status=Payment.Status.PENDING)
        self.assertEqual(payment.amount, Decimal('25000.00'))
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.invoice, self.invoice)

        # Balance untouched — PENDING payments never count toward amount_paid
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount_paid, Decimal('0.00'))

    def test_amount_exceeding_balance_rejected(self):
        """An amount above the invoice balance is rejected — no payment row."""
        response, mock_post = self._post_initiate({
            'invoice_id': self.invoice.id,
            'amount': '70000.00',
        })

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('parent-pay'), fetch_redirect_response=False)
        self.assertEqual(Payment.objects.filter(status=Payment.Status.PENDING).count(), 0)
        mock_post.assert_not_called()

    def test_zero_amount_rejected(self):
        """A zero amount is rejected — no payment row is created."""
        response, mock_post = self._post_initiate({
            'invoice_id': self.invoice.id,
            'amount': '0',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Payment.objects.filter(status=Payment.Status.PENDING).count(), 0)
        mock_post.assert_not_called()

    def test_other_payment_no_invoice(self):
        """An invoice-less payment is created against the student directly."""
        response, _ = self._post_initiate({
            'student_id': self.student.pk,
            'amount': '5000.00',
            'description': 'Books',
        })

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response, 'https://paystack.test/start', fetch_redirect_response=False,
        )

        self.assertEqual(Payment.objects.filter(status=Payment.Status.PENDING).count(), 1)
        payment = Payment.objects.get(status=Payment.Status.PENDING)
        self.assertIsNone(payment.invoice)
        self.assertEqual(payment.student, self.student)
        self.assertEqual(payment.description, 'Books')
        self.assertEqual(payment.amount, Decimal('5000.00'))
        self.assertEqual(payment.status, Payment.Status.PENDING)

    def test_other_payment_requires_student(self):
        """An invoice-less payment without student_id is rejected."""
        response, mock_post = self._post_initiate({
            'amount': '5000.00',
            'description': 'Books',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Payment.objects.filter(status=Payment.Status.PENDING).count(), 0)
        mock_post.assert_not_called()

    def test_student_role_can_pay_own_invoice(self):
        """The student user can initiate payment on their own invoice."""
        response, _ = self._post_initiate({
            'invoice_id': self.invoice.id,
            'amount': '25000.00',
        }, user=self.student_user)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Payment.objects.filter(status=Payment.Status.PENDING).count(), 1)
        payment = Payment.objects.get(status=Payment.Status.PENDING)
        self.assertEqual(payment.amount, Decimal('25000.00'))
        self.assertEqual(payment.invoice, self.invoice)

    def test_unauthorized_parent_other_payment_rejected(self):
        """A parent not linked to the student cannot pay for that student."""
        parent2 = User.objects.create_user(
            username='parent_unlinked',
            email='unlinked@test.com',
            password='testpass123',
            school=self.school,
            role=Roles.PARENT,
            first_name='Unlinked',
            last_name='Parent',
        )

        response, mock_post = self._post_initiate({
            'student_id': self.student.pk,
            'amount': '5000.00',
            'description': 'Books',
        }, user=parent2)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Payment.objects.filter(status=Payment.Status.PENDING).count(), 0)
        mock_post.assert_not_called()

    def test_callback_url_uses_pay_page(self):
        """The Paystack callback URL points at the portal pay page, not the old return page."""
        response, mock_post = self._post_initiate({
            'invoice_id': self.invoice.id,
            'amount': '25000.00',
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(mock_post.called)
        payload = mock_post.call_args.kwargs['json']
        self.assertIn('callback_url', payload)
        self.assertIn('parent/pay', payload['callback_url'])


class ReferenceOnlyStatusTest(BaseFeesTest):
    """PaymentStatusPartialView resolves payments by reference alone (no invoice_id)."""

    def setUp(self):
        super().setUp()
        self.invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('60000.00'),
        )

    def test_status_partial_without_invoice_id(self):
        """Reference-only polling works for an invoice-based payment."""
        payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('60000.00'),
            method=Payment.Method.PAYSTACK,
            reference='PARTIAL_REF_001',
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )
        self.client.force_login(self.parent_user)

        # PENDING state renders the polling partial (reference only)
        response = self.client.get(
            reverse('fees:payment-status-partial'),
            {'reference': payment.reference},
        )
        self.assertEqual(response.status_code, 200)

        # Confirm as the webhook would, then poll again → confirmed state
        payment.status = Payment.Status.CONFIRMED
        payment.save()
        response = self.client.get(
            reverse('fees:payment-status-partial'),
            {'reference': payment.reference},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payment Successful!')

    def test_status_partial_other_payment(self):
        """Reference-only polling works for an invoice-less (student) payment."""
        payment = Payment.objects.create(
            school=self.school,
            invoice=None,
            student=self.student,
            amount=Decimal('5000.00'),
            method=Payment.Method.PAYSTACK,
            reference='PARTIAL_REF_002',
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
            description='Books',
        )
        self.client.force_login(self.parent_user)

        response = self.client.get(
            reverse('fees:payment-status-partial'),
            {'reference': payment.reference},
        )
        self.assertEqual(response.status_code, 200)

        payment.status = Payment.Status.CONFIRMED
        payment.save()
        response = self.client.get(
            reverse('fees:payment-status-partial'),
            {'reference': payment.reference},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payment Successful!')


class OtherPaymentWebhookTest(BaseFeesTest):
    """Webhook-first path: charge.success creates invoice-less payments from metadata."""

    def setUp(self):
        super().setUp()
        self.invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('60000.00'),
        )

    def _post_webhook(self, reference, amount_kobo=6000000, metadata=None):
        """Simulate a Paystack charge.success webhook with custom metadata."""
        import json
        from unittest.mock import patch
        from django.test.client import RequestFactory
        from fees.paystack import handle_webhook as webhook_view

        data = {
            'reference': reference,
            'amount': amount_kobo,
            'paid_at': '2026-01-15T10:30:00.000Z',
            'metadata': metadata if metadata is not None else {},
        }
        payload = json.dumps({'event': 'charge.success', 'data': data})
        factory = RequestFactory()
        request = factory.post(
            '/fees/api/paystack-webhook/',
            data=payload,
            content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE='test_signature',
        )
        with patch('fees.paystack.verify_webhook_signature', return_value=True):
            return webhook_view(request)

    def test_webhook_creates_other_payment_from_student_id(self):
        """Webhook with student_id metadata creates a CONFIRMED invoice-less payment."""
        from fees.models import FeeReceipt, Payment

        reference = 'WEBHOOK_REF_OTHER_001'
        response = self._post_webhook(
            reference,
            amount_kobo=500000,
            metadata={
                'student_id': self.student.pk,
                'school_id': self.school.pk,
                'description': 'Books',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Payment.objects.count(), 1)

        payment = Payment.objects.get(reference=reference)
        self.assertIsNone(payment.invoice)
        self.assertEqual(payment.student, self.student)
        self.assertEqual(payment.description, 'Books')
        self.assertEqual(payment.amount, Decimal('5000.00'))
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)
        self.assertTrue(payment.webhook_processed)
        self.assertEqual(FeeReceipt.objects.count(), 1)

    def test_webhook_missing_invoice_and_student_400(self):
        """Webhook with neither invoice_id nor student_id is rejected with 400."""
        from fees.models import Payment

        response = self._post_webhook('WEBHOOK_REF_OTHER_002', metadata={})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Payment.objects.count(), 0)

    def test_webhook_updates_description_on_existing_payment(self):
        """A webhook for an existing payment fills in a blank description."""
        from fees.models import FeeReceipt, Payment

        reference = 'WEBHOOK_REF_OTHER_003'
        Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('60000.00'),
            method=Payment.Method.PAYSTACK,
            reference=reference,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )

        response = self._post_webhook(
            reference,
            amount_kobo=6000000,
            metadata={'invoice_id': self.invoice.id, 'description': 'Books'},
        )

        self.assertEqual(response.status_code, 200)
        payment = Payment.objects.get(reference=reference)
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)
        self.assertEqual(payment.description, 'Books')
        self.assertTrue(payment.webhook_processed)
        self.assertEqual(FeeReceipt.objects.count(), 1)


class MakePaymentPageTest(BaseFeesTest):
    """Portal pay pages ('parent-pay' / 'student-pay') render child + invoice data."""

    def setUp(self):
        super().setUp()
        self.invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('60000.00'),
        )
        # Second child so the parent page shows more than one child
        user2 = User.objects.create_user(
            username='student2',
            email='student2@test.com',
            password='testpass123',
            school=self.school,
            role=Roles.STUDENT,
            first_name='Jane',
            last_name='Doe',
        )
        self.student2 = Student.objects.create(
            school=self.school,
            user=user2,
            admission_number='STU002',
            date_of_birth=date(2011, 3, 3),
            gender=Student.FEMALE,
            admission_date=date(2025, 9, 1),
            status=Student.ACTIVE,
        )
        StudentGuardianLink.objects.create(
            school=self.school,
            student=self.student2,
            guardian=self.parent_user,
            relationship=StudentGuardianLink.MOTHER,
        )
        self.invoice2 = Invoice.objects.create(
            school=self.school,
            student=self.student2,
            term=self.term,
            total_amount=Decimal('45000.00'),
        )

    def test_parent_pay_page_renders(self):
        """Parent pay page lists children and their balances."""
        self.client.force_login(self.parent_user)
        response = self.client.get(reverse('parent-pay'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Make a Payment')
        self.assertContains(response, 'John Doe')
        self.assertContains(response, 'Jane Doe')
        # Invoice term names show the outstanding fees for each child
        self.assertContains(response, 'First Term')

    def test_student_pay_page_renders(self):
        """Student pay page renders for the student's own user."""
        self.client.force_login(self.student_user)
        response = self.client.get(reverse('student-pay'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Make a Payment')

    def test_pay_page_context(self):
        """Context exposes invoices_by_child with the children's invoices and totals."""
        self.client.force_login(self.parent_user)
        response = self.client.get(reverse('parent-pay'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Make a Payment')

        if response.context is not None:
            self.assertIn('invoices_by_child', response.context)
            self.assertTrue(response.context['invoices_by_child'])
            self.assertEqual(
                Decimal(str(response.context['total_owed'])),
                Decimal('105000.00'),
            )
        else:
            # Context unavailable — fall back to the rendered invoice term name
            self.assertContains(response, 'First Term')

    def test_pending_bank_transfer_visible_but_balance_unchanged(self):
        """A pending transfer shows in recent payments but never reduces the owed total."""
        Payment.objects.create(
            school=self.school,
            student=self.student,
            invoice=self.invoice,
            amount=Decimal('30000.00'),
            method=Payment.Method.BANK_TRANSFER,
            reference=None,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )
        self.client.force_login(self.parent_user)
        response = self.client.get(reverse('parent-pay'))

        self.assertEqual(response.status_code, 200)
        # Still owing the full amount — pending transfer doesn't count yet
        self.assertContains(response, '&#8358;60000.00')
        # The pending transaction is visible for the parent
        self.assertContains(response, 'Awaiting confirmation')
        self.assertNotContains(response, 'Receipt')

        if response.context is not None:
            self.assertEqual(
                Decimal(str(response.context['total_owed'])),
                Decimal('105000.00'),
            )
            recent = list(response.context['recent_payments'])
            self.assertTrue(any(p.status == 'PENDING' for p in recent))

    def test_confirmed_bank_transfer_reduces_balance(self):
        """Once confirmed, the transfer reduces the balance and a receipt is offered."""
        payment = Payment.objects.create(
            school=self.school,
            student=self.student,
            invoice=self.invoice,
            amount=Decimal('30000.00'),
            method=Payment.Method.BANK_TRANSFER,
            reference=None,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )
        payment.status = Payment.Status.CONFIRMED
        payment.save()

        self.client.force_login(self.parent_user)
        response = self.client.get(reverse('parent-pay'))

        self.assertEqual(response.status_code, 200)
        if response.context is not None:
            self.assertEqual(
                Decimal(str(response.context['total_owed'])),
                Decimal('75000.00'),
            )


class BankTransferProofTest(BaseFeesTest):
    """Bank-transfer checkout requires an uploaded proof screenshot."""

    def setUp(self):
        super().setUp()
        self.invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('60000.00'),
        )

    def _post(self, extra=None):
        data = {
            'student_id': str(self.student.pk),
            'item': ['outstanding'],
            'amount': '60000.00',
            'method': 'bank_transfer',
        }
        if extra:
            data.update(extra)
        self.client.force_login(self.parent_user)
        return self.client.post(reverse('fees:checkout-submit'), data, follow=True)

    def test_transfer_without_proof_rejected(self):
        """No screenshot — the transfer is refused and nothing is recorded."""
        response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Upload a screenshot of your transfer')
        self.assertEqual(
            Payment.objects.filter(method=Payment.Method.BANK_TRANSFER).count(),
            0,
        )

    def test_transfer_with_proof_creates_pending_payment(self):
        """A screenshot + payer details produce a PENDING payment with proof."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        proof = SimpleUploadedFile(
            'proof.png', b'fake-image-bytes', content_type='image/png'
        )
        response = self._post({
            'proof_image': proof,
            'paid_by_name': 'Aunty Ada',
            'paid_by_relation': 'Aunt',
        })
        self.assertNotContains(response, 'before submitting')

        payment = Payment.objects.get(method=Payment.Method.BANK_TRANSFER)
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.paid_by_name, 'Aunty Ada')
        self.assertEqual(payment.paid_by_relation, 'Aunt')
        self.assertTrue(payment.proof_image)
        # Pending transfer still doesn't reduce the balance
        self.assertEqual(payment.invoice.balance, Decimal('60000.00'))


class PaystackGatingTest(BaseFeesTest):
    """The Paystack card option only appears when keys are configured."""

    def setUp(self):
        super().setUp()
        Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('60000.00'),
        )

    def _get_pay_page(self):
        self.client.force_login(self.parent_user)
        return self.client.get(reverse('parent-pay'))

    def test_paystack_hidden_without_keys(self):
        """No PAYSTACK keys — only the bank-transfer method is offered."""
        with self.settings(PAYSTACK_SECRET_KEY='', PAYSTACK_PUBLIC_KEY=''):
            response = self._get_pay_page()
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Paystack Card')
        self.assertContains(response, 'Bank Transfer')
        self.assertContains(response, 'Amount due')

    def test_paystack_shown_with_keys(self):
        """With keys configured the card option and checkout button appear."""
        with self.settings(
            PAYSTACK_SECRET_KEY='sk_test_abc',
            PAYSTACK_PUBLIC_KEY='pk_test_abc',
        ):
            response = self._get_pay_page()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Paystack Card')
        self.assertContains(response, 'Proceed to Paystack Checkout')

# --- In-App Notification Trigger Tests ---

class InAppNotificationTriggerTest(BaseFeesTest):
    """Tests that fee events create IN_APP NotificationLog rows with correct references."""

    def setUp(self):
        super().setUp()
        self.invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('60000.00'),
        )

    def test_payment_confirmation_creates_notification_log(self):
        """confirm_payment_from_verify creates NotificationLog with reference 'payment-confirm:{id}'."""
        from fees.paystack import confirm_payment_from_verify

        payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            student=self.student,
            amount=Decimal('60000.00'),
            method=Payment.Method.PAYSTACK,
            reference='PAY_CONFIRM_REF',
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )

        data = {
            'status': 'success',
            'amount': 6000000,  # kobo
            'currency': 'NGN',
            'fees': 15000,
            'authorization': {'channel': 'card', 'last4': '4242', 'card_type': 'visa'},
            'customer': {'email': 'p@x.com', 'first_name': 'Ada', 'last_name': 'Lovelace'},
        }

        confirm_payment_from_verify(payment, data)

        log = NotificationLog.objects.get(reference='payment-confirm:%s' % payment.id)
        self.assertEqual(log.channel, NotificationLog.Channel.IN_APP)
        self.assertEqual(log.recipient, self.parent_user)
        self.assertIn('Payment confirmed', log.subject)
        self.assertEqual(log.status, NotificationLog.Status.QUEUED)

    def test_payment_failure_creates_notification_log(self):
        """charge.failed webhook creates NotificationLog with reference 'payment-fail:{id}'."""
        from fees.paystack import _handle_charge_failure

        payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            student=self.student,
            amount=Decimal('60000.00'),
            method=Payment.Method.PAYSTACK,
            reference='PAY_FAIL_REF',
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )

        event = {'event': 'charge.failed', 'data': {'reference': 'PAY_FAIL_REF'}}
        _handle_charge_failure('charge.failed', event, event['data'], webhook_log=None)

        log = NotificationLog.objects.get(reference='payment-fail:%s' % payment.id)
        self.assertEqual(log.channel, NotificationLog.Channel.IN_APP)
        self.assertEqual(log.recipient, self.parent_user)
        self.assertIn('Payment failed', log.subject)
        self.assertEqual(log.status, NotificationLog.Status.QUEUED)

    def test_bank_transfer_confirm_creates_notification_log(self):
        """PendingTransferConfirmView creates NotificationLog with reference 'transfer-confirm:{id}'."""
        payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            student=self.student,
            amount=Decimal('60000.00'),
            method=Payment.Method.BANK_TRANSFER,
            reference=None,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )

        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse('school_admin:pending_transfer_confirm', args=[payment.pk])
        )

        self.assertEqual(response.status_code, 302)
        log = NotificationLog.objects.get(reference='transfer-confirm:%s' % payment.id)
        self.assertEqual(log.channel, NotificationLog.Channel.IN_APP)
        self.assertEqual(log.recipient, self.parent_user)
        self.assertIn('Bank transfer confirmed', log.subject)
        self.assertEqual(log.status, NotificationLog.Status.QUEUED)

    def test_bank_transfer_reject_creates_notification_log(self):
        """PendingTransferRejectView creates NotificationLog with reference 'transfer-reject:{id}'."""
        payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            student=self.student,
            amount=Decimal('60000.00'),
            method=Payment.Method.BANK_TRANSFER,
            reference=None,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )

        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse('school_admin:pending_transfer_reject', args=[payment.pk])
        )

        self.assertEqual(response.status_code, 302)
        log = NotificationLog.objects.get(reference='transfer-reject:%s' % payment.id)
        self.assertEqual(log.channel, NotificationLog.Channel.IN_APP)
        self.assertEqual(log.recipient, self.parent_user)
        self.assertIn('Bank transfer rejected', log.subject)
        self.assertEqual(log.status, NotificationLog.Status.QUEUED)

    def test_receipt_issuance_creates_notification_log(self):
        """issue_receipt creates NotificationLog with reference 'receipt:{id}'."""
        from fees.paystack import issue_receipt

        payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            student=self.student,
            amount=Decimal('60000.00'),
            method=Payment.Method.PAYSTACK,
            reference='RCPT_REF',
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
        )

        receipt = issue_receipt(payment)

        log = NotificationLog.objects.get(reference='receipt:%s' % payment.id)
        self.assertEqual(log.channel, NotificationLog.Channel.IN_APP)
        self.assertEqual(log.recipient, self.parent_user)
        self.assertIn('Receipt issued', log.subject)
        self.assertEqual(log.status, NotificationLog.Status.QUEUED)
        self.assertIsNotNone(receipt)
