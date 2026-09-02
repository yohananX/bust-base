"""Fee-related utilities: student type resolution, pricing helpers, etc."""
from __future__ import annotations

from core.models import AcademicSession
from students.models import ClassEnrollment, Student


def resolve_student_type(student: Student, session=None) -> str:
    """Return 'NEW' or 'RETURNING' for a student relative to a session.

    A student is considered *new* when they have no prior class enrollment
    before the given session starts. Otherwise they are *returning*.

    Withdrawn/re-enrolling students are treated as new if their most recent
    prior enrollment was in an earlier session.
    """
    session = session or AcademicSession.objects.filter(
        school=student.school, is_current=True
    ).first()

    if session is None:
        return 'NEW'

    has_prior = ClassEnrollment.objects.filter(
        student=student,
        session__start_date__lt=session.start_date,
    ).exists()

    return 'RETURNING' if has_prior else 'NEW'


def student_type_for_term(student, term):
    """Convenience wrapper: resolve student type for the term's session."""
    return resolve_student_type(student, term.session)
