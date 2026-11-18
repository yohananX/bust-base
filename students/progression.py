"""Permanent progression configuration and next-session preparation services.

Views should remain orchestration-only.  All graph validation, proposal
generation, exception handling, and transactional confirmation live here.
"""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from core.models import AcademicSession, Term

from .models import (
    AcademicStage,
    ClassEnrollment,
    ClassOffering,
    SchoolClass,
    SessionPreparation,
    Student,
    StudentSessionMovement,
)
from .services import confirm_enrolment


TERM_NAMES = ('First Term', 'Second Term', 'Third Term')


class PreparationError(ValidationError):
    """A session preparation cannot safely perform the requested operation."""


@dataclass(frozen=True)
class ConfirmationResult:
    enrolled: int
    withdrawn: int
    excluded: int
    already_confirmed: bool = False


def _raise(message, field=None):
    if field:
        raise PreparationError({field: message})
    raise PreparationError(message)


def _assert_draft(preparation):
    if preparation.status != SessionPreparation.Status.DRAFT:
        _raise('This session preparation has already been confirmed and is read-only.')


def _normalise_id(value):
    if value in (None, ''):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise PreparationError('Progression selections must use valid record IDs.')


def _cycle_start(edge_map):
    """Return a node involved in a directed cycle, otherwise ``None``."""
    complete = set()
    for start in edge_map:
        if start in complete:
            continue
        path = set()
        current = start
        while current is not None and current not in complete:
            if current in path:
                return current
            path.add(current)
            current = edge_map.get(current)
        complete.update(path)
    return None


def _resolved_progression_graph(school, stage_mapping=None, class_mapping=None, *, lock=False):
    stage_qs = AcademicStage.objects.filter(school=school)
    class_qs = SchoolClass.objects.filter(school=school).select_related('academic_stage')
    if lock:
        stage_qs = stage_qs.select_for_update()
        class_qs = class_qs.select_for_update()

    stages = {stage.pk: stage for stage in stage_qs}
    classes = {school_class.pk: school_class for school_class in class_qs}
    stage_edges = {stage.pk: stage.next_stage_id for stage in stages.values()}
    class_edges = {school_class.pk: school_class.next_class_id for school_class in classes.values()}

    for raw_source, raw_target in (stage_mapping or {}).items():
        source_id = _normalise_id(raw_source)
        target_id = _normalise_id(raw_target)
        if source_id not in stages:
            _raise('A selected academic stage does not belong to this school.', 'next_stage')
        if target_id is not None and target_id not in stages:
            _raise('The next academic stage must belong to this school.', 'next_stage')
        if source_id == target_id:
            _raise('An academic stage cannot progress to itself.', 'next_stage')
        stage_edges[source_id] = target_id

    for raw_source, raw_target in (class_mapping or {}).items():
        source_id = _normalise_id(raw_source)
        target_id = _normalise_id(raw_target)
        if source_id not in classes:
            _raise('A selected class does not belong to this school.', 'next_class')
        if target_id is not None and target_id not in classes:
            _raise('The next class must belong to this school.', 'next_class')
        if source_id == target_id:
            _raise('A class cannot progress to itself.', 'next_class')
        class_edges[source_id] = target_id

    if any(target_id is not None and target_id not in stages for target_id in stage_edges.values()):
        _raise('Every next academic stage must belong to this school.', 'next_stage')
    if any(target_id is not None and target_id not in classes for target_id in class_edges.values()):
        _raise('Every next class must belong to this school.', 'next_class')
    if _cycle_start(stage_edges) is not None:
        _raise('Academic stage progression cannot contain a cycle.', 'next_stage')
    if _cycle_start(class_edges) is not None:
        _raise('Class progression cannot contain a cycle.', 'next_class')

    for school_class in classes.values():
        if not school_class.academic_stage_id:
            _raise(f'{school_class.name} must belong to an academic stage.', 'academic_stage')
        destination_id = class_edges[school_class.pk]
        if destination_id is None:
            continue
        destination = classes[destination_id]
        if destination.academic_stage_id == school_class.academic_stage_id:
            continue
        configured_next_stage = stage_edges.get(school_class.academic_stage_id)
        if configured_next_stage is None:
            _raise(
                f'{school_class.name} cannot progress across stages until '
                'its source stage has a next stage.',
                'next_class',
            )
        if configured_next_stage != destination.academic_stage_id:
            _raise(
                f'{school_class.name} must progress to a class in its stage’s '
                'configured next stage.',
                'next_class',
            )

    return stages, classes, stage_edges, class_edges


def validate_progression_configuration(school, stage_mapping=None, class_mapping=None):
    """Validate a complete proposed progression graph without changing it."""
    _resolved_progression_graph(school, stage_mapping, class_mapping)


@transaction.atomic
def update_progression_configuration(school, stage_mapping=None, class_mapping=None):
    """Persist permanent stage/class progression after whole-graph validation."""
    stages, classes, stage_edges, class_edges = _resolved_progression_graph(
        school, stage_mapping, class_mapping, lock=True
    )

    changed_stages = 0
    for stage_id, target_id in stage_edges.items():
        if stages[stage_id].next_stage_id != target_id:
            AcademicStage.objects.filter(school=school, pk=stage_id).update(
                next_stage_id=target_id
            )
            changed_stages += 1

    changed_classes = 0
    for class_id, target_id in class_edges.items():
        if classes[class_id].next_class_id != target_id:
            SchoolClass.objects.filter(school=school, pk=class_id).update(
                next_class_id=target_id
            )
            changed_classes += 1

    return changed_stages, changed_classes


def validate_term_schedule(session_start, session_end, term_specs):
    """Validate the three configured terms and return them in canonical order."""
    if not session_start or not session_end or session_end < session_start:
        _raise('Session end date must be on or after its start date.', 'end_date')
    by_name = {spec.get('name'): spec for spec in term_specs}
    if set(by_name) != set(TERM_NAMES) or len(term_specs) != len(TERM_NAMES):
        _raise('Configure First, Second and Third Term exactly once.', 'terms')

    ordered = []
    prior_end = None
    for name in TERM_NAMES:
        spec = by_name[name]
        start = spec.get('start_date')
        end = spec.get('end_date')
        if not start or not end:
            _raise(f'{name} start and end dates are required.', 'terms')
        if end < start:
            _raise(f'{name} end date must be on or after its start date.', 'terms')
        if start < session_start or end > session_end:
            _raise(f'{name} dates must fall within the academic session.', 'terms')
        if prior_end is not None and start <= prior_end:
            _raise('Term dates must be chronological and must not overlap.', 'terms')
        ordered.append({'name': name, 'start_date': start, 'end_date': end})
        prior_end = end
    return ordered


@transaction.atomic
def create_session_preparation(
    *, school, source_session, name, start_date, end_date, term_specs, created_by=None
):
    """Create a future session, configured terms, and its draft preparation."""
    name = (name or '').strip()
    if not name:
        _raise('Session name is required.', 'name')
    ordered_terms = validate_term_schedule(start_date, end_date, term_specs)
    source_session = AcademicSession.objects.select_for_update().filter(
        school=school, pk=source_session.pk
    ).first()
    if source_session is None:
        _raise('Select a source session from this school.', 'source_session')
    if start_date <= source_session.end_date:
        _raise('The next session must start after the source session ends.', 'start_date')
    if AcademicSession.objects.filter(school=school, name=name).exists():
        _raise('A session with this name already exists.', 'name')

    target_session = AcademicSession(
        school=school,
        name=name,
        start_date=start_date,
        end_date=end_date,
        is_current=False,
    )
    target_session.full_clean()
    target_session.save()
    for spec in ordered_terms:
        Term.objects.create(
            school=school,
            session=target_session,
            name=spec['name'],
            start_date=spec['start_date'],
            end_date=spec['end_date'],
            is_current=False,
        )

    preparation = SessionPreparation(
        school=school,
        source_session=source_session,
        target_session=target_session,
        created_by=created_by,
    )
    preparation.full_clean()
    preparation.save()
    return preparation


@transaction.atomic
def get_or_create_session_preparation(*, school, source_session, target_session, created_by=None):
    """Start or return the one preparation associated with an existing target."""
    source = AcademicSession.objects.select_for_update().filter(
        school=school, pk=source_session.pk
    ).first()
    target = AcademicSession.objects.select_for_update().filter(
        school=school, pk=target_session.pk
    ).first()
    if source is None or target is None:
        _raise('Source and target sessions must belong to this school.')
    if target.start_date <= source.end_date:
        _raise('The target session must start after the source session ends.')
    preparation = SessionPreparation.objects.filter(
        school=school, target_session=target
    ).first()
    if preparation:
        if preparation.source_session_id != source.pk:
            _raise('This target session already has a preparation from another source session.')
        return preparation, False
    if target.is_current:
        _raise('The current session cannot be used as a future preparation target.')
    term_names = set(
        Term.objects.filter(school=school, session=target).values_list(
            'name', flat=True
        )
    )
    if term_names != set(TERM_NAMES):
        _raise('Configure First, Second and Third Term before preparing this session.')

    preparation = SessionPreparation(
        school=school,
        source_session=source,
        target_session=target,
        created_by=created_by,
    )
    preparation.full_clean()
    preparation.save()
    return preparation, True


@transaction.atomic
def update_preparation_schedule(*, preparation, start_date, end_date, term_specs):
    """Update target-session and term dates while the preparation is a draft."""
    preparation = SessionPreparation.objects.select_for_update().select_related(
        'target_session'
    ).get(pk=preparation.pk, school=preparation.school)
    _assert_draft(preparation)
    ordered_terms = validate_term_schedule(start_date, end_date, term_specs)
    if start_date <= preparation.source_session.end_date:
        _raise('The next session must start after the source session ends.', 'start_date')

    target = preparation.target_session
    target.start_date = start_date
    target.end_date = end_date
    target.save(update_fields=['start_date', 'end_date'])
    existing_terms = {
        term.name: term
        for term in Term.objects.select_for_update().filter(
            school=preparation.school, session=target
        )
    }
    if set(existing_terms) != set(TERM_NAMES):
        _raise('The target session must contain exactly First, Second and Third Term.')
    for spec in ordered_terms:
        term = existing_terms[spec['name']]
        term.start_date = spec['start_date']
        term.end_date = spec['end_date']
        term.save(update_fields=['start_date', 'end_date'])
    return preparation


@transaction.atomic
def set_preparation_offerings(*, preparation, class_ids):
    """Synchronise target-session offerings without deleting protected data."""
    preparation = SessionPreparation.objects.select_for_update().get(
        pk=preparation.pk, school=preparation.school
    )
    _assert_draft(preparation)
    selected_ids = {_normalise_id(value) for value in class_ids}
    selected_ids.discard(None)
    classes = {
        school_class.pk: school_class
        for school_class in SchoolClass.objects.filter(
            school=preparation.school, pk__in=selected_ids
        )
    }
    if set(classes) != selected_ids:
        _raise('Every selected class must belong to this school.', 'classes')

    existing = list(
        ClassOffering.objects.select_for_update().filter(
            school=preparation.school,
            academic_session=preparation.target_session,
        )
    )
    for offering in existing:
        if offering.school_class_id not in selected_ids:
            try:
                offering.delete()
            except ProtectedError:
                _raise(
                    f'{offering.school_class.name} cannot be removed because its '
                    'offering already has protected academic or enrolment records.',
                    'classes',
                )

    created = 0
    for school_class in classes.values():
        _, was_created = ClassOffering.objects.get_or_create(
            school=preparation.school,
            school_class=school_class,
            academic_session=preparation.target_session,
        )
        created += int(was_created)
    return created, len(selected_ids)


@transaction.atomic
def generate_progression_proposals(preparation):
    """Create or refresh idempotent proposals from permanent class progression."""
    preparation = SessionPreparation.objects.select_for_update().get(
        pk=preparation.pk, school=preparation.school
    )
    _assert_draft(preparation)
    enrollments = list(
        ClassEnrollment.objects.filter(
            school=preparation.school,
            session=preparation.source_session,
        ).select_related(
            'student__user',
            'school_class__next_class',
            'school_class__academic_stage',
        ).order_by('student_id')
    )
    existing = {
        movement.student_id: movement
        for movement in StudentSessionMovement.objects.select_for_update().filter(
            school=preparation.school, preparation=preparation
        )
    }
    retained_ids = []
    created = 0
    refreshed = 0
    for enrollment in enrollments:
        student = enrollment.student
        if student.status == Student.ACTIVE:
            proposed_class = enrollment.school_class.next_class or enrollment.school_class
            basis = (
                StudentSessionMovement.ProposalBasis.NEXT_CLASS
                if enrollment.school_class.next_class_id
                else StudentSessionMovement.ProposalBasis.SAME_CLASS
            )
            default_action = StudentSessionMovement.Action.PROGRESS
            default_destination = proposed_class
        else:
            proposed_class = None
            basis = StudentSessionMovement.ProposalBasis.LIFECYCLE_EXCLUSION
            default_action = (
                StudentSessionMovement.Action.WITHDRAW
                if student.status == Student.WITHDRAWN
                else StudentSessionMovement.Action.EXCLUDE
            )
            default_destination = None

        movement = existing.get(student.pk)
        if movement is None:
            movement = StudentSessionMovement(
                school=preparation.school,
                preparation=preparation,
                student=student,
                source_enrollment=enrollment,
                proposed_class=proposed_class,
                destination_class=default_destination,
                proposal_basis=basis,
                action=default_action,
            )
            movement.full_clean()
            movement.save()
            created += 1
        else:
            movement.source_enrollment = enrollment
            movement.proposed_class = proposed_class
            movement.proposal_basis = basis
            if not movement.is_override or student.status != Student.ACTIVE:
                movement.action = default_action
                movement.destination_class = default_destination
                movement.note = ''
                movement.is_override = False
            movement.full_clean()
            movement.save()
            refreshed += 1
        retained_ids.append(movement.pk)

    StudentSessionMovement.objects.filter(
        school=preparation.school, preparation=preparation
    ).exclude(pk__in=retained_ids).delete()
    preparation.proposals_generated_at = timezone.now()
    preparation.save(update_fields=['proposals_generated_at', 'updated_at'])
    return created, refreshed


def movement_issue(movement, offering_class_ids=None, target_enrollments=None):
    """Return ``(code, message)`` for a blocking movement issue, or ``None``."""
    if movement.action not in (
        StudentSessionMovement.Action.PROGRESS,
        StudentSessionMovement.Action.REPEAT,
    ):
        return None
    if movement.student.status != Student.ACTIVE:
        return 'LIFECYCLE_STATUS', 'The student is no longer active and must be excluded or withdrawn.'
    if not movement.destination_class_id:
        return 'NO_DESTINATION', 'No destination class is selected.'
    if (
        movement.action == StudentSessionMovement.Action.REPEAT
        and movement.destination_class_id != movement.source_enrollment.school_class_id
    ):
        return 'INVALID_REPEATER', 'A repeater must remain in the source class.'

    if offering_class_ids is None:
        offering_class_ids = set(
            ClassOffering.objects.filter(
                school=movement.school,
                academic_session=movement.preparation.target_session,
            ).values_list('school_class_id', flat=True)
        )
    if movement.destination_class_id not in offering_class_ids:
        return 'MISSING_OFFERING', 'The destination class is not offered in the target session.'

    if target_enrollments is None:
        target_enrollments = {
            enrollment.student_id: enrollment
            for enrollment in ClassEnrollment.objects.filter(
                school=movement.school,
                session=movement.preparation.target_session,
                student=movement.student,
            )
        }
    existing = target_enrollments.get(movement.student_id)
    if existing and existing.school_class_id != movement.destination_class_id:
        return 'ENROLMENT_CONFLICT', 'The student already has a different enrolment in the target session.'
    if existing and not existing.class_offering_id:
        return 'ENROLMENT_CONFLICT', 'The existing target enrolment is not linked to an exact class offering.'
    return None


@transaction.atomic
def update_student_movement(*, movement, action, destination_class=None, note=''):
    """Apply one reviewed exception while retaining all enrolment validation."""
    reference = StudentSessionMovement.objects.filter(
        pk=movement.pk, school=movement.school
    ).values('preparation_id').first()
    if reference is None:
        _raise('Select a valid student movement.')
    preparation = SessionPreparation.objects.select_for_update().select_related(
        'target_session'
    ).get(pk=reference['preparation_id'], school=movement.school)
    _assert_draft(preparation)
    movement = StudentSessionMovement.objects.select_for_update().select_related(
        'preparation__target_session', 'source_enrollment__school_class'
    ).get(pk=movement.pk, school=movement.school, preparation=preparation)
    valid_actions = {choice for choice, _ in StudentSessionMovement.Action.choices}
    if action not in valid_actions:
        _raise('Select a valid movement action.', 'action')

    if action == StudentSessionMovement.Action.REPEAT:
        destination_class = movement.source_enrollment.school_class
    elif action in (
        StudentSessionMovement.Action.EXCLUDE,
        StudentSessionMovement.Action.WITHDRAW,
    ):
        destination_class = None
    else:
        if destination_class is None:
            _raise('Select a destination class.', 'destination_class')
        destination_class = SchoolClass.objects.filter(
            school=movement.school, pk=destination_class.pk
        ).first()
        if destination_class is None:
            _raise('Destination class must belong to this school.', 'destination_class')

    if destination_class is not None and not ClassOffering.objects.filter(
        school=movement.school,
        academic_session=movement.preparation.target_session,
        school_class=destination_class,
    ).exists():
        _raise('The selected destination has no offering in the target session.', 'destination_class')

    movement.action = action
    movement.destination_class = destination_class
    movement.note = (note or '').strip()
    movement.is_override = not (
        action == StudentSessionMovement.Action.PROGRESS
        and destination_class is not None
        and destination_class.pk == movement.proposed_class_id
    )
    movement.full_clean()
    movement.save()
    return movement


def preparation_summary(preparation, movements=None):
    """Return review counts and annotate movements with any blocking issue."""
    if movements is None:
        movements = list(
            StudentSessionMovement.objects.filter(
                school=preparation.school, preparation=preparation
            ).select_related(
                'student__user',
                'source_enrollment__school_class',
                'proposed_class',
                'destination_class',
                'preparation__target_session',
            )
        )
    offering_class_ids = set(
        ClassOffering.objects.filter(
            school=preparation.school,
            academic_session=preparation.target_session,
        ).values_list('school_class_id', flat=True)
    )
    target_enrollments = {
        enrollment.student_id: enrollment
        for enrollment in ClassEnrollment.objects.filter(
            school=preparation.school,
            session=preparation.target_session,
        ).select_related('school_class')
    }

    counts = {
        'total': len(movements),
        'eligible': 0,
        'progressing': 0,
        'remaining': 0,
        'repeaters': 0,
        'manual_attention': 0,
        'excluded': 0,
        'withdrawn': 0,
        'without_offering': 0,
        'overrides': 0,
    }
    for movement in movements:
        movement.review_issue = movement_issue(
            movement, offering_class_ids, target_enrollments
        )
        included = movement.action in (
            StudentSessionMovement.Action.PROGRESS,
            StudentSessionMovement.Action.REPEAT,
        )
        if movement.student.status == Student.ACTIVE:
            counts['eligible'] += 1
        if included and movement.destination_class_id == movement.source_enrollment.school_class_id:
            counts['remaining'] += 1
        elif included:
            counts['progressing'] += 1
        if movement.action == StudentSessionMovement.Action.REPEAT:
            counts['repeaters'] += 1
        elif movement.action == StudentSessionMovement.Action.EXCLUDE:
            counts['excluded'] += 1
        elif movement.action == StudentSessionMovement.Action.WITHDRAW:
            counts['withdrawn'] += 1
        if movement.is_override:
            counts['overrides'] += 1
        if movement.review_issue:
            counts['manual_attention'] += 1
            if movement.review_issue[0] == 'MISSING_OFFERING':
                counts['without_offering'] += 1
    return counts, movements


@transaction.atomic
def confirm_session_preparation(*, preparation, confirmed_by=None):
    """Confirm every reviewed movement atomically and idempotently."""
    preparation = SessionPreparation.objects.select_for_update().select_related(
        'source_session', 'target_session'
    ).get(pk=preparation.pk, school=preparation.school)
    if preparation.status == SessionPreparation.Status.CONFIRMED:
        movements = preparation.movements.all()
        return ConfirmationResult(
            enrolled=movements.filter(
                action__in=(
                    StudentSessionMovement.Action.PROGRESS,
                    StudentSessionMovement.Action.REPEAT,
                )
            ).count(),
            withdrawn=movements.filter(
                action=StudentSessionMovement.Action.WITHDRAW
            ).count(),
            excluded=movements.filter(
                action=StudentSessionMovement.Action.EXCLUDE
            ).count(),
            already_confirmed=True,
        )
    if preparation.proposals_generated_at is None:
        _raise('Generate and review student movements before confirmation.')

    movements = list(
        StudentSessionMovement.objects.select_for_update().filter(
            school=preparation.school, preparation=preparation
        ).select_related(
            'student',
            'source_enrollment__school_class',
            'destination_class',
            'preparation__target_session',
        )
    )
    locked_students = {
        student.pk: student
        for student in Student.objects.select_for_update().filter(
            school=preparation.school,
            pk__in=[movement.student_id for movement in movements],
        ).order_by('pk')
    }
    if len(locked_students) != len(movements):
        _raise('One or more students in the preparation no longer exist.')
    for movement in movements:
        movement.student = locked_students[movement.student_id]
    source_count = ClassEnrollment.objects.filter(
        school=preparation.school, session=preparation.source_session
    ).count()
    if source_count != len(movements):
        _raise('Source enrolments changed after proposal generation. Regenerate the plan.')

    counts, movements = preparation_summary(preparation, movements)
    if counts['manual_attention']:
        _raise(
            f'{counts["manual_attention"]} student movement(s) still require manual attention.'
        )

    offerings = {
        offering.school_class_id: offering
        for offering in ClassOffering.objects.select_for_update().filter(
            school=preparation.school,
            academic_session=preparation.target_session,
        )
    }
    enrolled = withdrawn = excluded = 0
    for movement in movements:
        if movement.action == StudentSessionMovement.Action.WITHDRAW:
            Student.objects.filter(
                school=preparation.school, pk=movement.student_id
            ).update(status=Student.WITHDRAWN)
            ClassEnrollment.objects.filter(
                school=preparation.school,
                pk=movement.source_enrollment_id,
                is_current=True,
            ).update(is_current=False)
            withdrawn += 1
            continue
        if movement.action == StudentSessionMovement.Action.EXCLUDE:
            excluded += 1
            continue

        offering = offerings[movement.destination_class_id]
        confirm_enrolment(
            student=movement.student,
            school_class=movement.destination_class,
            session=preparation.target_session,
            class_offering=offering,
        )
        enrolled += 1

    preparation.status = SessionPreparation.Status.CONFIRMED
    preparation.confirmed_at = timezone.now()
    preparation.confirmed_by = confirmed_by
    preparation.save(update_fields=[
        'status', 'confirmed_at', 'confirmed_by', 'updated_at',
    ])
    return ConfirmationResult(
        enrolled=enrolled,
        withdrawn=withdrawn,
        excluded=excluded,
    )
