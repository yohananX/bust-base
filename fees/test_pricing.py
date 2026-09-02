from decimal import Decimal
from datetime import date
from datetime import timedelta

from django.test import TestCase
from django.db import IntegrityError
from django.utils import timezone

from core.models import School, AcademicSession, Term
from students.models import SchoolClass, Student, ClassEnrollment
from accounts.models import Roles, User
from fees.models import FeeCategory, FeeStructure, FeePrice, FeePriceOverride
from fees.pricing import resolve_prices, resolve_price_for_student


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

