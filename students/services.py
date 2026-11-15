"""Transactional enrolment services for the students app.

Provides ``confirm_enrolment``, the single write path for creating or returning
a student's class enrolment. Direct ``ClassEnrollment.objects.create(...)``
calls in views and model methods should route through this service.
"""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .models import ClassEnrollment, ClassOffering


class EnrolmentConflictError(ValidationError):
    """Raised when an existing enrolment conflicts with a requested class/session.

    Callers must treat this as a genuine conflict requiring an explicit change
    operation, never as a silent successful no-op.
    """


def confirm_enrolment(student, school_class, session):
    """Confirm (create or return) a student's enrolment in a class/session.

    The service is transactional and idempotent:

    * Resolves the exact ``ClassOffering`` for the class/session.
    * Rejects cross-tenant or mismatched records.
    * Creates at most one enrolment per student/session.
    * If an enrolment already exists for the student/session and matches the
      requested class/offering, returns it without creating a duplicate.
    * If an existing enrolment conflicts with the requested class, raises
      :class:`EnrolmentConflictError` (not a silent no-op).
    * Only deactivates the previous current enrolment after the new enrolment
      has been successfully created and validated.
    * Uses ``transaction.atomic()`` and handles concurrent duplicate requests
      safely via the database uniqueness constraint plus ``IntegrityError``
      handling.

    Returns the (existing or newly created) :class:`ClassEnrollment`.
    """
    if student.school_id is None:
        raise ValidationError({'student': 'Student must belong to a school.'})
    if school_class.school_id != student.school_id:
        raise ValidationError(
            {'school_class': 'Class must belong to the same school as the student.'}
        )
    if session.school_id != student.school_id:
        raise ValidationError(
            {'session': 'Session must belong to the same school as the student.'}
        )

    try:
        offering = ClassOffering.objects.get(
            school_class=school_class,
            academic_session=session,
            school=student.school,
        )
    except ClassOffering.DoesNotExist:
        raise ValidationError(
            {
                'class_offering': (
                    'No class offering exists for this class and session. '
                    'Create the offering before enrolling.'
                )
            }
        )
    except ClassOffering.MultipleObjectsReturned:
        raise ValidationError(
            {
                'class_offering': (
                    'Multiple class offerings exist for this class and session. '
                    'The offering is ambiguous.'
                )
            }
        )

    with transaction.atomic():
        existing = (
            ClassEnrollment.objects.filter(student=student, session=session)
            .select_for_update()
            .first()
        )
        if existing:
            if (
                existing.school_class_id == school_class.id
                and existing.class_offering_id == offering.id
            ):
                # Idempotent: same student/class/session already enrolled.
                return existing
            raise EnrolmentConflictError(
                {
                    'class_enrollment': (
                        'An enrolment already exists for this student in this '
                        'session for a different class. Use an explicit change '
                        'operation instead of re-confirming.'
                    )
                }
            )

        try:
            # The nested atomic block creates a savepoint. If a concurrent
            # request wins the unique(student, session) race, rolling back this
            # savepoint keeps the outer transaction usable for the lookup below
            # on both PostgreSQL and SQLite.
            with transaction.atomic():
                enrolment = ClassEnrollment(
                    school=student.school,
                    student=student,
                    school_class=school_class,
                    session=session,
                    class_offering=offering,
                    is_current=True,
                )
                # Cross-table/domain validation runs here. The database owns
                # the concurrent uniqueness decision; skipping model-level
                # unique validation avoids a race where a just-committed peer
                # row would raise ValidationError instead of reaching the
                # IntegrityError recovery path below.
                enrolment.full_clean(validate_unique=False)
                enrolment.save()
        except IntegrityError:
            # Concurrent duplicate: a sibling transaction created the enrolment
            # first. A matching enrolment is idempotent; a differing one is a
            # conflict. Any other integrity failure propagates.
            existing = ClassEnrollment.objects.filter(
                student=student, session=session
            ).first()
            if existing and (
                existing.school_class_id == school_class.id
                and existing.class_offering_id == offering.id
            ):
                return existing
            if existing:
                raise EnrolmentConflictError(
                    {
                        'class_enrollment': (
                            'An enrolment already exists for this student in '
                            'this session for a different class.'
                        )
                    }
                )
            raise

    return enrolment
