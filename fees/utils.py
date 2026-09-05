"""Fee-related utilities: student type resolution, pricing helpers, etc."""
from __future__ import annotations

from core.models import AcademicSession
from students.models import ClassEnrollment, Student


def resolve_student_type(student: Student, session=None, term=None) -> str:
    """Return 'NEW' or 'RETURNING' for a student relative to a session/term.

    A student is considered *new* when they have no prior class enrollment
    before the given session starts AND they have not yet paid the
    Registration Form one-time fee. Otherwise they are *returning*.

    The stored Student.student_type takes precedence when the field is
    'RETURNING' (it may have been auto-flipped after the Registration Form
    payment). For the current term in which Registration was just paid, the
    student is still treated as NEW (registration_paid_term == term means
    onboarding still applies this term).

    Withdrawn/re-enrolling students are treated as new if their most recent
    prior enrollment was in an earlier session.
    """
    if session is None:
        session = AcademicSession.objects.filter(
            school=student.school, is_current=True
        ).first()

    if session is None:
        return getattr(student, 'student_type', 'NEW') or 'NEW'

    has_prior_enrollment = ClassEnrollment.objects.filter(
        student=student,
        session__start_date__lt=session.start_date,
    ).exists()

    if has_prior_enrollment:
        return 'RETURNING'

    registration_paid_term_id = getattr(student, 'registration_paid_term_id', None)
    if registration_paid_term_id:
        return 'RETURNING'

    return 'NEW'


def student_type_for_term(student, term):
    """Convenience wrapper: resolve student type for the term's session."""
    return resolve_student_type(student, term.session)
