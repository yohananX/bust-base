"""Tests for the payment management module enhancements.

Covers:
- FeeCategoryGroup hierarchy and assignments
- InvoiceResetLog audit trail
- FeeValidationError logging
- InvoiceIntegrityValidator
- FeeStructureValidator
- InvoiceResetService (term, class, student, school)
- Generation billing_cycle enforcement and one-time guard
- Checkout grouped_extras
"""
from decimal import Decimal
from datetime import date

from django.test import TestCase
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.models import School, AcademicSession, Term
from accounts.models import Roles
from students.models import SchoolClass, Student, ClassEnrollment, StudentGuardianLink
from fees.models import (
    FeeCategory, FeeCategoryGroup, FeeCategoryGroupAssignment,
    FeeStructure, Invoice, InvoiceLineItem, Payment, PaymentLineItem,
    InvoiceResetLog, FeeValidationError,
)
from fees.validation import InvoiceIntegrityValidator, FeeStructureValidator
from fees.reset import InvoiceResetService
from fees.generation import generate_invoice_for_student, sync_class_invoices, effective_fee_structures
from fees.checkout import get_checkout_options


class BasePaymentManagementTest(TestCase):
    """Common setup for payment management tests."""

    def setUp(self):
        self.school = School.objects.create(
            name='Test School',
            short_code='test',
        )
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
        self.next_term = Term.objects.create(
            school=self.school,
            session=self.session,
            name='Second Term',
            start_date=date(2026, 1, 5),
            end_date=date(2026, 4, 10),
            is_current=False,
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school,
            name='JSS1A',
            level='JSS1',
        )
        self.student_user = self._create_user('student1', Roles.STUDENT)
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
        self.admin_user = self._create_user('admin1', Roles.ADMIN)
        self.superadmin_user = self._create_user('superadmin1', Roles.ADMIN, is_superuser=True)

    def _create_user(self, username, role, is_superuser=False):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        return User.objects.create_user(
            username=username,
            email=f'{username}@test.com',
            password='testpass123',
            school=self.school if not is_superuser else None,
            role=role,
            first_name=username.title(),
            last_name='User',
            is_superuser=is_superuser,
            is_staff=is_superuser,
        )


# ─── FeeCategoryGroup Tests ──────────────────────────────────────────────────


class FeeCategoryGroupTest(BasePaymentManagementTest):
    def test_group_creation(self):
        group = FeeCategoryGroup.objects.create(
            school=self.school,
            name='Academic',
            group_type=FeeCategoryGroup.GROUP_TYPES[0][0],
        )
        self.assertEqual(str(group), 'Academic')

    def test_nested_group_depth_limit(self):
        parent = FeeCategoryGroup.objects.create(
            school=self.school,
            name='Parent',
        )
        child = FeeCategoryGroup.objects.create(
            school=self.school,
            name='Child',
            parent=parent,
        )
        grandchild = FeeCategoryGroup(
            school=self.school,
            name='Grandchild',
            parent=child,
        )
        with self.assertRaises(ValidationError):
            grandchild.full_clean()

    def test_group_assignment_unique_together(self):
        group = FeeCategoryGroup.objects.create(school=self.school, name='Academic')
        category = FeeCategory.objects.create(school=self.school, name='Tuition')
        FeeCategoryGroupAssignment.objects.create(
            school=self.school, group=group, category=category
        )
        with self.assertRaises(Exception):
            FeeCategoryGroupAssignment.objects.create(
                school=self.school, group=group, category=category
            )


# ─── InvoiceResetLog Tests ───────────────────────────────────────────────────


class InvoiceResetLogTest(BasePaymentManagementTest):
    def test_reset_log_creation(self):
        term = Term.objects.create(
            school=self.school,
            session=self.session,
            name='Third Term',
            start_date=date(2026, 4, 20),
            end_date=date(2026, 7, 10),
            is_current=False,
        )
        log = InvoiceResetLog.objects.create(
            school=self.school,
            scope_type=InvoiceResetLog.ResetScope.TERM,
            scope_id=term.pk,
            scope_name=str(term),
            reset_by=self.admin_user,
            reason='Test reset',
            invoices_deleted=5,
            payments_deleted=3,
            line_items_deleted=12,
            receipts_deleted=2,
        )
        self.assertEqual(log.scope_type, 'TERM')
        self.assertEqual(log.invoices_deleted, 5)


# ─── FeeValidationError Tests ───────────────────────────────────────────────


class FeeValidationErrorTest(BasePaymentManagementTest):
    def test_validation_error_creation(self):
        err = FeeValidationError.objects.create(
            school=self.school,
            code=FeeValidationError.ErrorCode.NEGATIVE_AMOUNT,
            message='Amount is negative',
            related_object_type='FeeStructure',
            related_object_id=1,
        )
        self.assertEqual(err.code, 'NEGATIVE_AMOUNT')
        self.assertFalse(err.is_resolved)


# ─── Validation Service Tests ───────────────────────────────────────────────


class ValidationServiceTest(BasePaymentManagementTest):
    def setUp(self):
        super().setUp()
        self.tuition_category = FeeCategory.objects.create(
            school=self.school,
            name='Tuition',
            is_compulsory=True,
            billing_cycle=FeeCategory.BILLING_CYCLE_CHOICES[0][0],
            student_type=FeeCategory.STUDENT_TYPE_CHOICES[2][0],
        )
        self.sports_category = FeeCategory.objects.create(
            school=self.school,
            name='Sports',
            is_compulsory=False,
            billing_cycle=FeeCategory.BILLING_CYCLE_CHOICES[0][0],
            student_type=FeeCategory.STUDENT_TYPE_CHOICES[2][0],
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

    def test_validate_invoice_totals_mismatch(self):
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
            amount=Decimal('8000.00'),
        )
        errors = InvoiceIntegrityValidator.validate_invoice_totals(invoice)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['code'], FeeValidationError.ErrorCode.MISMATCHED_TOTAL)

    def test_validate_invoice_totals_match(self):
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
        errors = InvoiceIntegrityValidator.validate_invoice_totals(invoice)
        self.assertEqual(len(errors), 0)

    def test_validate_compulsory_coverage_missing(self):
        optional_category = FeeCategory.objects.create(
            school=self.school,
            name='Library',
            is_compulsory=False,
        )
        invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('50000.00'),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice,
            category=self.tuition_category,
            amount=Decimal('50000.00'),
        )
        errors = InvoiceIntegrityValidator.validate_compulsory_coverage(invoice)
        # sports is optional, so no missing compulsory
        self.assertEqual(len(errors), 0)

    def test_validate_structure_negative_amount(self):
        neg_category = FeeCategory.objects.create(
            school=self.school,
            name='Neg',
            is_compulsory=True,
        )
        fs = FeeStructure(
            school=self.school,
            school_class=self.school_class,
            term=self.term,
            category=neg_category,
            amount=Decimal('-100.00'),
        )
        errors = FeeStructureValidator.validate_structure(fs)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['code'], FeeValidationError.ErrorCode.NEGATIVE_AMOUNT)

    def test_validate_structure_duplicate(self):
        dup_category = FeeCategory.objects.create(
            school=self.school,
            name='Dup',
            is_compulsory=True,
        )
        FeeStructure.objects.create(
            school=self.school,
            school_class=self.school_class,
            term=self.term,
            category=dup_category,
            amount=Decimal('60000.00'),
        )
        fs = FeeStructure(
            school=self.school,
            school_class=self.school_class,
            term=self.term,
            category=dup_category,
            amount=Decimal('70000.00'),
        )
        errors = FeeStructureValidator.validate_structure(fs)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['code'], FeeValidationError.ErrorCode.DUPLICATE_STRUCTURE)


# ─── Reset Service Tests ────────────────────────────────────────────────────


class ResetServiceTest(BasePaymentManagementTest):
    def setUp(self):
        super().setUp()
        self.tuition_category = FeeCategory.objects.create(
            school=self.school,
            name='Tuition',
            is_compulsory=True,
        )
        self.fee_structure = FeeStructure.objects.create(
            school=self.school,
            school_class=self.school_class,
            term=self.term,
            category=self.tuition_category,
            amount=Decimal('50000.00'),
        )
        self.invoice = Invoice.objects.create(
            school=self.school,
            student=self.student,
            term=self.term,
            total_amount=Decimal('50000.00'),
        )
        InvoiceLineItem.objects.create(
            invoice=self.invoice,
            category=self.tuition_category,
            amount=Decimal('50000.00'),
        )
        self.payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=Decimal('20000.00'),
            method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )

    def test_reset_student(self):
        log = InvoiceResetService.reset_student(
            self.school, self.student, self.term,
            user=self.superadmin_user, reason='Test reset'
        )
        self.assertEqual(log.scope_type, InvoiceResetLog.ResetScope.STUDENT)
        self.assertEqual(log.invoices_deleted, 1)
        self.assertEqual(log.payments_deleted, 1)
        self.assertFalse(Invoice.objects.filter(pk=self.invoice.pk).exists())
        self.assertFalse(Payment.objects.filter(pk=self.payment.pk).exists())

    def test_reset_student_no_invoice(self):
        student2 = Student.objects.create(
            school=self.school,
            user=self._create_user('student2', Roles.STUDENT),
            admission_number='STU002',
            date_of_birth=date(2010, 1, 1),
            gender=Student.MALE,
            admission_date=date(2025, 9, 1),
            status=Student.ACTIVE,
        )
        ClassEnrollment.objects.create(
            school=self.school,
            student=student2,
            school_class=self.school_class,
            session=self.session,
            is_current=True,
        )
        log = InvoiceResetService.reset_student(
            self.school, student2, self.term,
            user=self.superadmin_user, reason='Test reset'
        )
        self.assertEqual(log.invoices_deleted, 0)

    def test_reset_term(self):
        log = InvoiceResetService.reset_term(
            self.school, self.term,
            user=self.superadmin_user, reason='Test reset'
        )
        self.assertEqual(log.scope_type, InvoiceResetLog.ResetScope.TERM)
        self.assertEqual(log.invoices_deleted, 1)
        self.assertFalse(Invoice.objects.filter(pk=self.invoice.pk).exists())

    def test_reset_school_requires_force(self):
        with self.assertRaises(ValueError):
            InvoiceResetService.reset_school(self.school, user=self.superadmin_user)

    def test_reset_school_with_force(self):
        log = InvoiceResetService.reset_school(
            self.school, user=self.superadmin_user, reason='Wipe all', force=True
        )
        self.assertEqual(log.scope_type, InvoiceResetLog.ResetScope.SCHOOL)
        self.assertEqual(log.invoices_deleted, 1)
        self.assertFalse(Invoice.objects.filter(pk=self.invoice.pk).exists())


# ─── Generation Billing Cycle Tests ─────────────────────────────────────────


class GenerationBillingCycleTest(BasePaymentManagementTest):
    def test_one_time_fee_not_rebilled_next_session(self):
        tuition_category = FeeCategory.objects.create(
            school=self.school,
            name='Tuition',
            is_compulsory=True,
            billing_cycle='ONE_TIME',
            student_type=FeeCategory.STUDENT_TYPE_CHOICES[2][0],
        )
        FeeStructure.objects.create(
            school=self.school,
            school_class=self.school_class,
            term=self.term,
            category=tuition_category,
            amount=Decimal('5000.00'),
        )

        invoice = generate_invoice_for_student(self.student, self.term)
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.total_amount, Decimal('5000.00'))

        next_session = AcademicSession.objects.create(
            school=self.school,
            name='2026/2027',
            start_date=date(2026, 9, 1),
            end_date=date(2027, 8, 31),
            is_current=False,
        )
        next_term = Term.objects.create(
            school=self.school,
            session=next_session,
            name='First Term',
            start_date=date(2026, 9, 1),
            end_date=date(2026, 12, 15),
            is_current=True,
        )
        FeeStructure.objects.create(
            school=self.school,
            school_class=self.school_class,
            term=next_term,
            category=tuition_category,
            amount=Decimal('5000.00'),
        )

        invoice2 = generate_invoice_for_student(self.student, next_term)
        self.assertIsNone(invoice2)

    def test_sync_preserves_one_time_guard(self):
        one_time_category = FeeCategory.objects.create(
            school=self.school,
            name='Registration',
            is_compulsory=True,
            billing_cycle='ONE_TIME',
            student_type=FeeCategory.STUDENT_TYPE_CHOICES[2][0],
        )
        one_time_fee = FeeStructure.objects.create(
            school=self.school,
            school_class=self.school_class,
            term=self.term,
            category=one_time_category,
            amount=Decimal('5000.00'),
        )

        invoice = generate_invoice_for_student(self.student, self.term)
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.total_amount, Decimal('5000.00'))

        one_time_fee.delete()

        sync_class_invoices(self.school_class, self.term)
        invoice.refresh_from_db()
        self.assertEqual(invoice.line_items.count(), 1)


# ─── Checkout Grouped Extras Tests ──────────────────────────────────────────


class CheckoutGroupedExtrasTest(BasePaymentManagementTest):
    def test_grouped_extras_returns_dict(self):
        co = get_checkout_options(self.student, self.term)
        self.assertIsNotNone(co.grouped_extras)
        self.assertIsInstance(co.grouped_extras, dict)

    def test_grouped_extras_contains_categories(self):
        co = get_checkout_options(self.student, self.term)
        all_items = []
        for items in co.grouped_extras.values():
            all_items.extend(items)
        self.assertEqual(len(all_items), len(co.extras))
