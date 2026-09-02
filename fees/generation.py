"""Reusable invoice-generation logic shared by bulk actions and enrollment flows."""
from decimal import Decimal

from core.models import Term
from students.models import ClassEnrollment
from .models import FeeCategory, FeePrice, Invoice, InvoiceLineItem
from .utils import resolve_student_type


def _is_one_time_already_billed(student, category, session):
    """Return True if a ONE_TIME category was already billed to this student in a prior session."""
    if category.billing_cycle != 'ONE_TIME':
        return False
    return InvoiceLineItem.objects.filter(
        invoice__student=student,
        category=category,
        billing_cycle='ONE_TIME',
        invoice__term__session__start_date__lt=session.start_date,
    ).exists()


def effective_fee_structures(school, school_class, term, student_type='ALL', student=None, session=None):
    """Resolve compulsory pricing for a class + term, with inheritance.

    Backward-compat shim that delegates to pricing.resolve_prices.
    Kept for callers that still import this name. The actual resolution
    logic lives in fees.pricing and supports FeePrice + FeePriceOverride
    with school-wide, level, and class scopes.
    """
    from .pricing import resolve_prices
    return resolve_prices(
        school=school,
        school_class=school_class,
        term=term,
        student_type=student_type,
        student=student,
        session=session,
    )


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

    student_type = resolve_student_type(student, term.session)
    fee_structures = effective_fee_structures(
        school, enrollment.school_class, term, student_type=student_type, student=student, session=term.session
    )
    if not fee_structures:
        return None

    line_items = []
    total = Decimal('0.00')
    for fs in fee_structures:
        line_items.append((fs.category, fs.amount, fs.category.billing_cycle))
        total += fs.amount

    invoice = Invoice.objects.create(
        school=school,
        student=student,
        term=term,
        total_amount=total,
    )
    for category, amount, billing_cycle in line_items:
        InvoiceLineItem.objects.create(
            invoice=invoice,
            category=category,
            amount=amount,
            term=term,
            session=term.session,
            billing_cycle=billing_cycle,
        )

    _notify_primary_guardian(student, term, invoice)
    return invoice


def generate_invoice_for_current_term(student):
    """Generate an invoice for the school's current term (if any)."""
    term = Term.objects.filter(school=student.school, is_current=True).first()
    if term is None:
        return None
    return generate_invoice_for_student(student, term)


def generate_invoices_for_class(school_class, term):
    """Backfill term invoices for students currently enrolled in a class
    who have no invoice for the term yet. Returns how many were created.

    Called when pricing is added/changed so students enrolled before the
    price existed still get their invoice.
    """
    from students.models import ClassEnrollment

    generated = 0
    enrollments = ClassEnrollment.objects.filter(
        session=term.session,
        school_class=school_class,
        is_current=True,
    ).select_related('student')
    for enrollment in enrollments:
        student = enrollment.student
        if student.school_id != school_class.school_id:
            continue
        if generate_invoice_for_student(student, term) is not None:
            generated += 1
    return generated


def generate_invoices_for_term(school, term):
    """Generate invoices for every active student enrolled in ``term``.

    Students who already have an invoice for the term, or who have no
    current enrollment in the term's session, are skipped. Returns a
    ``(generated, skipped)`` tuple.

    Canonical bulk entry point — used by the admin portal view and the
    Django admin action.
    """
    from students.models import Student

    students = Student.objects.filter(
        school=school,
        status=Student.ACTIVE,
        enrollments__session=term.session,
        enrollments__is_current=True,
    ).distinct()

    generated = 0
    skipped = 0
    for student in students:
        if generate_invoice_for_student(student, term) is None:
            skipped += 1
        else:
            generated += 1
    return generated, skipped


def sync_class_invoices(school_class, term):
    """Re-price invoices that have no payment history yet.

    Line items and totals are rebuilt from the current compulsory pricing
    for the class/term. Invoices with any payment are left untouched so
    recorded money is never mutated.
    """
    from django.db.models import Count

    from .models import InvoiceLineItem

    invoices = Invoice.objects.filter(
        school=school_class.school,
        term=term,
        student__enrollments__session=term.session,
        student__enrollments__school_class=school_class,
        student__enrollments__is_current=True,
    ).annotate(num_payments=Count('payments')).filter(num_payments=0)

    updated = 0
    for invoice in invoices.distinct():
        student = invoice.student
        student_type = resolve_student_type(student, term.session)
        structures = effective_fee_structures(
            school_class.school, school_class, term, student_type=student_type, student=student, session=term.session
        )
        if not structures:
            continue

        invoice.line_items.all().delete()
        total = Decimal('0.00')
        for fs in structures:
            InvoiceLineItem.objects.create(
                invoice=invoice,
                category=fs.category,
                amount=fs.amount,
                term=term,
                session=term.session,
                billing_cycle=fs.category.billing_cycle,
            )
            total += fs.amount
        invoice.total_amount = total
        invoice.save(update_fields=['total_amount'])
        updated += 1
    return updated


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