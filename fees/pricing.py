"""Pricing engine for fee structures.

Pure-function interface for resolving applicable prices for a given school,
class, term, and student type.

Resolution is deterministic (two-stage precedence, ties broken by `pk`):

1. Scope precedence — most specific wins per category:
   ``CLASS`` < ``LEVEL`` < ``SCHOOL_WIDE``.
2. Student-type precedence within the same scope (target mode only):
   a price for the exact requested type wins over a price for ``ALL``.

``student_type`` semantics:

- ``'NEW'`` / ``'RETURNING'`` — target mode: only rows for the exact type
  or ``ALL`` are eligible.
- ``'ALL'`` — aggregate mode: every row is eligible regardless of type
  (used for dashboards and checkout previews before a type is chosen).
"""
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from core.models import Term
from .models import FeeCategory, FeePrice, FeePriceOverride

STUDENT_TYPE_ALL = 'ALL'
CHRISTMAS_FEE = 'Christmas/End of Term Party Fee'

_SCOPE_PRECEDENCE = {
    FeePrice.SCOPE_CLASS: 0,
    FeePrice.SCOPE_LEVEL: 1,
    FeePrice.SCOPE_SCHOOL_WIDE: 2,
}


def _is_fee_price_active(price):
    """Check if a FeePrice is active based on effective dates."""
    today = timezone.now().date()
    if price.effective_from and today < price.effective_from:
        return False
    if price.effective_to and today > price.effective_to:
        return False
    return True


def _is_applicable(price, school_class, class_level):
    """Return whether a price's scope matches the given class/level."""
    if price.scope == FeePrice.SCOPE_CLASS and price.school_class_id == school_class.id:
        return True
    if price.scope == FeePrice.SCOPE_LEVEL and price.level == class_level:
        return True
    if price.scope == FeePrice.SCOPE_SCHOOL_WIDE and not price.school_class_id and not price.level:
        return True
    return False


def _student_type_precedence(price, student_type):
    """Stage-2 key: the exact requested type wins over ALL within a scope."""
    if student_type != STUDENT_TYPE_ALL:
        return 0 if price.student_type == student_type else 1
    return 0


def _primary_sort_key(price, student_type):
    """Order candidates so the winner per category is the first encountered."""
    return (
        _SCOPE_PRECEDENCE.get(price.scope, 99),
        _student_type_precedence(price, student_type),
        price.pk,
    )


def _is_first_term_of_session(school, term):
    """Return True when ``term`` is the first term in its session.

    The Christmas/End of Term Party Fee is only billed in the first term of
    a session; generation and display agree because this gate lives in the
    resolver.
    """
    if term is None or term.session_id is None:
        return False
    first_term = (
        Term.objects.filter(school=school, session=term.session)
        .order_by('start_date', 'id')
        .first()
    )
    return first_term is not None and first_term.id == term.id


def _get_active_override(school, student, category):
    """Get active student-level override for a category, if any."""
    if not student:
        return None

    today = timezone.now().date()
    return FeePriceOverride.objects.filter(
        school=school,
        student=student,
        category=category,
        is_active=True,
        valid_from__lte=today,
        valid_to__gte=today,
    ).first()


def _resolve_from_feeprice(school, school_class, term, student_type='ALL', student=None, session=None):
    """Resolve prices from FeePrice model with the two-stage precedence."""
    if not school_class:
        return []

    class_level = school_class.level or ''

    base_qs = FeePrice.objects.filter(
        school=school,
        is_active=True,
        category__is_compulsory=True,
    )
    if student_type != STUDENT_TYPE_ALL:
        base_qs = base_qs.filter(
            Q(student_type=STUDENT_TYPE_ALL) | Q(student_type=student_type)
        )

    def is_applicable(price):
        return _is_applicable(price, school_class, class_level)

    if term is not None:
        explicit = list(base_qs.filter(term=term))
        fallback_candidates = list(base_qs.exclude(term=term))
    else:
        explicit = list(base_qs.filter(term__isnull=True))
        fallback_candidates = list(base_qs.exclude(term__isnull=True))

    # Stage 1 + Stage 2: most specific scope first, exact type before ALL,
    # then lowest pk. First candidate per category wins.
    deduped = []
    seen_cats = set()
    ordered = sorted(
        (fp for fp in explicit if is_applicable(fp) and _is_fee_price_active(fp)),
        key=lambda fp: _primary_sort_key(fp, student_type),
    )
    for fp in ordered:
        if fp.category_id in seen_cats:
            continue
        seen_cats.add(fp.category_id)
        deduped.append(fp)

    def fallback_sort_key(fp):
        # Most recent term first; term-less fallbacks sort first (matches
        # Postgres DESC NULLS FIRST). Within a term, re-apply scope and
        # type precedence, then name, then pk.
        term_key = fp.term.start_date.toordinal() if fp.term else 10 ** 9
        return (
            -term_key,
            _SCOPE_PRECEDENCE.get(fp.scope, 99),
            _student_type_precedence(fp, student_type),
            fp.category.name,
            fp.pk,
        )

    fallbacks = []
    seen = set(deduped and {fp.category_id for fp in deduped} or set())
    fallback_candidates.sort(key=fallback_sort_key)
    for fp in fallback_candidates:
        if fp.category_id in seen:
            continue
        if not _is_fee_price_active(fp):
            continue
        if not is_applicable(fp):
            continue
        seen.add(fp.category_id)
        fallbacks.append(fp)

    combined = deduped + fallbacks

    if student is not None and session is not None:
        from .generation import _is_one_time_already_billed

        filtered = []
        for fp in combined:
            category = fp.category
            if category.billing_cycle == 'ONE_TIME':
                if _is_one_time_already_billed(student, category, session):
                    continue
            filtered.append(fp)
        combined = filtered

    combined = _apply_christmas_fee_gate(school, term, combined)

    return combined


def _apply_christmas_fee_gate(school, term, prices):
    """Drop the Christmas/End of Term Party Fee outside the first term."""
    christmas_present = any(fp.category.name == CHRISTMAS_FEE for fp in prices)
    if not christmas_present:
        return prices
    if _is_first_term_of_session(school, term):
        return prices
    return [fp for fp in prices if fp.category.name != CHRISTMAS_FEE]


def resolve_prices(school, school_class, term, student_type='ALL', student=None, session=None):
    """Resolve applicable fee prices for a class + term.

    Queries the FeePrice model only (FeeStructure has been dropped).
    """
    if school_class is None:
        return []

    return _resolve_from_feeprice(
        school, school_class, term,
        student_type=student_type,
        student=student,
        session=session,
    )


def resolve_price_for_student(school, student, school_class, category, term=None, student_type=None):
    """Resolve the effective price for one student + category.

    Precedence:
    1. Active FeePriceOverride for this student + category
    2. Resolved FeePrice for the student's class + term (type-aware)
    3. None
    """
    override = _get_active_override(school, student, category)
    if override:
        return override.amount

    session = term.session if term else None
    if student_type is None:
        from .utils import resolve_student_type

        student_type = resolve_student_type(student, session, term)
    prices = resolve_prices(
        school, school_class, term,
        student_type=student_type,
        student=student,
        session=session,
    )
    for price in prices:
        if price.category_id == category.id:
            return price.amount

    return None