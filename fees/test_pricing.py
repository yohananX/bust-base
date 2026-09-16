from decimal import Decimal
from datetime import date
from datetime import timedelta

from django.test import TestCase
from django.db import IntegrityError
from django.utils import timezone

from core.models import School, AcademicSession, Term
from students.models import SchoolClass, Student, ClassEnrollment
from accounts.models import Roles, User
from fees.models import FeeCategory, FeePrice, FeePriceOverride, Invoice
from fees.pricing import resolve_prices, resolve_price_for_student
from fees.generation import (
    generate_invoices_for_level,
    sync_level_invoices,
    generate_invoices_school_wide,
    sync_school_wide_invoices,
)


class BasePricingTest(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='Test School', short_code='test')
        self.session = AcademicSession.objects.create(
            school=self.school, name='2025/2026',
            start_date=date(2025, 9, 1), end_date=date(2026, 8, 31), is_current=True,
        )
        self.term = Term.objects.create(
            school=self.school, session=self.session, name='First Term',
            start_date=date(2025, 9, 1), end_date=date(2025, 12, 15), is_current=True,
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school, name='JSS1A', level='JSS1',
        )
        self.student = Student.objects.create(
            school=self.school,
            user=User.objects.create_user(username='stu1', school=self.school, role=Roles.STUDENT),
            admission_number='STU001', date_of_birth=date(2010, 1, 1), gender='M',
            admission_date=date(2025, 9, 1), status='ACTIVE',
        )
        ClassEnrollment.objects.create(
            school=self.school, student=self.student, school_class=self.school_class,
            session=self.session, is_current=True,
        )


class ResolvePricesTest(BasePricingTest):
    def test_resolve_prices_returns_list(self):
        result = resolve_prices(self.school, self.school_class, self.term)
        self.assertIsInstance(result, list)

    def test_resolve_prices_delegates_to_effective_fee_structures(self):
        from fees.generation import effective_fee_structures
        expected = effective_fee_structures(self.school, self.school_class, self.term)
        actual = resolve_prices(self.school, self.school_class, self.term)
        self.assertEqual(list(expected), list(actual))

    def test_resolve_prices_filters_student_type(self):
        new_cat = FeeCategory.objects.create(
            school=self.school, name='New Only', student_type='NEW', billing_cycle='PER_TERM'
        )
        returning_cat = FeeCategory.objects.create(
            school=self.school, name='Returning Only', student_type='RETURNING', billing_cycle='PER_TERM'
        )
        all_cat = FeeCategory.objects.create(
            school=self.school, name='All', student_type='ALL', billing_cycle='PER_TERM'
        )
        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_CLASS, school_class=self.school_class,
            term=self.term, category=new_cat, amount=Decimal('1000.00'), student_type='NEW'
        )
        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_CLASS, school_class=self.school_class,
            term=self.term, category=returning_cat, amount=Decimal('2000.00'), student_type='RETURNING'
        )
        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_CLASS, school_class=self.school_class,
            term=self.term, category=all_cat, amount=Decimal('3000.00'), student_type='ALL'
        )

        result = resolve_prices(self.school, self.school_class, self.term, student_type='NEW')
        cats = {fp.category.name for fp in result}
        self.assertIn('New Only', cats)
        self.assertIn('All', cats)
        self.assertNotIn('Returning Only', cats)

    def test_resolve_prices_guards_one_time_already_billed(self):
        one_time_cat = FeeCategory.objects.create(
            school=self.school, name='Registration', billing_cycle='ONE_TIME', student_type='NEW'
        )
        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_SCHOOL_WIDE, school_class=None,
            term=None, category=one_time_cat, amount=Decimal('5000.00'), student_type='NEW'
        )
        prior_session = AcademicSession.objects.create(
            school=self.school, name='2024/2025',
            start_date=date(2024, 9, 1), end_date=date(2025, 8, 31), is_current=False,
        )
        prior_term = Term.objects.create(
            school=self.school, session=prior_session, name='First Term',
            start_date=date(2024, 9, 1), end_date=date(2024, 12, 15), is_current=False,
        )
        ClassEnrollment.objects.create(
            school=self.school, student=self.student, school_class=self.school_class,
            session=prior_session, is_current=True,
        )
        from fees.generation import generate_invoice_for_student
        generate_invoice_for_student(self.student, prior_term)

        result = resolve_prices(
            self.school, self.school_class, self.term,
            student_type='NEW', student=self.student, session=self.session
        )
        cats = {fp.category.name for fp in result}
        self.assertNotIn('Registration', cats)

    def test_resolve_prices_term_fallback(self):
        cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL'
        )
        prior_term = Term.objects.create(
            school=self.school, session=self.session, name='Previous Term',
            start_date=date(2025, 1, 1), end_date=date(2025, 3, 31), is_current=False,
        )
        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_CLASS, school_class=self.school_class,
            term=prior_term, category=cat, amount=Decimal('25000.00'), student_type='ALL'
        )
        result = resolve_prices(self.school, self.school_class, self.term)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].amount, Decimal('25000.00'))

    def test_resolve_prices_no_prices_returns_empty(self):
        result = resolve_prices(self.school, self.school_class, self.term)
        self.assertEqual(result, [])


class ScopeFeePriceTest(BasePricingTest):
    def test_school_wide_fee_returned_for_any_class(self):
        cat = FeeCategory.objects.create(
            school=self.school, name='PTA', billing_cycle='ONE_TIME', student_type='NEW'
        )
        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_SCHOOL_WIDE, school_class=None,
            term=None, category=cat, amount=Decimal('1000.00'), student_type='NEW'
        )
        result = resolve_prices(self.school, self.school_class, None, student_type='NEW')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].scope, FeePrice.SCOPE_SCHOOL_WIDE)
        self.assertEqual(result[0].amount, Decimal('1000.00'))

    def test_class_specific_overrides_school_wide_for_same_category(self):
        cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL'
        )
        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_SCHOOL_WIDE, school_class=None,
            term=self.term, category=cat, amount=Decimal('20000.00'), student_type='ALL'
        )
        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_CLASS, school_class=self.school_class,
            term=self.term, category=cat, amount=Decimal('25000.00'), student_type='ALL'
        )
        result = resolve_prices(self.school, self.school_class, self.term)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].scope, FeePrice.SCOPE_CLASS)
        self.assertEqual(result[0].amount, Decimal('25000.00'))

    def test_scope_class_requires_school_class(self):
        fp = FeePrice(
            school=self.school,
            scope=FeePrice.SCOPE_CLASS,
            school_class=None,
            term=self.term,
            category=FeeCategory.objects.create(
                school=self.school, name='Tuition', billing_cycle='PER_TERM'
            ),
            amount=Decimal('1000.00'),
        )
        with self.assertRaises(Exception):
            fp.full_clean()

    def test_scope_school_wide_must_not_have_school_class(self):
        fp = FeePrice(
            school=self.school,
            scope=FeePrice.SCOPE_SCHOOL_WIDE,
            school_class=self.school_class,
            term=self.term,
            category=FeeCategory.objects.create(
                school=self.school, name='PTA', billing_cycle='ONE_TIME'
            ),
            amount=Decimal('1000.00'),
        )
        with self.assertRaises(Exception):
            fp.full_clean()

    def test_unique_constraint_per_scope(self):
        from django.core.exceptions import ValidationError
        cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL'
        )
        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_SCHOOL_WIDE, school_class=None,
            term=self.term, category=cat, amount=Decimal('1000.00'), student_type='ALL'
        )
        duplicate = FeePrice(
            school=self.school, scope=FeePrice.SCOPE_SCHOOL_WIDE, school_class=None,
            term=self.term, category=cat, amount=Decimal('2000.00'), student_type='ALL'
        )
        with self.assertRaises(ValidationError):
            duplicate.full_clean()


class FeePriceTest(BasePricingTest):
    def test_feeprice_class_scope_creation(self):
        cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL'
        )
        fp = FeePrice.objects.create(
            school=self.school,
            scope=FeePrice.SCOPE_CLASS,
            school_class=self.school_class,
            term=self.term,
            category=cat,
            amount=Decimal('25000.00'),
            student_type='ALL',
        )
        self.assertEqual(fp.scope, FeePrice.SCOPE_CLASS)
        self.assertEqual(fp.school_class, self.school_class)

    def test_feeprice_level_scope_creation(self):
        cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL'
        )
        fp = FeePrice.objects.create(
            school=self.school,
            scope=FeePrice.SCOPE_LEVEL,
            level='JSS',
            term=self.term,
            category=cat,
            amount=Decimal('20000.00'),
            student_type='ALL',
        )
        self.assertEqual(fp.scope, FeePrice.SCOPE_LEVEL)
        self.assertEqual(fp.level, 'JSS')

    def test_feeprice_school_wide_creation(self):
        cat = FeeCategory.objects.create(
            school=self.school, name='PTA', billing_cycle='ONE_TIME', student_type='NEW'
        )
        fp = FeePrice.objects.create(
            school=self.school,
            scope=FeePrice.SCOPE_SCHOOL_WIDE,
            term=None,
            category=cat,
            amount=Decimal('1000.00'),
            student_type='NEW',
        )
        self.assertEqual(fp.scope, FeePrice.SCOPE_SCHOOL_WIDE)
        self.assertIsNone(fp.school_class)
        self.assertEqual(fp.level, '')

    def test_resolve_prices_uses_feeprice_before_feestructure(self):
        cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL'
        )
    def test_resolve_prices_uses_feeprice(self):
        cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL'
        )
        FeePrice.objects.create(
            school=self.school,
            scope=FeePrice.SCOPE_CLASS,
            school_class=self.school_class,
            term=self.term,
            category=cat,
            amount=Decimal('30000.00'),
            student_type='ALL',
        )
        result = resolve_prices(self.school, self.school_class, self.term)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], FeePrice)
        self.assertEqual(result[0].amount, Decimal('30000.00'))

    def test_resolve_prices_empty_when_no_feeprice(self):
        cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL'
        )
        result = resolve_prices(self.school, self.school_class, self.term)
        self.assertEqual(len(result), 0)

    def test_resolve_prices_does_not_include_other_classes(self):
        """Regression test: resolver must not return class-specific prices
        from other classes when resolving for a specific class.
        """
        jss2 = SchoolClass.objects.create(
            school=self.school, name='JSS2', level='JSS',
        )
        cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL'
        )
        FeePrice.objects.create(
            school=self.school,
            scope=FeePrice.SCOPE_CLASS,
            school_class=jss2,
            term=self.term,
            category=cat,
            amount=Decimal('40000.00'),
            student_type='ALL',
        )
        result = resolve_prices(self.school, self.school_class, self.term)
        self.assertEqual(len(result), 0)

    def test_resolve_prices_dedupes_school_wide_with_class(self):
        """When a category has both school-wide and class-specific rows,
        the class-specific one wins (no duplicate from school-wide).
        """
        cat = FeeCategory.objects.create(
            school=self.school, name='PTA', billing_cycle='ONE_TIME', student_type='NEW'
        )
        FeePrice.objects.create(
            school=self.school,
            scope=FeePrice.SCOPE_SCHOOL_WIDE,
            school_class=None,
            term=None,
            category=cat,
            amount=Decimal('1000.00'),
            student_type='NEW',
        )
        FeePrice.objects.create(
            school=self.school,
            scope=FeePrice.SCOPE_CLASS,
            school_class=self.school_class,
            term=None,
            category=cat,
            amount=Decimal('2000.00'),
            student_type='NEW',
        )
        result = resolve_prices(self.school, self.school_class, None, student_type='NEW')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].scope, FeePrice.SCOPE_CLASS)
        self.assertEqual(result[0].amount, Decimal('2000.00'))

    def test_resolve_prices_level_scope(self):
        jss2 = SchoolClass.objects.create(
            school=self.school, name='JSS2A', level='JSS',
        )
        cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL'
        )
        FeePrice.objects.create(
            school=self.school,
            scope=FeePrice.SCOPE_LEVEL,
            level='JSS',
            term=self.term,
            category=cat,
            amount=Decimal('28000.00'),
            student_type='ALL',
        )
        result = resolve_prices(self.school, jss2, self.term)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], FeePrice)
        self.assertEqual(result[0].amount, Decimal('28000.00'))
        self.assertEqual(result[0].level, 'JSS')

    def test_feeprice_effective_date_filtering(self):
        cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL'
        )
        today = timezone.now().date()
        fp_future = FeePrice.objects.create(
            school=self.school,
            scope=FeePrice.SCOPE_CLASS,
            school_class=self.school_class,
            term=self.term,
            category=cat,
            amount=Decimal('35000.00'),
            student_type='ALL',
            effective_from=today + timedelta(days=30),
        )
        cat2 = FeeCategory.objects.create(
            school=self.school, name='Tuition2', billing_cycle='PER_TERM', student_type='ALL'
        )
        fp_past = FeePrice.objects.create(
            school=self.school,
            scope=FeePrice.SCOPE_CLASS,
            school_class=self.school_class,
            term=self.term,
            category=cat2,
            amount=Decimal('25000.00'),
            student_type='ALL',
            effective_to=today - timedelta(days=1),
        )
        result = resolve_prices(self.school, self.school_class, self.term)
        self.assertEqual(len(result), 0)

    def test_feeprice_class_requires_school_class(self):
        fp = FeePrice(
            school=self.school,
            scope=FeePrice.SCOPE_CLASS,
            school_class=None,
            term=self.term,
            category=FeeCategory.objects.create(
                school=self.school, name='Tuition', billing_cycle='PER_TERM'
            ),
            amount=Decimal('1000.00'),
        )
        with self.assertRaises(Exception):
            fp.full_clean()

    def test_feeprice_school_wide_must_not_have_class_or_level(self):
        fp = FeePrice(
            school=self.school,
            scope=FeePrice.SCOPE_SCHOOL_WIDE,
            school_class=self.school_class,
            level='JSS',
            term=self.term,
            category=FeeCategory.objects.create(
                school=self.school, name='PTA', billing_cycle='ONE_TIME'
            ),
            amount=Decimal('1000.00'),
        )
        with self.assertRaises(Exception):
            fp.full_clean()


class FeePriceOverrideTest(BasePricingTest):
    def test_override_takes_precedence_over_feeprice(self):
        cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL'
        )
        FeePrice.objects.create(
            school=self.school,
            scope=FeePrice.SCOPE_CLASS,
            school_class=self.school_class,
            term=self.term,
            category=cat,
            amount=Decimal('30000.00'),
            student_type='ALL',
        )
        today = timezone.now().date()
        FeePriceOverride.objects.create(
            school=self.school,
            student=self.student,
            category=cat,
            amount=Decimal('15000.00'),
            reason='Scholarship',
            valid_from=today - timedelta(days=10),
            valid_to=today + timedelta(days=10),
        )
        result = resolve_price_for_student(self.school, self.student, self.school_class, cat, term=self.term)
        self.assertEqual(result, Decimal('15000.00'))

    def test_override_within_valid_dates_only(self):
        cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL'
        )
        FeePrice.objects.create(
            school=self.school,
            scope=FeePrice.SCOPE_CLASS,
            school_class=self.school_class,
            term=self.term,
            category=cat,
            amount=Decimal('30000.00'),
            student_type='ALL',
        )
        FeePriceOverride.objects.create(
            school=self.school,
            student=self.student,
            category=cat,
            amount=Decimal('15000.00'),
            reason='Scholarship',
            valid_from=self.term.start_date,
            valid_to=self.term.end_date - timedelta(days=1),
        )
        result = resolve_price_for_student(self.school, self.student, self.school_class, cat, term=self.term)
        self.assertEqual(result, Decimal('30000.00'))

    def test_resolve_price_for_student_returns_none_when_no_price(self):
        cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL'
        )
        result = resolve_price_for_student(self.school, self.student, self.school_class, cat, term=self.term)
        self.assertIsNone(result)


class GenerationScopeTest(BasePricingTest):
    """Test scope-aware invoice generation utilities."""

    def setUp(self):
        super().setUp()
        self.cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL'
        )

    def test_generate_invoices_for_level_creates_invoices(self):
        """LEVEL scope creates invoices for all classes with matching level."""
        jss1b = SchoolClass.objects.create(
            school=self.school, name='JSS1B', level='JSS1',
        )
        jss2 = SchoolClass.objects.create(
            school=self.school, name='JSS2', level='JSS',
        )
        Student.objects.create(
            school=self.school,
            user=User.objects.create_user(username='stu2', school=self.school, role=Roles.STUDENT),
            admission_number='STU002', date_of_birth=date(2010, 1, 1), gender='M',
            admission_date=date(2025, 9, 1), status='ACTIVE',
        )
        Student.objects.create(
            school=self.school,
            user=User.objects.create_user(username='stu3', school=self.school, role=Roles.STUDENT),
            admission_number='STU003', date_of_birth=date(2010, 1, 1), gender='M',
            admission_date=date(2025, 9, 1), status='ACTIVE',
        )
        ClassEnrollment.objects.create(
            school=self.school, student=Student.objects.get(admission_number='STU002'),
            school_class=jss1b, session=self.session, is_current=True,
        )
        ClassEnrollment.objects.create(
            school=self.school, student=Student.objects.get(admission_number='STU003'),
            school_class=jss2, session=self.session, is_current=True,
        )

        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_LEVEL, level='JSS1',
            term=self.term, category=self.cat, amount=Decimal('25000.00'), student_type='ALL'
        )

        generated = generate_invoices_for_level(self.school, 'JSS1', self.term)
        self.assertEqual(generated, 2)  # JSS1A and JSS1B

        # JSS2 should not have invoice (different level)
        jss2_invoices = Invoice.objects.filter(student__enrollments__school_class=jss2, term=self.term)
        self.assertEqual(jss2_invoices.count(), 0)

    def test_generate_invoices_school_wide_creates_invoices(self):
        """SCHOOL_WIDE scope creates invoices for all active classes."""
        jss2 = SchoolClass.objects.create(
            school=self.school, name='JSS2', level='JSS',
        )
        Student.objects.create(
            school=self.school,
            user=User.objects.create_user(username='stu2', school=self.school, role=Roles.STUDENT),
            admission_number='STU002', date_of_birth=date(2010, 1, 1), gender='M',
            admission_date=date(2025, 9, 1), status='ACTIVE',
        )
        ClassEnrollment.objects.create(
            school=self.school, student=Student.objects.get(admission_number='STU002'),
            school_class=jss2, session=self.session, is_current=True,
        )

        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_SCHOOL_WIDE, school_class=None,
            term=self.term, category=self.cat, amount=Decimal('20000.00'), student_type='ALL'
        )

        generated = generate_invoices_school_wide(self.school, self.term)
        self.assertEqual(generated, 2)  # JSS1A and JSS2

    def test_sync_level_invoices_reprices_unpaid(self):
        """sync_level_invoices only re-prices unpaid invoices."""
        jss1b = SchoolClass.objects.create(
            school=self.school, name='JSS1B', level='JSS1',
        )
        Student.objects.create(
            school=self.school,
            user=User.objects.create_user(username='stu2', school=self.school, role=Roles.STUDENT),
            admission_number='STU002', date_of_birth=date(2010, 1, 1), gender='M',
            admission_date=date(2025, 9, 1), status='ACTIVE',
        )
        ClassEnrollment.objects.create(
            school=self.school, student=Student.objects.get(admission_number='STU002'),
            school_class=jss1b, session=self.session, is_current=True,
        )

        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_LEVEL, level='JSS1',
            term=self.term, category=self.cat, amount=Decimal('25000.00'), student_type='ALL'
        )

        generate_invoices_for_level(self.school, 'JSS1', self.term)

        # Confirm one payment on JSS1A student's invoice
        invoice1 = Invoice.objects.get(student=self.student, term=self.term)
        from fees.models import Payment
        Payment.objects.create(
            school=self.school, invoice=invoice1, student=self.student,
            amount=Decimal('25000.00'), method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED, paid_on=timezone.now(),
        )

        # Update price
        FeePrice.objects.filter(school=self.school, category=self.cat, term=self.term).update(amount=Decimal('30000.00'))

        # Sync level - should only update unpaid invoice (JSS1B)
        re_priced = sync_level_invoices(self.school, 'JSS1', self.term)
        self.assertEqual(re_priced, 1)

        invoice1.refresh_from_db()
        invoice2 = Invoice.objects.get(student__admission_number='STU002', term=self.term)
        invoice2.refresh_from_db()

        # JSS1A has payment, should keep old amount
        self.assertEqual(invoice1.total_amount, Decimal('25000.00'))
        # JSS1B no payment, should be updated
        self.assertEqual(invoice2.total_amount, Decimal('30000.00'))

    def test_sync_school_wide_invoices_reprices_unpaid(self):
        """sync_school_wide_invoices only re-prices unpaid invoices."""
        jss2 = SchoolClass.objects.create(
            school=self.school, name='JSS2', level='JSS',
        )
        Student.objects.create(
            school=self.school,
            user=User.objects.create_user(username='stu2', school=self.school, role=Roles.STUDENT),
            admission_number='STU002', date_of_birth=date(2010, 1, 1), gender='M',
            admission_date=date(2025, 9, 1), status='ACTIVE',
        )
        ClassEnrollment.objects.create(
            school=self.school, student=Student.objects.get(admission_number='STU002'),
            school_class=jss2, session=self.session, is_current=True,
        )

        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_SCHOOL_WIDE, school_class=None,
            term=self.term, category=self.cat, amount=Decimal('20000.00'), student_type='ALL'
        )

        generate_invoices_school_wide(self.school, self.term)

        # Confirm payment on JSS1A student's invoice
        invoice1 = Invoice.objects.get(student=self.student, term=self.term)
        from fees.models import Payment
        Payment.objects.create(
            school=self.school, invoice=invoice1, student=self.student,
            amount=Decimal('20000.00'), method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED, paid_on=timezone.now(),
        )

        # Update price
        FeePrice.objects.filter(school=self.school, category=self.cat, term=self.term).update(amount=Decimal('25000.00'))

        # Sync school-wide - should only update unpaid invoice (JSS2)
        re_priced = sync_school_wide_invoices(self.school, self.term)
        self.assertEqual(re_priced, 1)

        invoice1.refresh_from_db()
        invoice2 = Invoice.objects.get(student__admission_number='STU002', term=self.term)
        invoice2.refresh_from_db()

        # JSS1A has payment, should keep old amount
        self.assertEqual(invoice1.total_amount, Decimal('20000.00'))
        # JSS2 no payment, should be updated
        self.assertEqual(invoice2.total_amount, Decimal('25000.00'))


class SubScopingResolutionTest(BasePricingTest):
    """Deterministic two-stage precedence for NEW/RETURNING sub-scoping.

    Stage 1: scope (CLASS < LEVEL < SCHOOL_WIDE — most specific wins).
    Stage 2: within the winning scope, target type beats a generic ALL row.
    """

    def _cat(self, name, **kwargs):
        return FeeCategory.objects.create(
            school=self.school, name=name,
            billing_cycle=kwargs.pop('billing_cycle', 'PER_TERM'),
            student_type=kwargs.pop('student_type', 'ALL'),
        )

    def _price(self, category, amount, scope=FeePrice.SCOPE_CLASS, **kwargs):
        return FeePrice.objects.create(
            school=self.school, scope=scope,
            school_class=self.school_class if scope == FeePrice.SCOPE_CLASS else None,
            level=kwargs.pop('level', ''),
            term=kwargs.pop('term', self.term),
            category=category, amount=Decimal(amount), student_type=kwargs.pop('student_type', 'ALL'),
        )

    def test_target_type_beats_all_in_same_scope(self):
        cat = self._cat('Tuition')
        self._price(cat, '40000.00', student_type='ALL')
        self._price(cat, '35000.00', student_type='NEW')
        result = resolve_prices(self.school, self.school_class, self.term, student_type='NEW')
        fp = next(fp for fp in result if fp.category == cat)
        self.assertEqual(fp.amount, Decimal('35000.00'))
        self.assertEqual(fp.student_type, 'NEW')

    def test_returning_type_beats_all_in_same_scope(self):
        cat = self._cat('Tuition')
        self._price(cat, '40000.00', student_type='ALL')
        self._price(cat, '38000.00', student_type='RETURNING')
        result = resolve_prices(self.school, self.school_class, self.term, student_type='RETURNING')
        fp = next(fp for fp in result if fp.category == cat)
        self.assertEqual(fp.amount, Decimal('38000.00'))
        self.assertEqual(fp.student_type, 'RETURNING')

    def test_missing_target_type_falls_back_to_all(self):
        cat = self._cat('Tuition')
        self._price(cat, '40000.00', student_type='ALL')
        result = resolve_prices(self.school, self.school_class, self.term, student_type='NEW')
        fp = next(fp for fp in result if fp.category == cat)
        self.assertEqual(fp.amount, Decimal('40000.00'))

    def test_new_excludes_returning_only_rows(self):
        cat = self._cat('Uniforms')
        self._price(cat, '40000.00', student_type='RETURNING')
        result = resolve_prices(self.school, self.school_class, self.term, student_type='NEW')
        self.assertNotIn(cat, {fp.category for fp in result})

    def test_returning_excludes_new_only_rows(self):
        cat = self._cat('Registration')
        self._price(cat, '5000.00', student_type='NEW')
        result = resolve_prices(self.school, self.school_class, self.term, student_type='RETURNING')
        self.assertNotIn(cat, {fp.category for fp in result})

    def test_scope_wins_over_type_precedence(self):
        """A generic ALL row in a more specific scope beats a NEW-tagged row
        further away, even though type has higher numeric priority."""
        cat = self._cat('Tuition')
        self._price(cat, '30000.00', scope=FeePrice.SCOPE_SCHOOL_WIDE, student_type='NEW')
        self._price(cat, '25000.00', scope=FeePrice.SCOPE_LEVEL, level='JSS1', student_type='ALL')
        result = resolve_prices(self.school, self.school_class, self.term, student_type='NEW')
        fp = next(fp for fp in result if fp.category == cat)
        self.assertEqual(fp.scope, FeePrice.SCOPE_LEVEL)
        self.assertEqual(fp.amount, Decimal('25000.00'))

    def test_agg_scope_aggregate_mode_mixes_types(self):
        """student_type='ALL' is aggregate mode: NEW and RETURNING prices both
        resolve, deterministically (lowest pk per category)."""
        cat = self._cat('Tuition')
        self._price(cat, '35000.00', student_type='NEW')
        self._price(cat, '38000.00', student_type='RETURNING')
        result = resolve_prices(self.school, self.school_class, self.term, student_type='ALL')
        fp = next(fp for fp in result if fp.category == cat)
        self.assertEqual(fp.student_type, 'NEW')
        self.assertEqual(fp.amount, Decimal('35000.00'))

    def test_specific_minus_all_in_aggregate_mode(self):
        """Aggregate mode keeps a single deterministic row per category (ALL
        beats a type-specific sibling on pk order)."""
        cat = self._cat('Uniforms')
        self._price(cat, '40000.00', student_type='ALL')
        self._price(cat, '45000.00', student_type='NEW')
        result = resolve_prices(self.school, self.school_class, self.term, student_type='ALL')
        prices = [fp for fp in result if fp.category == cat]
        self.assertEqual(len(prices), 1)
        self.assertEqual(prices[0].student_type, 'ALL')
        self.assertEqual(prices[0].amount, Decimal('40000.00'))

    def test_resolve_price_for_student_respects_subscoping(self):
        cat = self._cat('Tuition')
        self._price(cat, '40000.00', student_type='ALL')
        self._price(cat, '35000.00', student_type='NEW')
        new_amount = resolve_price_for_student(
            self.school, self.student, self.school_class, cat,
            term=self.term, student_type='NEW',
        )
        self.assertEqual(new_amount, Decimal('35000.00'))
        returning_amount = resolve_price_for_student(
            self.school, self.student, self.school_class, cat,
            term=self.term, student_type='RETURNING',
        )
        self.assertEqual(returning_amount, Decimal('40000.00'))


class ChristmasFeeGateTest(BasePricingTest):
    """The Christmas fee resolves only in the first term of a session."""

    def _cat(self, name, **kwargs):
        return FeeCategory.objects.create(
            school=self.school, name=name,
            billing_cycle=kwargs.pop('billing_cycle', 'PER_TERM'),
            student_type=kwargs.pop('student_type', 'ALL'),
        )

    def _setup_two_terms(self):
        self.term2 = Term.objects.create(
            school=self.school, session=self.session, name='Second Term',
            start_date=date(2026, 1, 1), end_date=date(2026, 3, 31), is_current=False,
        )
        self.christmas = self._cat('Christmas/End of Term Party Fee')
        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_SCHOOL_WIDE, school_class=None,
            term=None, category=self.christmas, amount=Decimal('5000.00'), student_type='ALL',
        )

    def test_christmas_visible_in_first_term(self):
        self._setup_two_terms()
        result = resolve_prices(self.school, self.school_class, self.term, student_type='NEW')
        self.assertIn(self.christmas, {fp.category for fp in result})

    def test_christmas_hidden_in_second_term(self):
        self._setup_two_terms()
        result = resolve_prices(self.school, self.school_class, self.term2, student_type='NEW')
        self.assertNotIn(self.christmas, {fp.category for fp in result})


class NameAndOverpaymentTest(BasePricingTest):
    """display_name plumbing and clamped display_balance."""

    def test_feeprice_display_name_falls_back_to_category(self):
        cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL'
        )
        fp = FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_CLASS, school_class=self.school_class,
            term=self.term, category=cat, amount=Decimal('25000.00'), student_type='ALL',
        )
        self.assertEqual(fp.display_name, 'Tuition')

    def test_feeprice_display_name_uses_custom_name(self):
        cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL'
        )
        fp = FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_CLASS, school_class=self.school_class,
            term=self.term, category=cat, amount=Decimal('25000.00'), student_type='ALL',
            name='Boarders Tuition'
        )
        self.assertEqual(fp.display_name, 'Boarders Tuition')

    def test_generation_line_item_captures_item_name(self):
        cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL'
        )
        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_CLASS, school_class=self.school_class,
            term=self.term, category=cat, amount=Decimal('25000.00'), student_type='ALL',
            name='Boarding Fee'
        )
        from fees.generation import generate_invoice_for_student
        invoice = generate_invoice_for_student(self.student, self.term)
        line = invoice.line_items.get(category=cat)
        self.assertEqual(line.item_name, 'Boarding Fee')
        self.assertEqual(line.display_name, 'Boarding Fee')

    def test_generation_line_item_item_name_falls_back_to_category(self):
        cat = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL'
        )
        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_CLASS, school_class=self.school_class,
            term=self.term, category=cat, amount=Decimal('25000.00'), student_type='ALL',
        )
        from fees.generation import generate_invoice_for_student
        invoice = generate_invoice_for_student(self.student, self.term)
        line = invoice.line_items.get(category=cat)
        self.assertEqual(line.item_name, 'Tuition')
        self.assertEqual(line.display_name, 'Tuition')

    def test_invoice_display_balance_clamps_negative(self):
        invoice = Invoice.objects.create(
            school=self.school, student=self.student, term=self.term,
            total_amount=Decimal('60000.00'),
        )
        from fees.models import Payment
        from django.utils import timezone
        Payment.objects.create(
            school=self.school, invoice=invoice, student=self.student,
            amount=Decimal('65000.00'), method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED, paid_on=timezone.now(),
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.balance, Decimal('-5000.00'))
        self.assertEqual(invoice.display_balance, Decimal('0.00'))

    def test_invoice_display_balance_positive_unchanged(self):
        invoice = Invoice.objects.create(
            school=self.school, student=self.student, term=self.term,
            total_amount=Decimal('60000.00'),
        )
        from fees.models import Payment
        from django.utils import timezone
        Payment.objects.create(
            school=self.school, invoice=invoice, student=self.student,
            amount=Decimal('20000.00'), method=Payment.Method.CASH,
            status=Payment.Status.CONFIRMED, paid_on=timezone.now(),
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.display_balance, Decimal('40000.00'))

