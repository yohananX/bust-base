"""Checkout module for the fees app.

Assembles the checkout cart for one student + term (``get_checkout_options``)
and reconciles a submitted checkout (``reconcile_checkout``).

Business rules:
- ONE invoice per student per term (``unique_together`` on ``Invoice``).
- ``Invoice.total_amount`` is the only stored money field; balance, amount-paid
  and status are computed live from CONFIRMED payments only.
- Line-item additions only ever ADD to ``total_amount``; balance is never
  mutated directly.
- All money is ``Decimal``.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import FeeStructure, Invoice, InvoiceLineItem
from core.models import Term
from students.models import ClassEnrollment


def current_term(school):
    """Return the current ``Term`` for a school (may be None)."""
    return Term.objects.filter(school=school, is_current=True).first()


@dataclass
class CheckoutOption:
    """A single payable option in the checkout cart."""
    key: str                  # 'outstanding' | f'extra:{category_pk}' | f'next:{category_pk}'
    kind: str                 # 'outstanding' | 'extra' | 'next'
    label: str                # display text
    amount: Decimal
    flexible: bool            # True only for outstanding
    category_id: int | None   # FeeCategory pk for extra/next, None for outstanding
    category_name: str
    term_id: int
    term_name: str
    invoice_id: int | None    # existing invoice pk for outstanding, else None


@dataclass
class NextTermGroup:
    """Group of next-term checkout options."""
    term_id: int
    term_name: str
    options: list[CheckoutOption]


@dataclass
class CheckoutOptions:
    """The assembled cart for one student + term."""
    student_id: int
    term_id: int
    term_name: str
    outstanding: CheckoutOption | None
    extras: list[CheckoutOption]
    next_term: NextTermGroup | None


def _invoice_for(student, term):
    """Return the existing invoice for a student + term, or None."""
    return Invoice.objects.filter(
        school=student.school, student=student, term=term
    ).first()


def _billed_category_ids(invoice):
    """Return the set of category pks already billed on an invoice (or empty)."""
    if invoice is None:
        return set()
    return set(invoice.line_items.values_list('category_id', flat=True))


def _extra_options(term, enrollment, invoice, student):
    """Build 'extra' options from FeeStructure rows not yet billed this term."""
    options = []
    billed = _billed_category_ids(invoice)
    fee_structures = FeeStructure.objects.filter(
        school=student.school,
        school_class=enrollment.school_class,
        term=term,
    ).select_related('category')
    for fs in fee_structures:
        if fs.category_id in billed:
            continue
        options.append(CheckoutOption(
            key=f'extra:{fs.category_id}',
            kind='extra',
            label=f"{fs.category.name} — ₦{fs.amount:,.2f}",
            amount=fs.amount,
            flexible=False,
            category_id=fs.category_id,
            category_name=fs.category.name,
            term_id=term.pk,
            term_name=term.name,
            invoice_id=None,
        ))
    options.sort(key=lambda option: option.category_name)
    return options


def _next_term_options(term, enrollment, student):
    """Build 'next' options from FeeStructure rows for the following term.

    Returns ``None`` when there is no following term, no current enrollment,
    or no billable categories — callers must not render an empty group.
    """
    next_term = Term.objects.filter(
        school=term.school, start_date__gt=term.start_date
    ).order_by('start_date').first()
    if next_term is None or enrollment is None:
        return None

    billed = _billed_category_ids(_invoice_for(student, next_term))
    options = []
    fee_structures = FeeStructure.objects.filter(
        school=student.school,
        school_class=enrollment.school_class,
        term=next_term,
    ).select_related('category')
    for fs in fee_structures:
        if fs.category_id in billed:
            continue
        options.append(CheckoutOption(
            key=f'next:{fs.category_id}',
            kind='next',
            label=f"{fs.category.name} — ₦{fs.amount:,.2f}",
            amount=fs.amount,
            flexible=False,
            category_id=fs.category_id,
            category_name=fs.category.name,
            term_id=next_term.pk,
            term_name=next_term.name,
            invoice_id=None,
        ))
    options.sort(key=lambda option: option.category_name)

    if not options:
        return None
    return NextTermGroup(
        term_id=next_term.pk,
        term_name=next_term.name,
        options=options,
    )


def get_checkout_options(student, term) -> CheckoutOptions:
    """Assemble the cart for one student + term.

    - ``outstanding``: the student's existing invoice for ``term`` when its
      computed balance is positive.
    - ``extras``: FeeStructure rows for the student's current class + ``term``
      whose category is not already represented on the term invoice.
    - ``next_term``: the same for the following term, or ``None`` when there is
      no following term (never an empty/disabled group).
    """
    invoice = _invoice_for(student, term)

    outstanding = None
    if invoice is not None and invoice.balance > 0:
        outstanding = CheckoutOption(
            key='outstanding',
            kind='outstanding',
            label=f"Outstanding: {term.name} — ₦{invoice.balance:,.2f}",
            amount=invoice.balance,
            flexible=True,
            category_id=None,
            category_name='Outstanding Fees',
            term_id=term.pk,
            term_name=term.name,
            invoice_id=invoice.pk,
        )

    extras = []
    next_term_group = None
    enrollment = ClassEnrollment.objects.filter(
        student=student, is_current=True
    ).select_related('school_class').first()
    if enrollment is not None:
        extras = _extra_options(term, enrollment, invoice, student)
        next_term_group = _next_term_options(term, enrollment, student)

    return CheckoutOptions(
        student_id=student.pk,
        term_id=term.pk,
        term_name=term.name,
        outstanding=outstanding,
        extras=extras,
        next_term=next_term_group,
    )


@dataclass
class Allocation:
    """One invoice's share of the entered payment."""
    invoice: object   # fees.models.Invoice instance
    amount: Decimal   # this invoice's share of the payment


@dataclass
class ReconcileResult:
    """Outcome of reconciling a submitted checkout."""
    invoices: list          # 1 or 2 Invoice instances
    allocations: list       # list[Allocation], sum of amounts == entered amount
    minimum_payable: Decimal
    total_balance: Decimal  # sum of involved invoices' balance AFTER additions
    is_split: bool          # True when two invoices involved


def _parse_key(key):
    """Parse an option key into (kind, category_pk).

    Returns ``('outstanding', None)`` for the outstanding key,
    ``('extra' | 'next', category_pk)`` for fee keys, and ``None`` for
    anything unrecognized or malformed.
    """
    if key == 'outstanding':
        return ('outstanding', None)
    if key.startswith('extra:') or key.startswith('next:'):
        kind, _, raw_pk = key.partition(':')
        try:
            return (kind, int(raw_pk))
        except ValueError:
            return None
    return None


def _resolve_fee_structure(student, enrollment, term, category_pk):
    """Look up the FeeStructure row for a category within a term + class."""
    if enrollment is None:
        return None
    return FeeStructure.objects.filter(
        school=student.school,
        school_class=enrollment.school_class,
        term=term,
        category_id=category_pk,
    ).first()


def reconcile_checkout(student, term, selected_keys, amount) -> ReconcileResult:
    """Reconcile a submitted checkout.

    Raises ``ValidationError(str)`` on invalid amounts or impossible
    selections. Mutations (invoice creation, line-item addition, total_amount
    increments) are atomic and idempotent — an already-billed category is never
    double-billed.
    """
    keys = list(selected_keys or [])
    try:
        amount = Decimal(amount)
    except (TypeError, ValueError, InvalidOperation):
        raise ValidationError('Enter a valid amount.')

    involves_outstanding = 'outstanding' in keys
    extra_keys = [k for k in keys if k.startswith('extra:')]
    next_keys = [k for k in keys if k.startswith('next:')]

    if not involves_outstanding and not extra_keys and not next_keys:
        raise ValidationError('Select at least one item to pay for.')

    next_term = None
    if next_keys:
        next_term = Term.objects.filter(
            school=term.school, start_date__gt=term.start_date
        ).order_by('start_date').first()
        if next_term is None:
            raise ValidationError('Selected next-term items are no longer available.')

    enrollment = None
    if extra_keys or next_keys:
        enrollment = ClassEnrollment.objects.filter(
            student=student, is_current=True
        ).select_related('school_class').first()

    extra_fee_structures = []
    for key in extra_keys:
        parsed = _parse_key(key)
        if parsed is None:
            continue
        _, category_pk = parsed
        fs = _resolve_fee_structure(student, enrollment, term, category_pk)
        if fs is not None:
            extra_fee_structures.append(fs)

    next_fee_structures = []
    for key in next_keys:
        parsed = _parse_key(key)
        if parsed is None:
            continue
        _, category_pk = parsed
        fs = _resolve_fee_structure(student, enrollment, next_term, category_pk)
        if fs is not None:
            next_fee_structures.append(fs)

    with transaction.atomic():
        current_invoice = None
        if involves_outstanding:
            current_invoice = Invoice.objects.filter(
                school=student.school, student=student, term=term
            ).first()
            if current_invoice is None or current_invoice.balance <= 0:
                raise ValidationError(f'No outstanding balance for {term.name}.')
        elif extra_keys:
            current_invoice, _ = Invoice.objects.get_or_create(
                school=student.school,
                student=student,
                term=term,
                defaults={'total_amount': Decimal('0.00')},
            )

        extras_fixed = Decimal('0.00')
        if current_invoice is not None and extra_fee_structures:
            for fs in extra_fee_structures:
                already_billed = current_invoice.line_items.filter(
                    category_id=fs.category_id
                ).exists()
                if not already_billed:
                    InvoiceLineItem.objects.create(
                        invoice=current_invoice,
                        category_id=fs.category_id,
                        amount=fs.amount,
                    )
                    current_invoice.total_amount = current_invoice.total_amount + fs.amount
                    current_invoice.save(update_fields=['total_amount'])
                extras_fixed += fs.amount

        next_invoice = None
        next_fixed = Decimal('0.00')
        if next_keys and next_term is not None:
            next_invoice, _ = Invoice.objects.get_or_create(
                school=student.school,
                student=student,
                term=next_term,
                defaults={'total_amount': Decimal('0.00')},
            )
            for fs in next_fee_structures:
                already_billed = next_invoice.line_items.filter(
                    category_id=fs.category_id
                ).exists()
                if not already_billed:
                    InvoiceLineItem.objects.create(
                        invoice=next_invoice,
                        category_id=fs.category_id,
                        amount=fs.amount,
                    )
                    next_invoice.total_amount = next_invoice.total_amount + fs.amount
                    next_invoice.save(update_fields=['total_amount'])
                next_fixed += fs.amount

        minimum_payable = extras_fixed + next_fixed

        if amount < minimum_payable:
            raise ValidationError(
                f'Amount must be at least ₦{minimum_payable:,.2f} '
                '(extras and next-term fees cannot be reduced).'
            )

        invoices = []
        if current_invoice is not None:
            invoices.append(current_invoice)
        if next_invoice is not None:
            invoices.append(next_invoice)

        if current_invoice is not None and next_invoice is not None:
            # Two invoices: next-term share is fixed, the rest lands on the
            # current-term invoice, capped by its balance AFTER additions.
            current_portion = amount - next_fixed
            if current_portion < extras_fixed:
                raise ValidationError(
                    f'Amount must be at least ₦{minimum_payable:,.2f} '
                    '(extras and next-term fees cannot be reduced).'
                )
            if current_portion > current_invoice.balance:
                raise ValidationError(
                    f'Amount must be at most ₦{current_invoice.balance:,.2f} '
                    f'for {term.name}.'
                )
            allocations = [
                Allocation(current_invoice, current_portion),
                Allocation(next_invoice, next_fixed),
            ]
        else:
            # One invoice involved (current-term or next-term only): the whole
            # amount lands on it, capped by its balance AFTER additions.
            target_invoice = current_invoice if current_invoice is not None else next_invoice
            if amount > target_invoice.balance:
                raise ValidationError(
                    f'Amount must be at most ₦{target_invoice.balance:,.2f} '
                    f'for {target_invoice.term.name}.'
                )
            allocations = [Allocation(target_invoice, amount)]

    return ReconcileResult(
        invoices=invoices,
        allocations=allocations,
        minimum_payable=minimum_payable,
        total_balance=sum(i.balance for i in invoices),
        is_split=len(invoices) == 2,
    )
