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


def _delete_with_log(*, school, scope_type, scope_id, scope_name, invoices_qs, payments_qs, user=None, reason=''):
    """Common delete + audit-log path for invoice resets.

    Counts line items and receipts before deletion, writes an
    ``InvoiceResetLog``, then deletes in dependency order:
    ``PaymentLineItem`` → ``Payment`` → ``InvoiceLineItem`` → ``Invoice``.
    """
    invoice_ids = list(invoices_qs.values_list('pk', flat=True))
    payment_ids = list(payments_qs.values_list('pk', flat=True))

    line_items_count = InvoiceLineItem.objects.filter(invoice__in=invoice_ids).count()
    receipts_count = FeeReceipt.objects.filter(payment__in=payment_ids).count()

    log = InvoiceResetLog.objects.create(
        school=school,
        scope_type=scope_type,
        scope_id=scope_id,
        scope_name=scope_name,
        reset_by=user,
        reason=reason,
        invoices_deleted=invoices_qs.count(),
        payments_deleted=payments_qs.count(),
        line_items_deleted=line_items_count,
        receipts_deleted=receipts_count,
    )

    with transaction.atomic():
        PaymentLineItem.objects.filter(payment__in=payment_ids).delete()
        payments_qs.delete()
        InvoiceLineItem.objects.filter(invoice__in=invoice_ids).delete()
        invoices_qs.delete()

    return log


class InvoiceResetService:
    @staticmethod
    def reset_term(school, term, user=None, reason=''):
        """Delete all invoices, payments, line items, receipts for a term."""
        invoices = Invoice.objects.filter(school=school, term=term)
        payments = Payment.objects.filter(school=school, invoice__term=term)
        return _delete_with_log(
            school=school,
            scope_type=InvoiceResetLog.ResetScope.TERM,
            scope_id=term.pk,
            scope_name=str(term),
            invoices_qs=invoices,
            payments_qs=payments,
            user=user,
            reason=reason,
        )

    @staticmethod
    def reset_class(school, school_class, term, user=None, reason=''):
        """Delete invoices for students currently enrolled in a class for a term."""
        from students.models import ClassEnrollment

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
        payments = Payment.objects.filter(school=school, invoice__term=term, invoice__student_id__in=student_ids)
        return _delete_with_log(
            school=school,
            scope_type=InvoiceResetLog.ResetScope.CLASS,
            scope_id=school_class.pk,
            scope_name=str(school_class),
            invoices_qs=invoices,
            payments_qs=payments,
            user=user,
            reason=reason,
        )

    @staticmethod
    def reset_student(school, student, term, user=None, reason=''):
        """Reset a single student's invoice for a term."""
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
        return _delete_with_log(
            school=school,
            scope_type=InvoiceResetLog.ResetScope.STUDENT,
            scope_id=student.pk,
            scope_name=str(student),
            invoices_qs=Invoice.objects.filter(pk=invoice.pk),
            payments_qs=payments,
            user=user,
            reason=reason,
        )

    @staticmethod
    def reset_school(school, user=None, reason='', force=False):
        """Delete ALL invoices, payments, line items, receipts for a school.

        ``force`` is required to prevent accidental mass deletion.
        """
        if not force:
            raise ValueError('force=True is required for school-wide resets.')

        invoices = Invoice.objects.filter(school=school)
        payments = Payment.objects.filter(school=school)
        return _delete_with_log(
            school=school,
            scope_type=InvoiceResetLog.ResetScope.SCHOOL,
            scope_id=school.pk,
            scope_name=school.name,
            invoices_qs=invoices,
            payments_qs=payments,
            user=user,
            reason=reason,
        )
