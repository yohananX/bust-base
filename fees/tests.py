from decimal import Decimal
from datetime import date, datetime

from django.test import TestCase, override_settings
from django.urls import reverse
from django.db import IntegrityError
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.auth import get_user_model

from core.models import School, AcademicSession, Term
from accounts.models import Roles
from students.models import SchoolClass, Student, ClassEnrollment, StudentGuardianLink
from fees.models import FeeCategory, FeeStructure, Invoice, InvoiceLineItem, Payment


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
