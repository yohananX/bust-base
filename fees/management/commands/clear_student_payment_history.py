from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from students.models import Student
from fees.models import (
    Payment,
    Invoice,
    InvoiceLineItem,
    FeeReceipt,
    PaymentLineItem,
    InvoiceResetLog,
)
from notifications.models import NotificationLog


class Command(BaseCommand):
    help = 'Clear all payment history for a specific student.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            required=True,
            help='User ID of the student (accounts.User PK).',
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        user_id = opts['user_id']
        user = User.objects.filter(pk=user_id, role='STUDENT').first()
        if not user:
            self.stdout.write(self.style.ERROR(f'Student user not found: user_id={user_id}'))
            return

        student = Student.objects.filter(user=user).first()
        if not student:
            self.stdout.write(self.style.ERROR(f'Student profile not found for user_id={user_id}'))
            return

        school = student.school
        self.stdout.write(
            self.style.WARNING(
                f'Target: {user.get_full_name()} (User id={user.id}, Student id={student.id}) at {school}'
            )
        )

        invoices = Invoice.objects.filter(school=school, student=student)
        invoice_ids = list(invoices.values_list('pk', flat=True))

        direct_payments = Payment.objects.filter(school=school, student=student)
        invoice_payments = Payment.objects.filter(school=school, invoice__in=invoice_ids)
        lesson_payments = Payment.objects.filter(
            school=school, lesson_enrollment__student=student
        )
        all_payment_ids = set(
            direct_payments.values_list('pk', flat=True)
        ) | set(invoice_payments.values_list('pk', flat=True)) | set(
            lesson_payments.values_list('pk', flat=True)
        )

        self.stdout.write(f'Invoices found: {invoices.count()}')
        for inv in invoices:
            self.stdout.write(f'  Invoice id={inv.id}, term={inv.term}, total={inv.total_amount}')

        self.stdout.write(f'Payments found: {len(all_payment_ids)}')
        for p in Payment.objects.filter(id__in=all_payment_ids):
            self.stdout.write(
                f'  Payment id={p.id}, amount={p.amount}, status={p.status}, '
                f'method={p.method}, invoice_id={p.invoice_id}, '
                f'lesson_enrollment_id={p.lesson_enrollment_id}'
            )

        # Delete in dependency order
        pli_count = PaymentLineItem.objects.filter(payment_id__in=all_payment_ids).count()
        self.stdout.write(f'PaymentLineItems to delete: {pli_count}')
        PaymentLineItem.objects.filter(payment_id__in=all_payment_ids).delete()

        receipt_count = FeeReceipt.objects.filter(payment_id__in=all_payment_ids).count()
        self.stdout.write(f'FeeReceipts to delete: {receipt_count}')
        FeeReceipt.objects.filter(payment_id__in=all_payment_ids).delete()

        pay_count = Payment.objects.filter(id__in=all_payment_ids).count()
        self.stdout.write(f'Payments to delete: {pay_count}')
        Payment.objects.filter(id__in=all_payment_ids).delete()

        ili_count = InvoiceLineItem.objects.filter(invoice_id__in=invoice_ids).count()
        self.stdout.write(f'InvoiceLineItems to delete: {ili_count}')
        InvoiceLineItem.objects.filter(invoice_id__in=invoice_ids).delete()

        inv_count = Invoice.objects.filter(id__in=invoice_ids).count()
        self.stdout.write(f'Invoices to delete: {inv_count}')
        Invoice.objects.filter(id__in=invoice_ids).delete()

        notif_refs = []
        for p_id in all_payment_ids:
            notif_refs.append(f'payment-confirm:{p_id}')
            notif_refs.append(f'receipt:{p_id}')
        notif_count = NotificationLog.objects.filter(reference__in=notif_refs).count()
        self.stdout.write(f'NotificationLogs to delete: {notif_count}')
        NotificationLog.objects.filter(reference__in=notif_refs).delete()

        InvoiceResetLog.objects.create(
            school=school,
            scope_type=InvoiceResetLog.ResetScope.STUDENT,
            scope_id=student.pk,
            scope_name=f"{user.get_full_name()} (admission {student.admission_number})",
            reason="Manual clearance of entire payment history by request.",
            invoices_deleted=inv_count,
            payments_deleted=pay_count,
            line_items_deleted=ili_count,
            receipts_deleted=receipt_count,
        )

        self.stdout.write(self.style.SUCCESS('Payment history cleared successfully.'))
