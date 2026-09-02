"""Pricing engine for fee structures.

Pure-function interface for resolving applicable prices for a given school,
class, and term.

Phase 0: delegates to existing effective_fee_structures().
Phase 1: includes school_class__isnull=True for SCHOOL_WIDE scope.
Phase 2: queries FeePrice model with 4-level precedence:
    1. CLASS + exact class + term
    2. CLASS + exact class + fallback term
    3. LEVEL + class.level + term
    4. SCHOOL_WIDE + term
Phase 5: removed fallback to FeeStructure (table dropped).
"""
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from .models import FeeCategory, FeePrice, FeePriceOverride


def _is_fee_price_active(price):
    """Check if a FeePrice is active based on effective dates."""
    today = timezone.now().date()
    if price.effective_from and today < price.effective_from:
        return False
    if price.effective_to and today > price.effective_to:
        return False
    return True


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
    """Resolve prices from FeePrice model with 4-level precedence."""
    if not school_class:
        return []

    class_level = school_class.level or ''

    qs = FeePrice.objects.filter(
        school=school,
        category__is_compulsory=True,
        is_active=True,
    )

    if term is not None:
        explicit = list(qs.filter(term=term))
        fallback_candidates = qs.exclude(term=term).order_by('-term__start_date', 'category__name')
    else:
        explicit = list(qs.filter(term__isnull=True))
        fallback_candidates = qs.exclude(term__isnull=True).order_by('-term__start_date', 'category__name')

    if student_type != 'ALL':
        explicit = [fp for fp in explicit if fp.student_type in ('ALL', student_type)]
        fallback_candidates = fallback_candidates.filter(
            Q(student_type='ALL') | Q(student_type=student_type)
        )

    def matches_class(price):
        return price.scope == FeePrice.SCOPE_CLASS and price.school_class_id == school_class.id

    def matches_level(price):
        return price.scope == FeePrice.SCOPE_LEVEL and price.level == class_level

    def matches_school_wide(price):
        return price.scope == FeePrice.SCOPE_SCHOOL_WIDE and not price.school_class_id and not price.level

    def effective(price):
        return _is_fee_price_active(price)

    def precedence(price):
        if matches_class(price):
            return 0
        if matches_level(price):
            return 1
        if matches_school_wide(price):
            return 2
        return 3

    explicit.sort(key=lambda p: (precedence(p), p.category_id))
    deduped_explicit = []
    seen_cats = set()
    for fp in explicit:
        if fp.category_id in seen_cats:
            continue
        if not effective(fp):
            continue
        seen_cats.add(fp.category_id)
        deduped_explicit.append(fp)

    fallbacks = []
    seen = set(seen_cats)
    for fp in fallback_candidates:
        if fp.category_id in seen:
            continue
        if not effective(fp):
            continue
        seen.add(fp.category_id)
        fallbacks.append(fp)

    combined = deduped_explicit + fallbacks

    if student is not None and session is not None:
        filtered = []
        for fp in combined:
            category = fp.category
            if category.billing_cycle == 'ONE_TIME':
                from .generation import _is_one_time_already_billed
                if _is_one_time_already_billed(student, category, session):
                    continue
            filtered.append(fp)
        combined = filtered

    return combined


def resolve_prices(school, school_class, term, student_type='ALL', student=None, session=None):
    """Resolve applicable fee prices for a class + term.

    Phase 5: queries FeePrice model only. FeeStructure has been dropped.
    """
    if school_class is None:
        return []

    return _resolve_from_feeprice(
        school, school_class, term,
        student_type=student_type,
        student=student,
        session=session,
    )


def resolve_price_for_student(school, student, school_class, category, term=None):
    """Resolve the effective price for one student + category.

    Precedence:
    1. Active FeePriceOverride for this student + category
    2. Resolved FeePrice for the student's class + term
    3. None
    """
    override = _get_active_override(school, student, category)
    if override:
        return override.amount

    session = term.session if term else None
    prices = resolve_prices(school, school_class, term, student=student, session=session)
    for price in prices:
        if price.category_id == category.id:
            return price.amount

    return None

