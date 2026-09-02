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

from django.test import TestCase
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages

from core.models import School, AcademicSession, Term
from accounts.models import Roles
from students.models import SchoolClass, Student, ClassEnrollment, StudentGuardianLink
from fees.models import FeeCategory, FeePrice, Invoice, InvoiceLineItem, Payment, PaymentLineItem
from fees.checkout import get_checkout_options, reconcile_checkout
try:
    from fees.views import CheckoutSubmitView
except ImportError:  # CheckoutSubmitView is built by a parallel agent (see views.py pattern)
    CheckoutSubmitView = None


User = get_user_model()

TUITION_AMOUNT = Decimal('50000.00')
BOOKS_AMOUNT = Decimal('10000.00')
NEXT_BOOKS_AMOUNT = Decimal('12000.00')


class FeeCheckoutTest(TestCase):
    """Fixture + tests for the checkout feature (fees.checkout + CheckoutSubmitView)."""

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(
            name='Test School',
            short_code='test',
        )

        cls.session = AcademicSession.objects.create(
            school=cls.school,
            name='2025/2026',
            start_date=date(2025, 9, 1),
            end_date=date(2026, 8, 31),
            is_current=True,
        )
        cls.term = Term.objects.create(
            school=cls.school,
            session=cls.session,
            name='First Term',
            start_date=date(2025, 9, 1),
            end_date=date(2025, 12, 15),
            is_current=True,
        )
        cls.next_term = Term.objects.create(
            school=cls.school,
            session=cls.session,
            name='Second Term',
            start_date=date(2026, 1, 5),
            end_date=date(2026, 4, 10),
            is_current=False,
        )

        cls.school_class = SchoolClass.objects.create(
            school=cls.school,
            name='JSS1A',
            level='JSS1',
        )

        cls.student_user = User.objects.create_user(
            username='student1',
            email='student1@test.com',
            password='testpass123',
            school=cls.school,
            role=Roles.STUDENT,
            first_name='John',
            last_name='Doe',
        )
        cls.student = Student.objects.create(
            school=cls.school,
            user=cls.student_user,
            admission_number='STU001',
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
            username='admin1',
            email='admin@test.com',
            password='testpass123',
            school=cls.school,
            role=Roles.ADMIN,
            first_name='Admin',
            last_name='User',
        )
        cls.parent_user = User.objects.create_user(
            username='parent1',
            email='parent@test.com',
            password='testpass123',
            school=cls.school,
            role=Roles.PARENT,
            first_name='Parent',
            last_name='One',
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
            name='Tuition',
        )
        cls.books_category = FeeCategory.objects.create(
            school=cls.school,
            name='Books',
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
        self.assertEqual(options.outstanding.key, 'outstanding')
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
        self.invoice.save(update_fields=['total_amount'])
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
        self.assertEqual(tuition_opt.key, f'next:{self.tuition_category.pk}')
        self.assertFalse(tuition_opt.flexible)
        self.assertEqual(tuition_opt.amount, TUITION_AMOUNT)

        books_opt = next_options[self.books_category.pk]
        self.assertEqual(books_opt.key, f'next:{self.books_category.pk}')
        self.assertFalse(books_opt.flexible)
        self.assertEqual(books_opt.amount, NEXT_BOOKS_AMOUNT)

    # ─── reconcile_checkout ──────────────────────────────────────────────

    def test_reconcile_checkout_reuses_invoice(self):
        """Outstanding-only checkout reuses the invoice: no new line items."""
        line_items_before = self.invoice.line_items.count()

        result = reconcile_checkout(
            self.student, self.term, ['outstanding'], Decimal('20000.00'),
        )

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.line_items.count(), line_items_before)
        self.assertFalse(result.is_split)
        self.assertEqual(len(result.invoices), 1)
        self.assertEqual(len(result.allocations), 1)
        self.assertEqual(result.allocations[0].invoice.pk, self.invoice.pk)
        self.assertEqual(result.allocations[0].amount, Decimal('20000.00'))
        self.assertEqual(result.minimum_payable, Decimal('0.00'))
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
        amount = Decimal('30000.00')

        result = reconcile_checkout(
            self.student, self.term,
            ['outstanding', f'next:{self.books_category.pk}'],
            amount,
        )

        self.assertTrue(result.is_split)
        self.assertEqual(len(result.invoices), 2)
        self.assertEqual(len(result.allocations), 2)
        self.assertEqual(result.minimum_payable, Decimal('0.00'))
        self.assertEqual(
            result.total_balance,
            TUITION_AMOUNT + NEXT_BOOKS_AMOUNT,
        )

        # Proportional: current gets amount * current_balance / total_balance.
        expected_current = (amount * TUITION_AMOUNT / (TUITION_AMOUNT + NEXT_BOOKS_AMOUNT)).quantize(Decimal('0.01'))
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
            self.student, self.term, [extra_key], Decimal('5000.00'),
        )
        self.assertEqual(result.allocations[0].amount, Decimal('5000.00'))
        self.assertEqual(result.minimum_payable, Decimal('0.00'))
        self.invoice.refresh_from_db()
        # The full extra is billed onto the invoice; reconcile itself only
        # returns the allocation (payment creation happens in the view), so the
        # stored balance reflects the full billed amount, not the partial one.
        self.assertEqual(self.invoice.total_amount, TUITION_AMOUNT + options.extras[0].amount)
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
                self.student, self.term, [extra_key],
                post_add_balance + Decimal('1.00'),
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
            self.skipTest('fees.views.CheckoutSubmitView not yet present')
        self.client.force_login(self.parent_user)

        from django.core.files.uploadedfile import SimpleUploadedFile
        response = self.client.post(reverse('fees:checkout-submit'), {
            'student_id': str(self.student.pk),
            'item': ['outstanding', f'next:{self.books_category.pk}'],
            'amount': '30000.00',
            'method': 'bank_transfer',
            'proof_image': SimpleUploadedFile(
                'proof.png', b'\x89PNG\r\n\x1a\nfake-image-bytes', content_type='image/png'
            ),
            'paid_by_name': 'Parent One',
            'paid_by_relation': 'Father',
        })

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response, reverse('parent-pay'), fetch_redirect_response=False,
        )

        payments = Payment.objects.filter(
            status=Payment.Status.PENDING,
            method=Payment.Method.BANK_TRANSFER,
        )
        self.assertEqual(payments.count(), 2)

        expected_current = (Decimal('30000.00') * TUITION_AMOUNT / (TUITION_AMOUNT + NEXT_BOOKS_AMOUNT)).quantize(Decimal('0.01'))
        current = payments.get(invoice=self.invoice)
        self.assertEqual(current.amount, expected_current)

        next_invoice = Invoice.objects.get(student=self.student, term=self.next_term)
        next_payment = payments.get(invoice=next_invoice)
        self.assertEqual(next_payment.amount, Decimal('30000.00') - expected_current)

    def test_checkout_submit_scope_denied(self):
        """A user with no link to the student is redirected and nothing is created."""
        if CheckoutSubmitView is None:
            self.skipTest('fees.views.CheckoutSubmitView not yet present')
        intruder = User.objects.create_user(
            username='intruder',
            email='intruder@test.com',
            password='testpass123',
            school=self.school,
            role=Roles.PARENT,
            first_name='Intruder',
            last_name='Parent',
        )
        self.client.force_login(intruder)

        response = self.client.post(reverse('fees:checkout-submit'), {
            'student_id': str(self.student.pk),
            'item': ['outstanding'],
            'amount': '20000.00',
            'method': 'bank_transfer',
        })

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(
            response, reverse('parent-pay'), fetch_redirect_response=False,
        )
        self.assertEqual(Payment.objects.count(), 0)

        messages = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(
            any('authorized' in m.lower() for m in messages),
            f'expected an authorization message, got: {messages}',
        )

    def test_checkout_creates_payment_line_items(self):
        """Bank-transfer checkout creates PaymentLineItems for selected items."""
        if CheckoutSubmitView is None:
            self.skipTest('fees.views.CheckoutSubmitView not yet present')
        self.client.force_login(self.parent_user)

        from django.core.files.uploadedfile import SimpleUploadedFile
        response = self.client.post(reverse('fees:checkout-submit'), {
            'student_id': str(self.student.pk),
            'item': ['outstanding', f'extra:{self.books_category.pk}'],
            'amount': '60000.00',
            'method': 'bank_transfer',
            'proof_image': SimpleUploadedFile(
                'proof.png', b'\x89PNG\r\n\x1a\nfake-image-bytes', content_type='image/png'
            ),
            'paid_by_name': 'Parent One',
            'paid_by_relation': 'Father',
        })

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
        self.assertIn('Outstanding: First Term', labels)
        self.assertIn('Books', labels)