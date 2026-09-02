"""Checkout module for the fees app.

Assembles the checkout cart for one student + term (``get_checkout_options``)
and reconciles a submitted checkout (``reconcile_checkout``).

Business rules:
- ONE invoice per student per term (``unique_together`` on ``Invoice``).
- ``Invoice.total_amount`` is the only stored money field; balance, amount-paid
  and status are computed live from CONFIRMED payments only. PENDING bank
  transfers do NOT reduce the balance until an admin confirms them.
- Line-item additions only ever ADD to ``total_amount``; balance is never
  mutated directly.
- Payments are fully negotiable: a parent selects what to pay for and enters
  any amount up to the total balance; selecting an optional category bills its
  full amount onto the invoice (remainder becomes owed).
- Overpayment policy: NO payment may exceed the outstanding balance of the
  invoices it covers. Every entry point enforces the cap (checkout reconcile,
  the initiate-payment view, admin cash recording) so a balance can never go
  negative; anyone who wants to pay beyond the bill must settle the remaining
  line items instead.
- All money is ``Decimal``.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from .models import FeeCategory, FeeStructure, Invoice, InvoiceLineItem, PaymentLineItem
from .utils import resolve_student_type
from .generation import effective_fee_structures
from core.models import Term
from students.models import ClassEnrollment


def _applicable_fee_structures(school, school_class, term, student_type='ALL'):
    """Return all applicable FeeStructure rows for a class + term.

    Merges:
    - compulsory categories (with fallback pricing from prior terms)
    - optional categories explicitly set for the current term
    """
    compulsory = list(
        effective_fee_structures(school, school_class, term, student_type=student_type)
    )
    optional = FeeStructure.objects.filter(
        school=school,
        school_class__in=[school_class, None],
        term=term,
        category__is_compulsory=False,
    ).select_related('category')
    if student_type != 'ALL':
        optional = optional.filter(
            Q(student_type='ALL') | Q(student_type=student_type)
        )

    seen = {fs.category_id for fs in compulsory}
    combined = list(compulsory)
    for fs in optional:
        if fs.category_id not in seen:
            combined.append(fs)
            seen.add(fs.category_id)
    return combined


def _grouped_extras(term, enrollment, invoice, student, student_type='ALL'):
    """Build extras grouped by FeeCategoryGroup.

    Returns a dict of {group_name: [CheckoutOption, ...]}.
    Categories without a group land under 'Other'.
    """
    raw = _extra_options(term, enrollment, invoice, student, student_type)
    groups = {}
    for opt in raw:
        group_name = 'Other'
        category = FeeCategory.objects.filter(pk=opt.category_id).first()
        if category and category.group_id:
            group_name = category.group.name
        groups.setdefault(group_name, []).append(opt)
    return dict(sorted(groups.items()))


def current_term(school):
    """Return the current ``Term`` for a school (may be None)."""
    return Term.objects.filter(school=school, is_current=True).first()


@dataclass
class CheckoutOption:
    """A single payable option in the checkout cart."""
    key: str                  # 'outstanding' | f'extra:{category_pk}' | f'next:{category_pk}' | f'bundle:{term_id}'
    kind: str                 # 'outstanding' | 'extra' | 'next' | 'bundle'
    label: str                # display text
    amount: Decimal
    flexible: bool            # True only for outstanding
    category_id: int | None   # FeeCategory pk for extra/next, None for outstanding/bundle
    category_name: str
    term_id: int
    term_name: str
    invoice_id: int | None    # existing invoice pk for outstanding, else None
    billed: bool = False      # category already on the term invoice
    settled: bool = False     # True when billed and its invoice is fully paid
    total_amount: Decimal | None = None  # term invoice total (outstanding only)
    paid_amount: Decimal | None = None   # amount already paid (outstanding only)
    bundle_items: list | None = None     # included CheckoutOption rows (bundle only)


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
    bundle: CheckoutOption | None = None
    grouped_extras: dict | None = None  # {group_name: [CheckoutOption, ...]}


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


def _extra_options(term, enrollment, invoice, student, student_type='ALL'):
    """Build 'extra' options from all applicable FeeStructure rows for the term.

    Uses ``_applicable_fee_structures`` so compulsory categories with fallback
    pricing from prior terms are included.

    Billed categories (already on the term invoice) are still included,
    marked ``billed=True`` so the frontend can render them as paid/disabled.
    ``settled`` reflects whether the term invoice is fully paid (so billed
    categories on a partially-paid invoice read as "included", not "paid").
    """
    options = []
    billed = _billed_category_ids(invoice)
    settled = invoice is not None and invoice.balance <= 0
    fee_structures = _applicable_fee_structures(
        student.school, enrollment.school_class, term, student_type=student_type
    )
    for fs in fee_structures:
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
            billed=(fs.category_id in billed),
            settled=settled,
        ))
    options.sort(key=lambda option: option.category_name)
    return options


def _next_term_options(term, enrollment, student, student_type='ALL'):
    """Build 'next' options from all applicable FeeStructure rows for the following term.

    Uses ``_applicable_fee_structures`` so compulsory categories with fallback
    pricing are included.

    Billed categories (already on the next-term invoice, if any) are still
    included, marked ``billed=True``. Returns ``None`` when there is no
    following term, no current enrollment, or no billable categories —
    callers must not render an empty group.
    """
    next_term = Term.objects.filter(
        school=term.school, start_date__gt=term.start_date
    ).order_by('start_date').first()
    if next_term is None or enrollment is None:
        return None

    next_invoice = _invoice_for(student, next_term)
    billed = _billed_category_ids(next_invoice)
    settled = next_invoice is not None and next_invoice.balance <= 0
    fee_structures = _applicable_fee_structures(
        student.school, enrollment.school_class, next_term, student_type=student_type
    )
    options = []
    for fs in fee_structures:
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
            billed=(fs.category_id in billed),
            settled=settled,
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
    - ``extras``: every FeeStructure row for the student's current class +
      ``term``. Categories already billed on the term invoice are flagged
      ``billed=True`` (rendered as paid); the rest stay selectable.
    - ``next_term``: the same for the following term, or ``None`` when there is
      no following term (never an empty/disabled group).
    - ``bundle``: a single option representing the full term fees for the
      student's type (new vs returning), with a breakdown of included items.
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
            total_amount=invoice.total_amount,
            paid_amount=invoice.amount_paid,
        )

    extras = []
    next_term_group = None
    bundle = None
    grouped_extras = None
    enrollment = ClassEnrollment.objects.filter(
        student=student, is_current=True
    ).select_related('school_class').first()
    if enrollment is not None:
        student_type = resolve_student_type(student, term.session)
        extras = _extra_options(term, enrollment, invoice, student, student_type=student_type)
        next_term_group = _next_term_options(term, enrollment, student, student_type=student_type)
        grouped_extras = _grouped_extras(term, enrollment, invoice, student, student_type=student_type)

        # Build the "full term fees" bundle for this student type.
        bundle_items = list(extras)
        bundle_amount = sum((opt.amount for opt in bundle_items), Decimal('0.00'))
        if bundle_items:
            bundle = CheckoutOption(
                key=f'bundle:{term.pk}',
                kind='bundle',
                label=f"{term.name} Full Fees — ₦{bundle_amount:,.2f}",
                amount=bundle_amount,
                flexible=False,
                category_id=None,
                category_name='Full Term Fees',
                term_id=term.pk,
                term_name=term.name,
                invoice_id=None,
                billed=False,
                settled=False,
                bundle_items=bundle_items,
            )

    return CheckoutOptions(
        student_id=student.pk,
        term_id=term.pk,
        term_name=term.name,
        outstanding=outstanding,
        extras=extras,
        next_term=next_term_group,
        bundle=bundle,
        grouped_extras=grouped_extras,
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
    """Parse an option key into (kind, category_pk_or_term_id).

    Returns:
      - ('outstanding', None)
      - ('extra' | 'next', category_pk)
      - ('bundle', term_id)
      - None for unrecognized/malformed keys.
    """
    if key == 'outstanding':
        return ('outstanding', None)
    if key.startswith('bundle:'):
        _, _, raw_term_id = key.partition(':')
        try:
            return ('bundle', int(raw_term_id))
        except ValueError:
            return None
    if key.startswith('extra:') or key.startswith('next:'):
        kind, _, raw_pk = key.partition(':')
        try:
            return (kind, int(raw_pk))
        except ValueError:
            return None
    return None


def _resolve_fee_structure(student, enrollment, term, category_pk, student_type='ALL'):
    """Look up the FeeStructure row for a category within a term + class."""
    if enrollment is None:
        return None
    for fs in _applicable_fee_structures(
        student.school, enrollment.school_class, term, student_type=student_type
    ):
        if fs.category_id == category_pk:
            return fs
    return None


def _bundle_fee_structures(student, enrollment, term, student_type='ALL'):
    """Return all applicable FeeStructure rows for a student type in a term."""
    if enrollment is None:
        return []
    return _applicable_fee_structures(
        student.school, enrollment.school_class, term, student_type=student_type
    )


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
    if amount <= 0:
        raise ValidationError('Enter an amount greater than 0.')

    involves_outstanding = 'outstanding' in keys
    extra_keys = [k for k in keys if k.startswith('extra:')]
    next_keys = [k for k in keys if k.startswith('next:')]
    bundle_keys = [k for k in keys if k.startswith('bundle:')]

    if not involves_outstanding and not extra_keys and not next_keys and not bundle_keys:
        raise ValidationError('Select at least one item to pay for.')

    next_term = None
    if next_keys:
        next_term = Term.objects.filter(
            school=term.school, start_date__gt=term.start_date
        ).order_by('start_date').first()
        if next_term is None:
            raise ValidationError('Selected next-term items are no longer available.')

    enrollment = None
    if extra_keys or next_keys or bundle_keys:
        enrollment = ClassEnrollment.objects.filter(
            student=student, is_current=True
        ).select_related('school_class').first()

    student_type = resolve_student_type(student, term.session)

    extra_fee_structures = []
    for key in extra_keys:
        parsed = _parse_key(key)
        if parsed is None:
            continue
        _, category_pk = parsed
        fs = _resolve_fee_structure(student, enrollment, term, category_pk, student_type=student_type)
        if fs is not None:
            extra_fee_structures.append(fs)

    next_fee_structures = []
    for key in next_keys:
        parsed = _parse_key(key)
        if parsed is None:
            continue
        _, category_pk = parsed
        fs = _resolve_fee_structure(student, enrollment, next_term, category_pk, student_type=student_type)
        if fs is not None:
            next_fee_structures.append(fs)

    bundle_fee_structures = []
    for key in bundle_keys:
        parsed = _parse_key(key)
        if parsed is None:
            continue
        kind, raw_term_id = parsed
        if kind != 'bundle':
            continue
        try:
            bundle_term = Term.objects.get(school=term.school, pk=raw_term_id)
        except Term.DoesNotExist:
            continue
        for fs in _bundle_fee_structures(student, enrollment, bundle_term, student_type=student_type):
            if fs not in bundle_fee_structures:
                bundle_fee_structures.append(fs)

    with transaction.atomic():
        current_invoice = None
        if involves_outstanding:
            current_invoice = Invoice.objects.filter(
                school=student.school, student=student, term=term
            ).first()
            if current_invoice is None or current_invoice.balance <= 0:
                raise ValidationError(f'No outstanding balance for {term.name}.')
        elif extra_keys or bundle_keys:
            current_invoice, _ = Invoice.objects.get_or_create(
                school=student.school,
                student=student,
                term=term,
                defaults={'total_amount': Decimal('0.00')},
            )

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

        if current_invoice is not None and bundle_fee_structures:
            for fs in bundle_fee_structures:
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

        next_invoice = None
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

        invoices = []
        if current_invoice is not None:
            invoices.append(current_invoice)
        if next_invoice is not None:
            invoices.append(next_invoice)

        if not invoices:
            raise ValidationError('Select at least one item to pay for.')

        total_balance = sum(i.balance for i in invoices)
        if amount > total_balance:
            raise ValidationError(
                f'Amount must be at most ₦{total_balance:,.2f}.'
            )

        if len(invoices) == 1:
            allocations = [Allocation(invoices[0], amount)]
        else:
            current_inv, next_inv = invoices
            current_share = (
                amount * current_inv.balance / total_balance
            ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if current_share > current_inv.balance:
                current_share = current_inv.balance
            next_share = amount - current_share
            if next_share > next_inv.balance:
                next_share = next_inv.balance
                current_share = amount - next_share
            allocations = [
                Allocation(current_inv, current_share),
                Allocation(next_inv, next_share),
            ]

    return ReconcileResult(
        invoices=invoices,
        allocations=allocations,
        minimum_payable=Decimal('0.00'),
        total_balance=total_balance,
        is_split=len(invoices) == 2,
    )


def get_selected_items(student, term, selected_keys):
    """Resolve selected checkout keys to item detail dicts.

    Returns a list of dicts with keys:
    kind, label, amount, source_key, category, term, session, invoice
    """
    keys = list(selected_keys or [])
    if not keys:
        return []

    involves_outstanding = 'outstanding' in keys
    extra_keys = [k for k in keys if k.startswith('extra:')]
    next_keys = [k for k in keys if k.startswith('next:')]
    bundle_keys = [k for k in keys if k.startswith('bundle:')]

    next_term = None
    if next_keys:
        next_term = Term.objects.filter(
            school=term.school, start_date__gt=term.start_date
        ).order_by('start_date').first()

    enrollment = None
    if extra_keys or next_keys or bundle_keys:
        enrollment = ClassEnrollment.objects.filter(
            student=student, is_current=True
        ).select_related('school_class').first()

    student_type = resolve_student_type(student, term.session)

    items = []
    current_invoice = _invoice_for(student, term)

    if involves_outstanding and current_invoice is not None and current_invoice.balance > 0:
        items.append({
            'kind': PaymentLineItem.KIND_OUTSTANDING,
            'label': f"Outstanding: {term.name}",
            'amount': current_invoice.balance,
            'source_key': 'outstanding',
            'category': None,
            'term': term,
            'session': term.session,
            'invoice': current_invoice,
        })

    for key in extra_keys:
        parsed = _parse_key(key)
        if parsed is None:
            continue
        _, category_pk = parsed
        fs = _resolve_fee_structure(student, enrollment, term, category_pk, student_type=student_type)
        if fs is not None:
            items.append({
                'kind': PaymentLineItem.KIND_EXTRA,
                'label': fs.category.name,
                'amount': fs.amount,
                'source_key': key,
                'category': fs.category,
                'term': term,
                'session': term.session,
                'invoice': current_invoice,
            })

    for key in next_keys:
        parsed = _parse_key(key)
        if parsed is None:
            continue
        _, category_pk = parsed
        fs = _resolve_fee_structure(student, enrollment, next_term, category_pk, student_type=student_type)
        if fs is not None:
            items.append({
                'kind': PaymentLineItem.KIND_NEXT,
                'label': fs.category.name,
                'amount': fs.amount,
                'source_key': key,
                'category': fs.category,
                'term': next_term,
                'session': next_term.session if next_term else None,
                'invoice': _invoice_for(student, next_term),
            })

    for key in bundle_keys:
        parsed = _parse_key(key)
        if parsed is None:
            continue
        kind, raw_term_id = parsed
        if kind != 'bundle':
            continue
        try:
            bundle_term = Term.objects.get(school=term.school, pk=raw_term_id)
        except Term.DoesNotExist:
            continue
        for fs in _bundle_fee_structures(student, enrollment, bundle_term, student_type=student_type):
            items.append({
                'kind': PaymentLineItem.KIND_EXTRA,
                'label': fs.category.name,
                'amount': fs.amount,
                'source_key': key,
                'category': fs.category,
                'term': bundle_term,
                'session': bundle_term.session,
                'invoice': _invoice_for(student, bundle_term),
            })

    return items
