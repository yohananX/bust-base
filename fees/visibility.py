"""Visibility and default-selection rules for fee categories in student portals."""

from decimal import Decimal

from core.models import Term


ONBOARDING_TOTAL_CATEGORIES = {
    'Tuition Fee', 'Registration Form', 'Uniforms', 'PTA',
    'File Jacket', 'Maintenance', 'Examination Fee',
}
RETURNING_HIDDEN_CATEGORIES = {
    'Registration Form', 'PTA', 'File Jacket', 'Maintenance', 'Examination Fee',
}
CHRISTMAS_FEE = 'Christmas/End of Term Party Fee'


def is_category_visible(category, student_type, term, school):
    """Return whether a fee category should be shown for a student type/term."""
    if student_type == 'RETURNING' and category.name in RETURNING_HIDDEN_CATEGORIES:
        return False
    if category.name == CHRISTMAS_FEE and not _is_first_term_of_session(school, term.session):
        return False
    return True


def is_default_checked(category, student_type, already_paid):
    """Return whether a category should be pre-selected in the checkout UI."""
    if already_paid:
        return False
    if student_type == 'NEW':
        return category.name in ONBOARDING_TOTAL_CATEGORIES
    return category.name == 'Tuition Fee'


def is_onboarding_total(category):
    """Return whether a category contributes to the 'Full Package' pseudo-item."""
    return category.name in ONBOARDING_TOTAL_CATEGORIES


def is_onboarding_total_by_name(category_name):
    """Return whether a category name contributes to the 'Full Package' pseudo-item."""
    return category_name in ONBOARDING_TOTAL_CATEGORIES


def _is_first_term_of_session(school, session):
    """Return True when the current term is the first term in its session."""
    first_term = Term.objects.filter(
        school=school, session=session,
    ).order_by('start_date').first()
    return first_term is not None
