"""Fee accuracy and validation layer.

Provides validators for:
- Invoice integrity (totals match line items, compulsory coverage)
- FeeStructure validity (positive amounts, no duplicates)
- One-time fee rebill guards
"""
from decimal import Decimal

from django.db.models import Q, Sum

from .models import (
    FeeCategory,
    FeeStructure,
    FeeValidationError,
    Invoice,
    InvoiceLineItem,
)


class InvoiceIntegrityValidator:
    """Validate structural integrity of an invoice."""

    @staticmethod
    def validate_invoice_totals(invoice: Invoice) -> list[dict]:
        """Ensure invoice.total_amount == sum(line_items)."""
        computed = invoice.line_items.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        errors = []
        if invoice.total_amount != computed:
            errors.append({
                'code': FeeValidationError.ErrorCode.MISMATCHED_TOTAL,
                'message': (
                    f'Invoice total {invoice.total_amount} does not match '
                    f'sum of line items {computed}.'
                ),
            })
        return errors

    @staticmethod
    def validate_compulsory_coverage(invoice: Invoice) -> list[dict]:
        """Ensure all compulsory categories for the class+term+student_type are present."""
        from students.models import ClassEnrollment
        from fees.utils import resolve_student_type

        student = invoice.student
        term = invoice.term
        enrollment = ClassEnrollment.objects.filter(
            student=student, session=term.session, is_current=True
        ).first()
        if not enrollment:
            return []

        student_type = resolve_student_type(student, term.session)
        required_categories = FeeCategory.objects.filter(
            school=invoice.school,
            is_compulsory=True,
            student_type__in=['ALL', student_type],
        ).values_list('pk', flat=True)

        billed_categories = set(
            invoice.line_items.values_list('category_id', flat=True)
        )
        missing = set(required_categories) - billed_categories
        errors = []
        if missing:
            names = list(
                FeeCategory.objects.filter(pk__in=missing).values_list('name', flat=True)
            )
            errors.append({
                'code': FeeValidationError.ErrorCode.MISSING_COMPULSORY,
                'message': f'Missing compulsory categories: {", ".join(names)}',
            })
        return errors

    @staticmethod
    def validate_no_one_time_rebill(student, category, session) -> list[dict]:
        """Ensure a ONE_TIME fee was never billed to this student in a prior session."""
        if category.billing_cycle != FeeCategory.ONE_TIME:
            return []

        exists = InvoiceLineItem.objects.filter(
            invoice__student=student,
            category=category,
            billing_cycle=FeeCategory.ONE_TIME,
            invoice__term__session__start_date__lt=session.start_date,
        ).exists()
        errors = []
        if exists:
            errors.append({
                'code': FeeValidationError.ErrorCode.ONE_TIME_REBILL,
                'message': (
                    f'One-time fee "{category.name}" was already billed to '
                    f'{student} in a prior session.'
                ),
            })
        return errors

    @classmethod
    def validate_invoice(cls, invoice: Invoice) -> list[FeeValidationError]:
        """Run all invoice validations and persist errors."""
        errors = []
        errors.extend(cls.validate_invoice_totals(invoice))
        errors.extend(cls.validate_compulsory_coverage(invoice))

        saved = []
        for err in errors:
            obj = FeeValidationError.objects.create(
                school=invoice.school,
                code=err['code'],
                message=err['message'],
                related_object_type='Invoice',
                related_object_id=invoice.pk,
            )
            saved.append(obj)
        return saved


class FeeStructureValidator:
    """Validate individual fee structures."""

    @staticmethod
    def validate_structure(fs: FeeStructure) -> list[dict]:
        """Validate amount > 0, no duplicates, valid student_type."""
        errors = []
        if fs.amount <= Decimal('0.00'):
            errors.append({
                'code': FeeValidationError.ErrorCode.NEGATIVE_AMOUNT,
                'message': f'FeeStructure amount must be greater than 0 (got {fs.amount}).',
            })

        duplicate = FeeStructure.objects.filter(
            school=fs.school,
            school_class=fs.school_class,
            term=fs.term,
            category=fs.category,
            student_type=fs.student_type,
        ).exclude(pk=fs.pk).exists()
        if duplicate:
            errors.append({
                'code': FeeValidationError.ErrorCode.DUPLICATE_STRUCTURE,
                'message': (
                    f'Duplicate FeeStructure for {fs.category.name} / '
                    f'{fs.school_class} / {fs.term or "One-time"} / {fs.student_type}.'
                ),
            })

        valid_types = [c[0] for c in FeeCategory.STUDENT_TYPE_CHOICES]
        if fs.student_type not in valid_types:
            errors.append({
                'code': FeeValidationError.ErrorCode.INVALID_STUDENT_TYPE,
                'message': f'Invalid student_type "{fs.student_type}".',
            })
        return errors

    @classmethod
    def validate_and_log(cls, fs: FeeStructure) -> list[FeeValidationError]:
        """Validate and persist errors."""
        errors = cls.validate_structure(fs)
        saved = []
        for err in errors:
            obj = FeeValidationError.objects.create(
                school=fs.school,
                code=err['code'],
                message=err['message'],
                related_object_type='FeeStructure',
                related_object_id=fs.pk,
            )
            saved.append(obj)
        return saved
