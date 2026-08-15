"""Reusable invoice-generation logic shared by bulk actions and enrollment flows."""
from decimal import Decimal

from core.models import Term
from students.models import ClassEnrollment
from .models import FeeStructure, Invoice, InvoiceLineItem


def generate_invoice_for_student(student, term):
    """Create a term invoice for one student from their current compulsory fees.

    Returns the created ``Invoice``, or ``None`` when skipped:
    - student has no current enrollment in the term's session,
    - the class/term has no compulsory fee structures,
    - an invoice for the student + term already exists (unique constraint).
    """
    school = student.school

    if Invoice.objects.filter(school=school, student=student, term=term).exists():
        return None

    enrollment = ClassEnrollment.objects.filter(
        student=student, session=term.session, is_current=True
    ).first()
    if not enrollment:
        return None

    fee_structures = FeeStructure.objects.filter(
        school=school,
        school_class=enrollment.school_class,
        term=term,
        category__is_compulsory=True,
    )
    if not fee_structures.exists():
        return None

    line_items = []
    total = Decimal('0.00')
    for fs in fee_structures:
        line_items.append((fs.category, fs.amount))
        total += fs.amount

    invoice = Invoice.objects.create(
        school=school,
        student=student,
        term=term,
        total_amount=total,
    )
    for category, amount in line_items:
        InvoiceLineItem.objects.create(
            invoice=invoice,
            category=category,
            amount=amount,
        )

    _notify_primary_guardian(student, term, invoice)
    return invoice


def generate_invoice_for_current_term(student):
    """Generate an invoice for the school's current term (if any)."""
    term = Term.objects.filter(school=student.school, is_current=True).first()
    if term is None:
        return None
    return generate_invoice_for_student(student, term)


def _notify_primary_guardian(student, term, invoice):
    guardian_link = student.guardian_links.filter(
        is_primary_contact=True
    ).first()
    if not guardian_link:
        return
    from notifications.utils import notify
    notify(
        recipient=guardian_link.guardian,
        channel='EMAIL',
        subject='New invoice for {first} {last}'.format(
            first=student.user.first_name,
            last=student.user.last_name,
        ),
        message=(
            'A new invoice for {term} has been generated. '
            'Amount: NGN{amount}'
        ).format(term=term.name, amount=invoice.total_amount),
        reference='invoice:{}'.format(invoice.id),
    )