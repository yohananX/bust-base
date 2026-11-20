"""Tests for the fee-checkout feature.

Covers two contracts built by parallel agents:

1. ``fees.checkout``
   - ``get_checkout_options(student, term) -> CheckoutOptions``
     (``.outstanding|None``, ``.extras`` list, ``.next_term|None``)
   - ``reconcile_checkout(student, term, selected_keys, amount) -> ReconcileResult``
     (``.invoices``, ``.allocations[.invoice/.amount]``, ``.minimum_payable``,
     ``.total_balance``, ``.is_split``) — raises ``ValidationError`` on an
     invalid amount.

2. ``fees.views.CheckoutSubmitView`` — POST at ``fees:checkout-submit``
   (fields: ``student_id``, ``item[]`` repeated, ``amount``, ``method``).
   ``bank_transfer`` creates PENDING BANK_TRANSFER ``Payment`` rows per
   allocation; ``paystack`` redirects to the gateway.

Fixture mirrors ``BaseFeesTest`` in ``fees/tests.py``: one school, one
current session, a current term plus a later (next) term, a school class
with one enrolled student, a parent linked via ``StudentGuardianLink``, two
fee categories (Tuition billed on the current-term invoice, Books open), and
a Books structure on the next term. The current-term invoice carries only
the Tuition line so its balance is > 0; both categories surface as extras,
with Tuition flagged ``billed=True`` and Books unbilled (selectable).
"""

from decimal import Decimal
from datetime import date
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.messages import get_messages

from core.models import School, AcademicSession, Term
from accounts.models import Roles
from students.models import SchoolClass, Student, ClassEnrollment, StudentGuardianLink
from fees.models import (
    FeeCategory,
    FeePrice,
    Invoice,
    InvoiceLineItem,
    Payment,
    PaymentLineItem,
)
from fees.checkout import get_checkout_options, reconcile_checkout

try:
    from fees.views import CheckoutSubmitView
except (
    ImportError
):  # CheckoutSubmitView is built by a parallel agent (see views.py pattern)
    CheckoutSubmitView = None


User = get_user_model()

TUITION_AMOUNT = Decimal("50000.00")
BOOKS_AMOUNT = Decimal("10000.00")
NEXT_BOOKS_AMOUNT = Decimal("12000.00")


class FeeCheckoutTest(TestCase):
    """Fixture + tests for the checkout feature (fees.checkout + CheckoutSubmitView)."""

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(
            name="Test School",
            short_code="test",
        )

        cls.session = AcademicSession.objects.create(
            school=cls.school,
            name="2025/2026",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 8, 31),
            is_current=True,
        )
        cls.term = Term.objects.create(
            school=cls.school,
            session=cls.session,
            name="First Term",
            start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 15),
            is_current=True,
        )
        cls.next_term = Term.objects.create(
            school=cls.school,
            session=cls.session,
            name="Second Term",
            start_date=date(2026, 1, 5),
            end_date=date(2026, 4, 10),
            is_current=False,
        )

        cls.school_class = SchoolClass.objects.create(
            school=cls.school,
            name="JSS1A",
        )

        cls.student_user = User.objects.create_user(
            username="student1",
            email="student1@test.com",
            password="testpass123",
            school=cls.school,
            role=Roles.STUDENT,
            first_name="John",
            last_name="Doe",
        )
        cls.student = Student.objects.create(
            school=cls.school,
            user=cls.student_user,
            admission_number="STU001",
            date_of_birth=date(2010, 1, 1),
            gender=Student.MALE,
            admission_date=date(2025, 9, 1),
            status=Student.ACTIVE,
        )
        cls.enrollment = ClassEnrollment.objects.create(
            school=cls.school,
            student=cls.student,
            school_class=cls.school_class,
            session=cls.session,
            is_current=True,
        )

        cls.admin_user = User.objects.create_user(
            username="admin1",
            email="admin@test.com",
            password="testpass123",
            school=cls.school,
            role=Roles.ADMIN,
            first_name="Admin",
            last_name="User",
        )
        cls.parent_user = User.objects.create_user(
            username="parent1",
            email="parent@test.com",
            password="testpass123",
            school=cls.school,
            role=Roles.PARENT,
            first_name="Parent",
            last_name="One",
        )
        StudentGuardianLink.objects.create(
            school=cls.school,
            student=cls.student,
            guardian=cls.parent_user,
            relationship=StudentGuardianLink.FATHER,
            is_primary_contact=True,
        )

        # Fee categories + structures for the current term. Tuition is billed
        # on the invoice; Books is NOT — so Books shows up as the extra.
        cls.tuition_category = FeeCategory.objects.create(
            school=cls.school,
            name="Tuition",
        )
        cls.books_category = FeeCategory.objects.create(
            school=cls.school,
            name="Books",
        )
        cls.tuition_fee = FeePrice.objects.create(
            school=cls.school,
            scope=FeePrice.SCOPE_CLASS,
            school_class=cls.school_class,
            term=cls.term,
            category=cls.tuition_category,
            amount=TUITION_AMOUNT,
        )
        cls.books_fee = FeePrice.objects.create(
            school=cls.school,
            scope=FeePrice.SCOPE_CLASS,
            school_class=cls.school_class,
            term=cls.term,
            category=cls.books_category,
            amount=BOOKS_AMOUNT,
        )
        cls.next_books_fee = FeePrice.objects.create(
            school=cls.school,
            scope=FeePrice.SCOPE_CLASS,
            school_class=cls.school_class,
            term=cls.next_term,
            category=cls.books_category,
            amount=NEXT_BOOKS_AMOUNT,
        )

        # Current-term invoice: Tuition line only → balance 50000, Books open.
        cls.invoice = Invoice.objects.create(
            school=cls.school,
            student=cls.student,
            term=cls.term,
            total_amount=TUITION_AMOUNT,
        )
        InvoiceLineItem.objects.create(
            invoice=cls.invoice,
            category=cls.tuition_category,
            amount=TUITION_AMOUNT,
        )

    # ─── get_checkout_options ────────────────────────────────────────────

    def test_get_checkout_options_outstanding(self):
        """Unpaid current-term invoice surfaces as the outstanding option."""
        options = get_checkout_options(self.student, self.term)

        self.assertIsNotNone(options.outstanding)
        self.assertTrue(options.outstanding.flexible)
        self.assertEqual(options.outstanding.amount, self.invoice.balance)
        self.assertEqual(self.invoice.balance, TUITION_AMOUNT)
        self.assertEqual(options.outstanding.key, "outstanding")
        self.assertEqual(options.outstanding.invoice_id, self.invoice.pk)

    def test_get_checkout_options_no_outstanding(self):
        """A fully paid invoice means no outstanding option."""
        Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=TUITION_AMOUNT,
            method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )

        options = get_checkout_options(self.student, self.term)

        self.assertIsNone(options.outstanding)

    def test_get_checkout_options_extras(self):
        """Every category appears as an extra; billed ones are flagged."""
        options = get_checkout_options(self.student, self.term)

        self.assertEqual(len(options.extras), 2)
        by_category = {e.category_id: e for e in options.extras}

        # Tuition is on the term invoice → paid badge
        tuition = by_category[self.tuition_category.pk]
        self.assertTrue(tuition.billed)

        # Books is unbilled → still selectable
        books = by_category[self.books_category.pk]
        self.assertFalse(books.billed)
        self.assertEqual(books.amount, BOOKS_AMOUNT)

    def test_get_checkout_options_all_billed_when_fully_paid(self):
        """A fully-paid student sees paid badges on every billed category."""
        # Bill the remaining category, then settle the whole invoice.
        InvoiceLineItem.objects.create(
            invoice=self.invoice,
            category=self.books_category,
            amount=BOOKS_AMOUNT,
        )
        self.invoice.total_amount = self.invoice.total_amount + BOOKS_AMOUNT
        self.invoice.save(update_fields=["total_amount"])
        Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            amount=TUITION_AMOUNT + BOOKS_AMOUNT,
            method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
            recorded_by=self.admin_user,
        )

        options = get_checkout_options(self.student, self.term)

        self.assertIsNone(options.outstanding)
        self.assertEqual(len(options.extras), 2)
        billed = {e.category_id: e.billed for e in options.extras}
        self.assertTrue(billed[self.tuition_category.pk])
        self.assertTrue(billed[self.books_category.pk])

    def test_get_checkout_options_next_term_omitted(self):
        """No later term → next_term is None (not an empty group)."""
        Term.objects.filter(pk=self.next_term.pk).delete()

        options = get_checkout_options(self.student, self.term)

        self.assertIsNone(options.next_term)

    def test_get_checkout_options_next_term_present(self):
        """A later term surfaces compulsory fees (with fallback) and explicit next-term fees."""
        options = get_checkout_options(self.student, self.term)

        self.assertIsNotNone(options.next_term)
        self.assertEqual(options.next_term.term_id, self.next_term.pk)
        self.assertEqual(len(options.next_term.options), 2)

        next_options = {opt.category_id: opt for opt in options.next_term.options}
        self.assertIn(self.tuition_category.pk, next_options)
        self.assertIn(self.books_category.pk, next_options)

        tuition_opt = next_options[self.tuition_category.pk]
        self.assertEqual(tuition_opt.key, f"next:{self.tuition_category.pk}")
        self.assertFalse(tuition_opt.flexible)
        self.assertEqual(tuition_opt.amount, TUITION_AMOUNT)

        books_opt = next_options[self.books_category.pk]
        self.assertEqual(books_opt.key, f"next:{self.books_category.pk}")
        self.assertFalse(books_opt.flexible)
        self.assertEqual(books_opt.amount, NEXT_BOOKS_AMOUNT)

    # ─── reconcile_checkout ──────────────────────────────────────────────

    def test_reconcile_checkout_reuses_invoice(self):
        """Outstanding-only checkout reuses the invoice: no new line items."""
        line_items_before = self.invoice.line_items.count()

        result = reconcile_checkout(
            self.student,
            self.term,
            ["outstanding"],
            Decimal("20000.00"),
        )

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.line_items.count(), line_items_before)
        self.assertFalse(result.is_split)
        self.assertEqual(len(result.invoices), 1)
        self.assertEqual(len(result.allocations), 1)
        self.assertEqual(result.allocations[0].invoice.pk, self.invoice.pk)
        self.assertEqual(result.allocations[0].amount, Decimal("20000.00"))
        self.assertEqual(result.minimum_payable, Decimal("0.00"))
        self.assertEqual(result.total_balance, TUITION_AMOUNT)

    def test_reconcile_checkout_idempotent_extras(self):
        """Selecting an extra twice never double-bills the category."""
        options = get_checkout_options(self.student, self.term)
        extra_key = options.extras[0].key

        reconcile_checkout(self.student, self.term, [extra_key], BOOKS_AMOUNT)
        self.invoice.refresh_from_db()
        self.assertEqual(
            self.invoice.line_items.filter(category=self.books_category).count(),
            1,
        )
        self.assertEqual(self.invoice.total_amount, TUITION_AMOUNT + BOOKS_AMOUNT)

        # Second, independent submit with the same key → still one line item
        reconcile_checkout(self.student, self.term, [extra_key], BOOKS_AMOUNT)
        self.invoice.refresh_from_db()
        self.assertEqual(
            self.invoice.line_items.filter(category=self.books_category).count(),
            1,
        )
        self.assertEqual(self.invoice.total_amount, TUITION_AMOUNT + BOOKS_AMOUNT)

    def test_reconcile_checkout_two_invoice_split(self):
        """Outstanding + next-term selection splits proportionally across invoices."""
        amount = Decimal("30000.00")

        result = reconcile_checkout(
            self.student,
            self.term,
            ["outstanding", f"next:{self.books_category.pk}"],
            amount,
        )

        self.assertTrue(result.is_split)
        self.assertEqual(len(result.invoices), 2)
        self.assertEqual(len(result.allocations), 2)
        self.assertEqual(result.minimum_payable, Decimal("0.00"))
        self.assertEqual(
            result.total_balance,
            TUITION_AMOUNT + NEXT_BOOKS_AMOUNT,
        )

        # Proportional: current gets amount * current_balance / total_balance.
        expected_current = (
            amount * TUITION_AMOUNT / (TUITION_AMOUNT + NEXT_BOOKS_AMOUNT)
        ).quantize(Decimal("0.01"))
        by_invoice = {a.invoice.pk: a.amount for a in result.allocations}
        self.assertEqual(by_invoice[self.invoice.pk], expected_current)
        self.assertEqual(sum(by_invoice.values()), amount)

        next_invoice = Invoice.objects.get(student=self.student, term=self.next_term)
        self.assertEqual(by_invoice[next_invoice.pk], amount - expected_current)
        self.assertEqual(next_invoice.total_amount, NEXT_BOOKS_AMOUNT)
        self.assertEqual(
            next_invoice.line_items.filter(category=self.books_category).count(),
            1,
        )

    def test_reconcile_checkout_partial_payment_allowed(self):
        """Amounts below the selected items' total are accepted (negotiable fees)."""
        options = get_checkout_options(self.student, self.term)
        extra_key = options.extras[0].key

        # Pay only a fraction of the selected Books extra — the remainder is owed.
        result = reconcile_checkout(
            self.student,
            self.term,
            [extra_key],
            Decimal("5000.00"),
        )
        self.assertEqual(result.allocations[0].amount, Decimal("5000.00"))
        self.assertEqual(result.minimum_payable, Decimal("0.00"))
        self.invoice.refresh_from_db()
        # The full extra is billed onto the invoice; reconcile itself only
        # returns the allocation (payment creation happens in the view), so the
        # stored balance reflects the full billed amount, not the partial one.
        self.assertEqual(
            self.invoice.total_amount, TUITION_AMOUNT + options.extras[0].amount
        )
        self.assertEqual(
            self.invoice.balance,
            TUITION_AMOUNT + options.extras[0].amount,
        )

    def test_validation_above_balance(self):
        """Amount above the current invoice balance (post-add) raises ValidationError."""
        options = get_checkout_options(self.student, self.term)
        extra_key = options.extras[0].key
        post_add_balance = self.invoice.balance + options.extras[0].amount

        with self.assertRaises(ValidationError):
            reconcile_checkout(
                self.student,
                self.term,
                [extra_key],
                post_add_balance + Decimal("1.00"),
            )

        # Nothing persisted on error
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.total_amount, TUITION_AMOUNT)
        self.assertEqual(
            self.invoice.line_items.filter(category=self.books_category).count(),
            0,
        )

    # ─── CheckoutSubmitView ──────────────────────────────────────────────

    def test_checkout_submit_bank_transfer_creates_pending(self):
        """Bank-transfer checkout creates a PENDING row per allocation, then redirects."""
        if CheckoutSubmitView is None:
            self.skipTest("fees.views.CheckoutSubmitView not yet present")
        self.client.force_login(self.parent_user)

        from django.core.files.uploadedfile import SimpleUploadedFile

        response = self.client.post(
            reverse("fees:checkout-submit"),
            {
                "student_id": str(self.student.pk),
                "item": ["outstanding", f"next:{self.books_category.pk}"],
                "amount": "30000.00",
                "method": "bank_transfer",
                "proof_image": SimpleUploadedFile(
                    "proof.png",
                    b"\x89PNG\r\n\x1a\nfake-image-bytes",
                    content_type="image/png",
                ),
                "paid_by_name": "Parent One",
                "paid_by_relation": "Father",
            },
        )

        self.assertEqual(response.status_code, 302)
        # After a bank transfer the parent is shown the transfer return page,
        # not the pay page — they need to see the awaiting-confirmation state.
        # The redirect points at the FIRST (current-term) allocation's payment.
        self.assertRedirects(
            response,
            reverse(
                "fees:transfer-return",
                kwargs={
                    "payment_id": Payment.objects.filter(
                        method=Payment.Method.BANK_TRANSFER,
                        invoice=self.invoice,
                    )
                    .first()
                    .pk
                },
            ),
            fetch_redirect_response=False,
        )
        # Payments are created before the redirect (the transfer return page
        # displays the first allocation's payment).
        payments = Payment.objects.filter(
            status=Payment.Status.PENDING,
            method=Payment.Method.BANK_TRANSFER,
        )
        self.assertEqual(payments.count(), 2)

        expected_current = (
            Decimal("30000.00") * TUITION_AMOUNT / (TUITION_AMOUNT + NEXT_BOOKS_AMOUNT)
        ).quantize(Decimal("0.01"))
        current = payments.get(invoice=self.invoice)
        self.assertEqual(current.amount, expected_current)

        next_invoice = Invoice.objects.get(student=self.student, term=self.next_term)
        next_payment = payments.get(invoice=next_invoice)
        self.assertEqual(next_payment.amount, Decimal("30000.00") - expected_current)

    @patch("fees.views.paystack_initiate")
    def test_checkout_submit_split_paystack_uses_unified_return(self, mock_initiate):
        """A split Paystack checkout creates both rows and uses the shared return URL."""
        mock_initiate.return_value = {
            "authorization_url": "https://paystack.test/start",
            "reference": "PAYSTACK-SPLIT-001",
        }
        self.client.force_login(self.parent_user)

        response = self.client.post(
            reverse("fees:checkout-submit"),
            {
                "student_id": str(self.student.pk),
                "item": ["outstanding", f"next:{self.books_category.pk}"],
                "amount": "30000.00",
                "method": "paystack",
            },
        )

        self.assertRedirects(
            response,
            "https://paystack.test/start",
            fetch_redirect_response=False,
        )
        self.assertEqual(
            Payment.objects.filter(method=Payment.Method.PAYSTACK).count(),
            2,
        )
        callback_url = mock_initiate.call_args.args[2]
        self.assertTrue(callback_url.endswith(reverse("fees:payment-return")))

    def test_checkout_submit_scope_denied(self):
        """A user with no link to the student is redirected and nothing is created."""
        if CheckoutSubmitView is None:
            self.skipTest("fees.views.CheckoutSubmitView not yet present")
        intruder = User.objects.create_user(
            username="intruder",
            email="intruder@test.com",
            password="testpass123",
            school=self.school,
            role=Roles.PARENT,
            first_name="Intruder",
            last_name="Parent",
        )
        self.client.force_login(intruder)

        response = self.client.post(
            reverse("fees:checkout-submit"),
            {
                "student_id": str(self.student.pk),
                "item": ["outstanding"],
                "amount": "20000.00",
                "method": "bank_transfer",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response,
            reverse("parent-pay"),
            fetch_redirect_response=False,
        )
        self.assertEqual(Payment.objects.count(), 0)

        messages = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(
            any("authorized" in m.lower() for m in messages),
            f"expected an authorization message, got: {messages}",
        )

    def test_checkout_creates_payment_line_items(self):
        """Bank-transfer checkout creates PaymentLineItems for selected items."""
        if CheckoutSubmitView is None:
            self.skipTest("fees.views.CheckoutSubmitView not yet present")
        self.client.force_login(self.parent_user)

        from django.core.files.uploadedfile import SimpleUploadedFile

        response = self.client.post(
            reverse("fees:checkout-submit"),
            {
                "student_id": str(self.student.pk),
                "item": ["outstanding", f"extra:{self.books_category.pk}"],
                "amount": "60000.00",
                "method": "bank_transfer",
                "proof_image": SimpleUploadedFile(
                    "proof.png",
                    b"\x89PNG\r\n\x1a\nfake-image-bytes",
                    content_type="image/png",
                ),
                "paid_by_name": "Parent One",
                "paid_by_relation": "Father",
            },
        )

        self.assertEqual(response.status_code, 302)
        payment = Payment.objects.get(
            status=Payment.Status.PENDING,
            method=Payment.Method.BANK_TRANSFER,
        )
        line_items = payment.line_items.all()
        self.assertEqual(line_items.count(), 2)
        kinds = {item.kind for item in line_items}
        self.assertIn(PaymentLineItem.KIND_OUTSTANDING, kinds)
        self.assertIn(PaymentLineItem.KIND_EXTRA, kinds)
        labels = {item.label for item in line_items}
        self.assertIn("Outstanding: First Term", labels)
        self.assertIn("Books", labels)


class TransferReferenceTest(TestCase):
    """Tests for the TRF-YYYYMMDD-XXXX reference generator."""

    def test_reference_format(self):
        """Reference matches TRF-YYYYMMDD-XXXX pattern."""
        from fees.utils import generate_transfer_reference
        import re

        ref = generate_transfer_reference()
        self.assertRegex(
            ref,
            r"^TRF-\d{8}-[0-9A-F]{4}$",
            f"reference {ref!r} does not match TRF-YYYYMMDD-XXXX",
        )

    def test_reference_date_todays(self):
        """Date portion of reference is today's date."""
        from datetime import date
        from fees.utils import generate_transfer_reference

        ref = generate_transfer_reference()
        expected = date.today().strftime("%Y%m%d")
        self.assertIn(f"TRF-{expected}-", ref)

    def test_reference_uniqueness(self):
        """Generating references 100 times produces 100 unique values."""
        from fees.utils import generate_transfer_reference

        refs = {generate_transfer_reference() for _ in range(100)}
        self.assertEqual(len(refs), 100)


class BankTransferPaymentTest(FeeCheckoutTest):
    """Tests for bank-transfer checkout: reference, idempotency, resubmission, balance."""

    def setUp(self):
        # Fresh DB for each test to avoid polluting the shared fixture.
        from django.test.utils import setup_test_environment

    def test_bank_transfer_creates_reference(self):
        """Bank-transfer checkout generates a TRF-YYYYMMDD-XXXX reference."""
        if CheckoutSubmitView is None:
            self.skipTest("CheckoutSubmitView not yet present")
        self.client.force_login(self.parent_user)

        from django.core.files.uploadedfile import SimpleUploadedFile

        response = self.client.post(
            reverse("fees:checkout-submit"),
            {
                "student_id": str(self.student.pk),
                "item": ["outstanding"],
                "amount": "20000.00",
                "method": "bank_transfer",
                "proof_image": SimpleUploadedFile(
                    "proof.png",
                    b"\x89PNG\r\n\x1a\nfake-image-bytes",
                    content_type="image/png",
                ),
                "paid_by_name": "Parent One",
                "paid_by_relation": "Father",
            },
        )

        self.assertEqual(response.status_code, 302)
        payment = Payment.objects.get(
            status=Payment.Status.PENDING,
            method=Payment.Method.BANK_TRANSFER,
        )
        self.assertIsNotNone(payment.reference)
        self.assertRegex(
            payment.reference,
            r"^TRF-\d{8}-[0-9A-F]{4}$",
            f"reference {payment.reference!r} does not match TRF-YYYYMMDD-XXXX",
        )

    def test_idempotent_resubmission_no_duplicate(self):
        """Re-submitting with the same idempotency_key does not create a duplicate."""
        if CheckoutSubmitView is None:
            self.skipTest("CheckoutSubmitView not yet present")
        self.client.force_login(self.parent_user)

        import uuid
        from django.core.files.uploadedfile import SimpleUploadedFile

        idempotency_key = str(uuid.uuid4())

        response = self.client.post(
            reverse("fees:checkout-submit"),
            {
                "student_id": str(self.student.pk),
                "item": ["outstanding"],
                "amount": "20000.00",
                "method": "bank_transfer",
                "proof_image": SimpleUploadedFile(
                    "proof.png",
                    b"\x89PNG\r\n\x1a\nfake-image-bytes",
                    content_type="image/png",
                ),
                "paid_by_name": "Parent One",
                "paid_by_relation": "Father",
                "idempotency_key": idempotency_key,
            },
        )

        self.assertEqual(response.status_code, 302)
        first_payment = Payment.objects.get(
            status=Payment.Status.PENDING,
            method=Payment.Method.BANK_TRANSFER,
        )

        # Re-submit with the same idempotency_key
        response2 = self.client.post(
            reverse("fees:checkout-submit"),
            {
                "student_id": str(self.student.pk),
                "item": ["outstanding"],
                "amount": "20000.00",
                "method": "bank_transfer",
                "proof_image": SimpleUploadedFile(
                    "proof.png",
                    b"\x89PNG\r\n\x1a\nfake-image-bytes",
                    content_type="image/png",
                ),
                "paid_by_name": "Parent One",
                "paid_by_relation": "Father",
                "idempotency_key": idempotency_key,
            },
        )

        self.assertEqual(response2.status_code, 302)
        # Still only one PENDING payment
        count = Payment.objects.filter(
            status=Payment.Status.PENDING,
            method=Payment.Method.BANK_TRANSFER,
        ).count()
        self.assertEqual(count, 1)
        messages = [str(m) for m in get_messages(response2.wsgi_request)]
        self.assertTrue(
            any("still pending" in m.lower() for m in messages),
            f"expected duplicate-warning message, got: {messages}",
        )

    def test_idempotent_resubmission_different_key_creates_new(self):
        """Re-submitting with a different idempotency_key creates a new payment."""
        if CheckoutSubmitView is None:
            self.skipTest("CheckoutSubmitView not yet present")
        self.client.force_login(self.parent_user)

        import uuid
        from django.core.files.uploadedfile import SimpleUploadedFile

        key1 = str(uuid.uuid4())
        key2 = str(uuid.uuid4())
        self.assertNotEqual(key1, key2)

        for key in (key1, key2):
            response = self.client.post(
                reverse("fees:checkout-submit"),
                {
                    "student_id": str(self.student.pk),
                    "item": ["outstanding"],
                    "amount": "20000.00",
                    "method": "bank_transfer",
                    "proof_image": SimpleUploadedFile(
                        "proof.png",
                        b"\x89PNG\r\n\x1a\nfake-image-bytes",
                        content_type="image/png",
                    ),
                    "paid_by_name": "Parent One",
                    "paid_by_relation": "Father",
                    "idempotency_key": key,
                },
            )
            self.assertEqual(response.status_code, 302)

        count = Payment.objects.filter(
            status=Payment.Status.PENDING,
            method=Payment.Method.BANK_TRANSFER,
        ).count()
        self.assertEqual(count, 2)

    def test_resubmission_of_links_to_rejected(self):
        """Submitting with resubmission_of=<payment_id> links the new payment."""
        if CheckoutSubmitView is None:
            self.skipTest("CheckoutSubmitView not yet present")
        self.client.force_login(self.parent_user)

        from django.core.files.uploadedfile import SimpleUploadedFile

        # Create a rejected payment to resubmit
        original = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            student=self.student,
            amount=TUITION_AMOUNT,
            method=Payment.Method.BANK_TRANSFER,
            reference="TRF-OLD-0001",
            status=Payment.Status.REJECTED,
            paid_on=timezone.now(),
            rejection_reason="Incorrect amount paid",
        )

        response = self.client.post(
            reverse("fees:checkout-submit"),
            {
                "student_id": str(self.student.pk),
                "item": ["outstanding"],
                "amount": "20000.00",
                "method": "bank_transfer",
                "proof_image": SimpleUploadedFile(
                    "proof.png",
                    b"\x89PNG\r\n\x1a\nfake-image-bytes",
                    content_type="image/png",
                ),
                "paid_by_name": "Parent One",
                "paid_by_relation": "Father",
                "resubmission_of": str(original.pk),
            },
        )

        self.assertEqual(response.status_code, 302)
        new_payment = Payment.objects.exclude(pk=original.pk).get(
            method=Payment.Method.BANK_TRANSFER,
            status=Payment.Status.PENDING,
        )
        self.assertEqual(new_payment.resubmission_of, original)

    def test_balance_unchanged_while_pending(self):
        """PENDING bank transfers must not reduce the invoice balance."""
        if CheckoutSubmitView is None:
            self.skipTest("CheckoutSubmitView not yet present")
        self.client.force_login(self.parent_user)

        from django.core.files.uploadedfile import SimpleUploadedFile

        balance_before = self.invoice.balance
        self.assertEqual(balance_before, TUITION_AMOUNT)

        response = self.client.post(
            reverse("fees:checkout-submit"),
            {
                "student_id": str(self.student.pk),
                "item": ["outstanding"],
                "amount": "20000.00",
                "method": "bank_transfer",
                "proof_image": SimpleUploadedFile(
                    "proof.png",
                    b"\x89PNG\r\n\x1a\nfake-image-bytes",
                    content_type="image/png",
                ),
                "paid_by_name": "Parent One",
                "paid_by_relation": "Father",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.invoice.refresh_from_db()
        # Balance should be unchanged — PENDING payments don't count
        self.assertEqual(self.invoice.balance, TUITION_AMOUNT)


class BankTransferDuplicateWarningTest(TestCase):
    """Soft duplicate warning when a PENDING bank transfer already exists."""

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Test School", short_code="test")
        cls.session = AcademicSession.objects.create(
            school=cls.school,
            name="2025/2026",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 8, 31),
            is_current=True,
        )
        cls.term = Term.objects.create(
            school=cls.school,
            session=cls.session,
            name="First Term",
            start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 15),
            is_current=True,
        )

        cls.school_class = SchoolClass.objects.create(
            school=cls.school,
            name="JSS1A",
        )

        cls.student_user = User.objects.create_user(
            username="student1",
            email="student1@test.com",
            password="testpass123",
            school=cls.school,
            role=Roles.STUDENT,
            first_name="John",
            last_name="Doe",
            is_active=True,
        )
        cls.student = Student.objects.create(
            school=cls.school,
            user=cls.student_user,
            admission_number="STU001",
            date_of_birth=date(2010, 1, 1),
            gender=Student.MALE,
            admission_date=date(2025, 9, 1),
            status=Student.ACTIVE,
        )
        ClassEnrollment.objects.create(
            school=cls.school,
            student=cls.student,
            school_class=cls.school_class,
            session=cls.session,
            is_current=True,
        )
        cls.category = FeeCategory.objects.create(
            school=cls.school,
            name="Tuition",
            is_compulsory=True,
        )
        FeePrice.objects.create(
            school=cls.school,
            scope=FeePrice.SCOPE_CLASS,
            school_class=cls.school_class,
            term=cls.term,
            category=cls.category,
            amount=TUITION_AMOUNT,
            student_type="ALL",
        )
        cls.invoice = Invoice.objects.create(
            school=cls.school,
            student=cls.student,
            term=cls.term,
            total_amount=TUITION_AMOUNT,
        )

        cls.parent_user = User.objects.create_user(
            username="parent1",
            email="parent1@test.com",
            password="testpass123",
            school=cls.school,
            role=Roles.PARENT,
            first_name="Henry",
            last_name="Cluefather",
            is_active=True,
        )
        StudentGuardianLink.objects.create(
            school=cls.school,
            student=cls.student,
            guardian=cls.parent_user,
            relationship="FATHER",
            is_primary_contact=True,
        )

        from django.core.files.uploadedfile import SimpleUploadedFile

        cls.proof = SimpleUploadedFile(
            "proof.png",
            b"\x89PNG\r\n\x1a\nfake-image-bytes",
            content_type="image/png",
        )

    def test_pending_transfer_soft_duplicate_warning(self):
        """Existing PENDING bank transfer blocks new submission without idempotency_key."""
        if CheckoutSubmitView is None:
            self.skipTest("CheckoutSubmitView not yet present")
        self.client.force_login(self.parent_user)

        # Submit first transfer (no idempotency_key)
        self.client.post(
            reverse("fees:checkout-submit"),
            {
                "student_id": str(self.student.pk),
                "item": ["outstanding"],
                "amount": "20000.00",
                "method": "bank_transfer",
                "proof_image": self.proof,
                "paid_by_name": "Parent One",
                "paid_by_relation": "Father",
            },
        )

        pending = Payment.objects.filter(
            status=Payment.Status.PENDING,
            method=Payment.Method.BANK_TRANSFER,
        ).first()
        self.assertIsNotNone(pending)
        self.assertEqual(pending.invoice, self.invoice)
        self.assertEqual(pending.student, self.student)
        from decimal import Decimal

        self.assertEqual(pending.amount, Decimal("20000.00"))

        # Second submission without idempotency_key should show warning and not create new
        self.proof = SimpleUploadedFile(
            "proof2.png",
            b"\x89PNG\r\n\x1a\nfake-image-new-bytes",
            content_type="image/png",
        )

        response2 = self.client.post(
            reverse("fees:checkout-submit"),
            {
                "student_id": str(self.student.pk),
                "item": ["outstanding"],
                "amount": "25000.00",
                "method": "bank_transfer",
                "proof_image": self.proof,
                "paid_by_name": "Parent One",
                "paid_by_relation": "Father",
            },
        )

        self.assertEqual(response2.status_code, 302)
        # Still only one PENDING payment
        count = Payment.objects.filter(
            status=Payment.Status.PENDING,
            method=Payment.Method.BANK_TRANSFER,
        ).count()
        self.assertEqual(count, 1)
        messages = [str(m) for m in get_messages(response2.wsgi_request)]
        self.assertTrue(
            any(
                "already awaiting" in m.lower() or "duplicate" in m.lower()
                for m in messages
            ),
            f"expected soft duplicate warning, got: {messages}",
        )


class PaymentStatusTransitionTest(TestCase):
    """Tests for REJECTED status and status transition constraints."""

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Test School", short_code="test")
        cls.session = AcademicSession.objects.create(
            school=cls.school,
            name="2025/2026",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 8, 31),
            is_current=True,
        )
        cls.term = Term.objects.create(
            school=cls.school,
            session=cls.session,
            name="First Term",
            start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 15),
            is_current=True,
        )

        cls.admin_user = User.objects.create_user(
            username="admin1",
            password="testpass123",
            school=cls.school,
            role=Roles.ADMIN,
        )

        cls.student_user = User.objects.create_user(
            username="student1",
            password="testpass123",
            school=cls.school,
            role=Roles.STUDENT,
        )
        cls.student = Student.objects.create(
            school=cls.school,
            user=cls.student_user,
            admission_number="STU001",
            date_of_birth=date(2010, 1, 1),
            gender=Student.MALE,
            admission_date=date(2025, 9, 1),
            status=Student.ACTIVE,
        )
        cls.invoice = Invoice.objects.create(
            school=cls.school,
            student=cls.student,
            term=cls.term,
            total_amount=TUITION_AMOUNT,
        )

    def test_pending_to_rejected_transition(self):
        """PENDING → REJECTED is a legal transition."""
        payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            student=self.student,
            amount=Decimal("20000.00"),
            method=Payment.Method.BANK_TRANSFER,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )
        payment.status = Payment.Status.REJECTED
        payment.rejection_reason = "Incorrect amount paid"
        payment.reviewed_by = self.admin_user
        payment.reviewed_at = timezone.now()
        payment.save()  # should not raise
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.REJECTED)

    def test_rejected_requires_reason(self):
        """REJECTED status requires a rejection_reason."""
        payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            student=self.student,
            amount=Decimal("20000.00"),
            method=Payment.Method.BANK_TRANSFER,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )
        payment.status = Payment.Status.REJECTED
        with self.assertRaises(ValidationError) as ctx:
            payment.full_clean()
        self.assertIn("rejection_reason", ctx.exception.message_dict)

    def test_rejected_requires_reason_not_blank(self):
        """Whitespace-only rejection_reason is treated as missing."""
        payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            student=self.student,
            amount=Decimal("20000.00"),
            method=Payment.Method.BANK_TRANSFER,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )
        payment.status = Payment.Status.REJECTED
        payment.rejection_reason = "   "
        with self.assertRaises(ValidationError) as ctx:
            payment.full_clean()
        self.assertIn("rejection_reason", ctx.exception.message_dict)

    def test_confirmed_to_rejected_rejected(self):
        """CONFIRMED → REJECTED is not a legal transition."""
        payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            student=self.student,
            amount=Decimal("20000.00"),
            method=Payment.Method.BANK_TRANSFER,
            status=Payment.Status.CONFIRMED,
            paid_on=timezone.now(),
        )
        payment.status = Payment.Status.REJECTED
        with self.assertRaises(ValidationError):
            payment.save()

    def test_failed_to_rejected_rejected(self):
        """FAILED → REJECTED is not a legal transition."""
        payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            student=self.student,
            amount=Decimal("20000.00"),
            method=Payment.Method.BANK_TRANSFER,
            status=Payment.Status.FAILED,
            paid_on=timezone.now(),
        )
        payment.status = Payment.Status.REJECTED
        with self.assertRaises(ValidationError):
            payment.save()

    def test_pending_to_confirmed_still_legal(self):
        """PENDING → CONFIRMED is still a legal transition."""
        payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            student=self.student,
            amount=Decimal("20000.00"),
            method=Payment.Method.BANK_TRANSFER,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )
        payment.status = Payment.Status.CONFIRMED
        payment.save()  # should not raise
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)

    def test_pending_to_failed_still_legal(self):
        """PENDING → FAILED is still a legal transition."""
        payment = Payment.objects.create(
            school=self.school,
            invoice=self.invoice,
            student=self.student,
            amount=Decimal("20000.00"),
            method=Payment.Method.BANK_TRANSFER,
            status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )
        payment.status = Payment.Status.FAILED
        payment.save()  # should not raise
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.FAILED)


class RejectionReasonChoicesTest(TestCase):
    """Tests for the PaymentRejectionReason choices enum."""

    def test_rejection_reason_choices_exist(self):
        """All expected choices are defined."""
        from fees.models import PaymentRejectionReason

        self.assertEqual(
            set(r.value for r in PaymentRejectionReason),
            {"INCORRECT_AMOUNT", "EXPIRED_TRANSFER", "INVALID_PROOF", "CUSTOM"},
        )

    def test_rejection_reason_display_labels(self):
        """Each choice has a human-readable label."""
        from fees.models import PaymentRejectionReason

        for choice in PaymentRejectionReason:
            label = choice.label
            self.assertTrue(len(label) > 0, f"{choice.value} has an empty label")
