"""Transactional services for session-scoped academic configuration."""

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import ClassSubject


@transaction.atomic
def copy_subject_configurations(source_offering, target_offering):
    """Copy missing subject configurations into a later class offering.

    Existing target configurations are never modified, making the operation
    idempotent and safe to repeat.  Teacher assignments and scores are not
    copied.  The returned tuple is ``(created_count, skipped_count)``.
    """
    errors = {}
    if source_offering.pk == target_offering.pk:
        errors['source_offering'] = 'Choose a different source offering.'
    if source_offering.school_id != target_offering.school_id:
        errors['source_offering'] = (
            'Source and target offerings must belong to the same school.'
        )
    if source_offering.school_class_id != target_offering.school_class_id:
        errors['source_offering'] = (
            'Source and target offerings must represent the same class.'
        )
    if (
        source_offering.academic_session.start_date
        >= target_offering.academic_session.start_date
    ):
        errors['source_offering'] = (
            'Source offering must belong to an earlier academic session.'
        )
    if errors:
        raise ValidationError(errors)

    created_count = 0
    skipped_count = 0
    source_configs = ClassSubject.objects.filter(
        school=source_offering.school,
        class_offering=source_offering,
    ).select_related('subject')

    for source_config in source_configs:
        _, created = ClassSubject.objects.get_or_create(
            school=target_offering.school,
            class_offering=target_offering,
            subject=source_config.subject,
            defaults={'pass_mark': source_config.pass_mark},
        )
        if created:
            created_count += 1
        else:
            skipped_count += 1

    return created_count, skipped_count
