"""Invoice reset service.

Provides atomic, audited deletion of payment records for:
- A single term
- A single class within a term
- A single student within a term
- An entire school (all terms)

Only superadmins may call these methods.
"""
from django.db import transaction
from django.db.models import Count

from .models import Invoice, InvoiceLineItem, Payment, PaymentLineItem, FeeReceipt, InvoiceResetLog


class InvoiceResetService:
    @staticmethod
    def reset_term(school, term, user=None, reason=''):
        """Delete all invoices, payments, line items, receipts for a term."""
        with transaction.atomic():
            invoices = Invoice.objects.filter(school=school, term=term)
            invoice_ids = list(invoices.values_list('pk', flat=True))
            payments = Payment.objects.filter(school=school, invoice__term=term)
            payment_ids = list(payments.values_list('pk', flat=True))

            line_items_count = InvoiceLineItem.objects.filter(invoice__in=invoice_ids).count()
            receipts_count = FeeReceipt.objects.filter(payment__in=payment_ids).count()

            log = InvoiceResetLog.objects.create(
                school=school,
                scope_type=InvoiceResetLog.ResetScope.TERM,
                scope_id=term.pk,
                scope_name=str(term),
                reset_by=user,
                reason=reason,
                invoices_deleted=invoices.count(),
                payments_deleted=payments.count(),
                line_items_deleted=line_items_count,
                receipts_deleted=receipts_count,
            )

            PaymentLineItem.objects.filter(payment__in=payment_ids).delete()
            payments.delete()
            InvoiceLineItem.objects.filter(invoice__in=invoice_ids).delete()
            invoices.delete()

            return log

    @staticmethod
    def reset_class(school, school_class, term, user=None, reason=''):
        """Delete invoices for students currently enrolled in a class for a term."""
        from students.models import ClassEnrollment

        with transaction.atomic():
            enrollments = ClassEnrollment.objects.filter(
                school=school,
                session=term.session,
                school_class=school_class,
                is_current=True,
            ).select_related('student')
            student_ids = [e.student_id for e in enrollments]

            invoices = Invoice.objects.filter(
                school=school,
                term=term,
                student_id__in=student_ids,
            )
            invoice_ids = list(invoices.values_list('pk', flat=True))
            payments = Payment.objects.filter(school=school, invoice__term=term, invoice__student_id__in=student_ids)
            payment_ids = list(payments.values_list('pk', flat=True))

            line_items_count = InvoiceLineItem.objects.filter(invoice__in=invoice_ids).count()
            receipts_count = FeeReceipt.objects.filter(payment__in=payment_ids).count()

            log = InvoiceResetLog.objects.create(
                school=school,
                scope_type=InvoiceResetLog.ResetScope.CLASS,
                scope_id=school_class.pk,
                scope_name=str(school_class),
                reset_by=user,
                reason=reason,
                invoices_deleted=invoices.count(),
                payments_deleted=payments.count(),
                line_items_deleted=line_items_count,
                receipts_deleted=receipts_count,
            )

            PaymentLineItem.objects.filter(payment__in=payment_ids).delete()
            payments.delete()
            InvoiceLineItem.objects.filter(invoice__in=invoice_ids).delete()
            invoices.delete()

            return log

    @staticmethod
    def reset_student(school, student, term, user=None, reason=''):
        """Reset a single student's invoice for a term."""
        with transaction.atomic():
            invoice = Invoice.objects.filter(school=school, student=student, term=term).first()
            if invoice is None:
                return InvoiceResetLog.objects.create(
                    school=school,
                    scope_type=InvoiceResetLog.ResetScope.STUDENT,
                    scope_id=student.pk,
                    scope_name=str(student),
                    reset_by=user,
                    reason=reason,
                    invoices_deleted=0,
                    payments_deleted=0,
                    line_items_deleted=0,
                    receipts_deleted=0,
                )

            payments = Payment.objects.filter(school=school, invoice=invoice)
            payment_ids = list(payments.values_list('pk', flat=True))
            line_items_count = invoice.line_items.count()
            receipts_count = FeeReceipt.objects.filter(payment__in=payment_ids).count()

            log = InvoiceResetLog.objects.create(
                school=school,
                scope_type=InvoiceResetLog.ResetScope.STUDENT,
                scope_id=student.pk,
                scope_name=str(student),
                reset_by=user,
                reason=reason,
                invoices_deleted=1,
                payments_deleted=payments.count(),
                line_items_deleted=line_items_count,
                receipts_deleted=receipts_count,
            )

            PaymentLineItem.objects.filter(payment__in=payment_ids).delete()
            payments.delete()
            invoice.line_items.all().delete()
            invoice.delete()

            return log

    @staticmethod
    def reset_school(school, user=None, reason='', force=False):
        """Delete ALL invoices, payments, line items, receipts for a school.

        ``force`` is required to prevent accidental mass deletion.
        """
        if not force:
            raise ValueError('force=True is required for school-wide resets.')

        with transaction.atomic():
            invoices = Invoice.objects.filter(school=school)
            invoice_ids = list(invoices.values_list('pk', flat=True))
            payments = Payment.objects.filter(school=school)
            payment_ids = list(payments.values_list('pk', flat=True))

            line_items_count = InvoiceLineItem.objects.filter(invoice__in=invoice_ids).count()
            receipts_count = FeeReceipt.objects.filter(payment__in=payment_ids).count()

            log = InvoiceResetLog.objects.create(
                school=school,
                scope_type=InvoiceResetLog.ResetScope.SCHOOL,
                scope_id=school.pk,
                scope_name=school.name,
                reset_by=user,
                reason=reason,
                invoices_deleted=invoices.count(),
                payments_deleted=payments.count(),
                line_items_deleted=line_items_count,
                receipts_deleted=receipts_count,
            )

            PaymentLineItem.objects.filter(payment__in=payment_ids).delete()
            payments.delete()
            InvoiceLineItem.objects.filter(invoice__in=invoice_ids).delete()
            invoices.delete()

            return log
