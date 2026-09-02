"""End-to-end tests for the redesigned payment recording flow."""
import json
from decimal import Decimal
from datetime import date

from django.test import TestCase, Client
from django.urls import reverse

from core.models import School, AcademicSession, Term
from students.models import SchoolClass, Student, ClassEnrollment
from accounts.models import Roles, User
from fees.models import (
    FeeCategory, FeePrice, Invoice, InvoiceLineItem,
    Payment, PaymentLineItem,
)


class PaymentRecordingFlowTest(TestCase):
    """End-to-end tests for student record payment flow."""

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
            school=self.school, name='JSS1', level='JSS',
        )
        self.admin_user = User.objects.create_user(
            username='admin', school=self.school, role=Roles.ADMIN,
        )
        self.admin_user.set_password('test')
        self.admin_user.save()
        self.client = Client()
        self.client.login(username='admin', password='test')

        self.student = Student.objects.create(
            school=self.school,
            user=User.objects.create_user(
                username='stu1', school=self.school, role=Roles.STUDENT
            ),
            admission_number='STU001',
            date_of_birth=date(2010, 1, 1), gender='M',
            admission_date=date(2025, 9, 1), status='ACTIVE',
        )
        ClassEnrollment.objects.create(
            school=self.school, student=self.student,
            school_class=self.school_class, session=self.session, is_current=True,
        )

        self.tuition = FeeCategory.objects.create(
            school=self.school, name='Tuition', billing_cycle='PER_TERM', student_type='ALL',
        )
        self.uniform = FeeCategory.objects.create(
            school=self.school, name='Uniforms', billing_cycle='ONE_TIME', student_type='NEW',
        )
        self.pta = FeeCategory.objects.create(
            school=self.school, name='PTA', billing_cycle='ONE_TIME', student_type='NEW',
        )

        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_CLASS,
            school_class=self.school_class, term=self.term,
            category=self.tuition, amount=Decimal('30000.00'), student_type='ALL',
        )
        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_SCHOOL_WIDE,
            school_class=None, term=None,
            category=self.uniform, amount=Decimal('10000.00'), student_type='NEW',
        )
        FeePrice.objects.create(
            school=self.school, scope=FeePrice.SCOPE_SCHOOL_WIDE,
            school_class=None, term=None,
            category=self.pta, amount=Decimal('2000.00'), student_type='NEW',
        )

    def test_line_items_api_returns_all_fees_for_class(self):
        url = reverse('fees:api-student-line-items', kwargs={'student_id': self.student.pk})
        response = self.client.get(url, {'scope': 'total'}, HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Tuition', content)
        self.assertIn('Uniforms', content)
        self.assertIn('PTA', content)
        self.assertIn('select-all-fees', content)
        self.assertIn('42000', content)

    def test_line_items_api_invoice_scope(self):
        invoice = Invoice.objects.create(
            school=self.school, student=self.student, term=self.term,
            total_amount=Decimal('30000.00'),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice, category=self.tuition, amount=Decimal('30000.00'),
            term=self.term, session=self.session, billing_cycle='PER_TERM',
        )
        url = reverse('fees:api-student-line-items', kwargs={'student_id': self.student.pk})
        response = self.client.get(
            url, {'scope': f'invoice:{invoice.pk}'}, HTTP_HX_REQUEST='true'
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Tuition', content)
        self.assertNotIn('Uniforms', content)
    def test_line_items_api_none_scope(self):
        url = reverse('fees:api-student-line-items', kwargs={'student_id': self.student.pk})
        response = self.client.get(url, {'scope': 'none'}, HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Free-form payment', content)

    def test_record_payment_class_total_with_specific_items(self):
        url = reverse('school_admin:student_record_payment', kwargs={'pk': self.student.pk})
        data = {
            'scope_select': 'total',
            'selected_line_items': [
                f'price:{FeePrice.objects.get(category=self.uniform).pk}',
                f'price:{FeePrice.objects.get(category=self.pta).pk}',
            ],
            'amount': '12000.00',
            'method': 'CASH',
            'paid_by_name': 'Father',
            'paid_by_relation': 'Father',
            'description': 'Uniforms + PTA',
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        payment = Payment.objects.filter(student=self.student).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.amount, Decimal('12000.00'))
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)
        self.assertIsNone(payment.invoice)
        items = PaymentLineItem.objects.filter(payment=payment)
        self.assertEqual(items.count(), 2)
        labels = {item.label for item in items}
        self.assertEqual(labels, {'Uniforms', 'PTA'})

    def test_record_payment_single_fee(self):
        url = reverse('school_admin:student_record_payment', kwargs={'pk': self.student.pk})
        data = {
            'scope_select': 'total',
            'selected_line_items': [
                f'price:{FeePrice.objects.get(category=self.tuition).pk}',
            ],
            'amount': '30000.00',
            'method': 'BANK_TRANSFER',
            'reference': 'TXN12345',
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        payment = Payment.objects.filter(student=self.student).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.amount, Decimal('30000.00'))
        self.assertEqual(payment.reference, 'TXN12345')

    def test_record_payment_none_scope(self):
        url = reverse('school_admin:student_record_payment', kwargs={'pk': self.student.pk})
        data = {
            'scope_select': 'none',
            'amount': '500.00',
            'method': 'CASH',
            'description': 'Donation',
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        payment = Payment.objects.filter(student=self.student).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.amount, Decimal('500.00'))
        self.assertIsNone(payment.invoice)
        self.assertEqual(PaymentLineItem.objects.filter(payment=payment).count(), 0)

    def test_record_payment_invoice_linked(self):
        invoice = Invoice.objects.create(
            school=self.school, student=self.student, term=self.term,
            total_amount=Decimal('30000.00'),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice, category=self.tuition, amount=Decimal('30000.00'),
            term=self.term, session=self.session, billing_cycle='PER_TERM',
        )
        url = reverse('school_admin:student_record_payment', kwargs={'pk': self.student.pk})
        data = {
            'scope_select': f'invoice:{invoice.pk}',
            'selected_line_items': [f'invoice:{InvoiceLineItem.objects.get(invoice=invoice).pk}'],
            'amount': '30000.00',
            'method': 'CASH',
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        payment = Payment.objects.filter(student=self.student).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.invoice, invoice)
        self.assertEqual(PaymentLineItem.objects.filter(payment=payment).count(), 1)

    def test_one_time_fee_disabled_when_already_paid(self):
        prior_session = AcademicSession.objects.create(
            school=self.school, name='2024/2025',
            start_date=date(2024, 9, 1), end_date=date(2025, 8, 31), is_current=False,
        )
        prior_term = Term.objects.create(
            school=self.school, session=prior_session, name='First Term',
            start_date=date(2024, 9, 1), end_date=date(2024, 12, 15), is_current=False,
        )
        prior_invoice = Invoice.objects.create(
            school=self.school, student=self.student, term=prior_term,
            total_amount=Decimal('10000.00'),
        )
        InvoiceLineItem.objects.create(
            invoice=prior_invoice, category=self.uniform, amount=Decimal('10000.00'),
            term=prior_term, session=prior_session, billing_cycle='ONE_TIME',
        )
        url = reverse('fees:api-student-line-items', kwargs={'student_id': self.student.pk})
        response = self.client.get(url, {'scope': 'total'}, HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Tuition', content)
        self.assertIn('PTA', content)
        self.assertNotIn('Uniforms', content)
