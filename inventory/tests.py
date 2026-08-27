from decimal import Decimal
from datetime import date

from django.test import TestCase
from django.urls import reverse
from django.db import IntegrityError
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.auth import get_user_model

from core.models import School, AcademicSession, Term
from accounts.models import Roles, User
from students.models import SchoolClass, Student, ClassEnrollment
from fees.models import FeeCategory, Payment
from inventory.models import (
    InventoryItem, FeeCategoryInventoryItem, InventoryProcurement,
    InventoryTransaction, BookPurchase
)
from inventory.services import add_procurement


User = get_user_model()


class BaseInventoryTest(TestCase):
    def setUp(self):
        self.school = School.objects.create(
            name='Test School', short_code='test',
        )
        self.session = AcademicSession.objects.create(
            school=self.school, name='2025/2026',
            start_date=date(2025, 9, 1), end_date=date(2026, 8, 31),
            is_current=True,
        )
        self.term = Term.objects.create(
            school=self.school, session=self.session, name='First Term',
            start_date=date(2025, 9, 1), end_date=date(2025, 12, 15),
            is_current=True,
        )
        self.school_class = SchoolClass.objects.create(
            school=self.school, name='JSS1A', level='JSS1',
        )
        self.student_user = User.objects.create_user(
            username='student1', email='stu@test.com', password='testpass123',
            school=self.school, role=Roles.STUDENT, first_name='John', last_name='Doe',
        )
        self.student = Student.objects.create(
            school=self.school, user=self.student_user,
            admission_number='STU001', date_of_birth=date(2010, 1, 1),
            gender=Student.MALE, admission_date=date(2025, 9, 1),
        )
        ClassEnrollment.objects.create(
            school=self.school, student=self.student,
            school_class=self.school_class, session=self.session, is_current=True,
        )
        self.admin_user = User.objects.create_user(
            username='admin1', email='admin@test.com', password='testpass123',
            school=self.school, role=Roles.ADMIN, first_name='Admin', last_name='User',
        )
        self.fee_category = FeeCategory.objects.create(
            school=self.school, name='Books',
        )


class InventoryItemModelTest(BaseInventoryTest):
    def test_creation(self):
        item = InventoryItem.objects.create(
            school=self.school, name='Math Book',
            school_class=self.school_class, unit_price=Decimal('2500.00'),
        )
        self.assertEqual(str(item), 'Math Book (JSS1A)')
        self.assertEqual(item.available_stock, 0)

    def test_unique_together(self):
        InventoryItem.objects.create(
            school=self.school, name='Math Book',
            school_class=self.school_class, unit_price=Decimal('2500.00'),
        )
        with self.assertRaises(IntegrityError):
            InventoryItem.objects.create(
                school=self.school, name='Math Book',
                school_class=self.school_class, unit_price=Decimal('3000.00'),
            )

    def test_available_stock_with_reserved(self):
        item = InventoryItem.objects.create(
            school=self.school, name='Math Book',
            school_class=self.school_class,
            total_stock=10, unit_price=Decimal('2500.00'),
        )
        item._reserved = 3
        self.assertEqual(item.available_stock, 7)

    def test_negative_stock_raises_validation_error(self):
        item = InventoryItem(
            school=self.school, name='Test',
            school_class=self.school_class,
            total_stock=-1, unit_price=Decimal('100.00'),
        )
        with self.assertRaises(ValidationError):
            item.full_clean()


class FeeCategoryInventoryItemTest(BaseInventoryTest):
    def test_link_creation(self):
        item = InventoryItem.objects.create(
            school=self.school, name='Math Book',
            school_class=self.school_class, unit_price=Decimal('2500.00'),
        )
        link = FeeCategoryInventoryItem.objects.create(
            fee_category=self.fee_category, inventory_item=item,
        )
        self.assertIn('Books', str(link))
        self.assertIn('Math Book', str(link))

    def test_cross_school_link_raises_validation_error(self):
        other_school = School.objects.create(name='Other', short_code='other')
        other_class = SchoolClass.objects.create(
            school=other_school, name='JSS1A', level='JSS1',
        )
        other_item = InventoryItem.objects.create(
            school=other_school, name='Other Book',
            school_class=other_class, unit_price=Decimal('2500.00'),
        )
        link = FeeCategoryInventoryItem(
            fee_category=self.fee_category, inventory_item=other_item,
        )
        with self.assertRaises(ValidationError):
            link.full_clean()


class InventoryProcurementTest(BaseInventoryTest):
    def test_procurement_increases_stock(self):
        item = InventoryItem.objects.create(
            school=self.school, name='Math Book',
            school_class=self.school_class,
            total_stock=5, unit_price=Decimal('2500.00'),
        )

        add_procurement(
            item=item,
            quantity=20,
            purchased_by=self.admin_user,
            unit_cost=Decimal('2000.00'),
            procurement_date=date(2025, 9, 1),
        )

        item.refresh_from_db()
        self.assertEqual(item.total_stock, 25)

        tx = InventoryTransaction.objects.first()
        self.assertEqual(tx.transaction_type, InventoryTransaction.TransactionType.PROCUREMENT)
        self.assertEqual(tx.quantity_change, 20)
        self.assertEqual(tx.balance_after, 25)

    def test_procurement_creates_transaction(self):
        item = InventoryItem.objects.create(
            school=self.school, name='Math Book',
            school_class=self.school_class,
            total_stock=0, unit_price=Decimal('2500.00'),
        )

        add_procurement(
            item=item,
            quantity=10,
            purchased_by=self.admin_user,
            unit_cost=Decimal('2000.00'),
            procurement_date=date(2025, 9, 1),
        )

        self.assertEqual(InventoryTransaction.objects.count(), 1)
        tx = InventoryTransaction.objects.first()
        self.assertEqual(tx.item, item)
        self.assertEqual(tx.balance_after, 10)


class InventoryTransactionTest(BaseInventoryTest):
    def test_all_transaction_types(self):
        item = InventoryItem.objects.create(
            school=self.school, name='Math Book',
            school_class=self.school_class,
            total_stock=10, unit_price=Decimal('2500.00'),
        )

        InventoryTransaction.objects.create(
            school=self.school, item=item,
            transaction_type=InventoryTransaction.TransactionType.PROCUREMENT,
            quantity_change=10, balance_after=20,
            created_by=self.admin_user,
        )

        InventoryTransaction.objects.create(
            school=self.school, item=item,
            transaction_type=InventoryTransaction.TransactionType.SALE,
            quantity_change=-2, balance_after=18,
            reference='payment:1', created_by=self.admin_user,
        )

        InventoryTransaction.objects.create(
            school=self.school, item=item,
            transaction_type=InventoryTransaction.TransactionType.REFUND,
            quantity_change=2, balance_after=20,
            reference='refund:1', created_by=self.admin_user,
        )

        InventoryTransaction.objects.create(
            school=self.school, item=item,
            transaction_type=InventoryTransaction.TransactionType.ADJUSTMENT,
            quantity_change=-1, balance_after=19,
            notes='Damaged', created_by=self.admin_user,
        )

        self.assertEqual(InventoryTransaction.objects.count(), 4)


class BookPurchaseModelTest(BaseInventoryTest):
    def test_status_lifecycle(self):
        payment = Payment.objects.create(
            school=self.school, invoice=None, student=self.student,
            amount=Decimal('5000.00'), method=Payment.Method.PAYSTACK,
            reference='BOOK_001', status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )
        item = InventoryItem.objects.create(
            school=self.school, name='Math Book',
            school_class=self.school_class, unit_price=Decimal('2500.00'),
        )

        bp = BookPurchase.objects.create(
            school=self.school, payment=payment, student=self.student,
            item=item, quantity=2, unit_price=Decimal('2500.00'),
            total_price=Decimal('5000.00'),
        )
        self.assertEqual(bp.status, BookPurchase.Status.PENDING)

        bp.status = BookPurchase.Status.CONFIRMED
        bp.confirmed_at = timezone.now()
        bp.save(update_fields=['status', 'confirmed_at'])

        bp.refresh_from_db()
        self.assertEqual(bp.status, BookPurchase.Status.CONFIRMED)
        self.assertIsNotNone(bp.confirmed_at)

    def test_total_price_calculation(self):
        payment = Payment.objects.create(
            school=self.school, invoice=None, student=self.student,
            amount=Decimal('5000.00'), method=Payment.Method.PAYSTACK,
            reference='BOOK_002', status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )
        item = InventoryItem.objects.create(
            school=self.school, name='Math Book',
            school_class=self.school_class, unit_price=Decimal('2500.00'),
        )

        bp = BookPurchase.objects.create(
            school=self.school, payment=payment, student=self.student,
            item=item, quantity=2, unit_price=Decimal('2500.00'),
            total_price=Decimal('5000.00'),
        )
        self.assertEqual(bp.total_price, Decimal('5000.00'))

    def test_total_price_validation(self):
        payment = Payment.objects.create(
            school=self.school, invoice=None, student=self.student,
            amount=Decimal('5000.00'), method=Payment.Method.PAYSTACK,
            reference='BOOK_003', status=Payment.Status.PENDING,
            paid_on=timezone.now(),
        )
        item = InventoryItem.objects.create(
            school=self.school, name='Math Book',
            school_class=self.school_class, unit_price=Decimal('2500.00'),
        )

        bp = BookPurchase(
            school=self.school, payment=payment, student=self.student,
            item=item, quantity=2, unit_price=Decimal('2500.00'),
            total_price=Decimal('9999.00'),
        )
        with self.assertRaises(ValidationError):
            bp.full_clean()


class CrossSchoolIsolationTest(BaseInventoryTest):
    def test_two_schools_with_same_data_dont_leak(self):
        school2 = School.objects.create(name='Second', short_code='second')
        class2 = SchoolClass.objects.create(
            school=school2, name='JSS1A', level='JSS1',
        )

        item1 = InventoryItem.objects.create(
            school=self.school, name='Math Book',
            school_class=self.school_class, unit_price=Decimal('2500.00'),
        )
        item2 = InventoryItem.objects.create(
            school=school2, name='Math Book',
            school_class=class2, unit_price=Decimal('3000.00'),
        )

        self.assertEqual(InventoryItem.objects.filter(school=self.school).count(), 1)
        self.assertEqual(InventoryItem.objects.filter(school=school2).count(), 1)

        self.assertEqual(
            InventoryItem.objects.get(school=self.school, name='Math Book').unit_price,
            Decimal('2500.00'),
        )
        self.assertEqual(
            InventoryItem.objects.get(school=school2, name='Math Book').unit_price,
            Decimal('3000.00'),
        )


class DecimalCheckTest(BaseInventoryTest):
    def test_no_float_in_inventory_app(self):
        import os

        inventory_dir = os.path.join(os.path.dirname(__file__))
        skip_files = {'tests.py'}
        skip_dirs = {'migrations', '__pycache__'}
        for root, dirs, files in os.walk(inventory_dir):
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
                    if 'float' in stripped.lower():
                        self.fail(
                            f'FLOAT USAGE FOUND: {filename}:{i}: {stripped}'
                        )
