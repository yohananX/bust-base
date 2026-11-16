"""Backfill session-scoped subject configurations and academic references.

This is the data-bearing half of the Phase 2 migration.  Legacy ownership
fields remain nullable until ``0013`` so this migration can be reversed
safely.  Forward migration validates every source row before changing data:

* each legacy ClassSubject is cloned once per existing ClassOffering;
* Score rows are mapped through their term session and the student's exact
  enrolment for that session;
* TeacherAssignment rows are mapped through their explicit legacy session;
* missing/contradictory evidence aborts with record IDs instead of guessing.

The effective legacy pass mark (class override, otherwise subject default) is
snapshotted into every offering-specific configuration.
"""

import django.db.models.deletion
from django.db import migrations, models


MAX_DIAGNOSTICS = 25


def _diagnostic_error(prefix, issues):
    preview = '; '.join(issues[:MAX_DIAGNOSTICS])
    remaining = len(issues) - MAX_DIAGNOSTICS
    if remaining > 0:
        preview += f'; ... and {remaining} more issue(s)'
    raise RuntimeError(f'{prefix}: {preview}')


def backfill_session_scope(apps, schema_editor):
    ClassSubject = apps.get_model('academics', 'ClassSubject')
    TeacherAssignment = apps.get_model('academics', 'TeacherAssignment')
    Score = apps.get_model('academics', 'Score')
    ClassOffering = apps.get_model('students', 'ClassOffering')
    ClassEnrollment = apps.get_model('students', 'ClassEnrollment')
    db_alias = schema_editor.connection.alias

    class_subjects = list(
        ClassSubject.objects.using(db_alias)
        .select_related('subject', 'school_class')
        .order_by('pk')
    )
    offerings = list(
        ClassOffering.objects.using(db_alias)
        .select_related('school_class', 'academic_session')
        .order_by('academic_session__start_date', 'pk')
    )

    issues = []
    offering_by_key = {}
    offerings_by_class = {}
    for offering in offerings:
        school_ids = {
            offering.school_id,
            offering.school_class.school_id,
            offering.academic_session.school_id,
        }
        if len(school_ids) != 1:
            issues.append(
                f'ClassOffering {offering.pk} has contradictory school/class/session ownership'
            )
            continue
        key = (
            offering.school_id,
            offering.school_class_id,
            offering.academic_session_id,
        )
        if key in offering_by_key:
            issues.append(
                f'ClassOffering {offering.pk} duplicates offering {offering_by_key[key].pk} '
                f'for school/class/session {key}'
            )
            continue
        offering_by_key[key] = offering
        offerings_by_class.setdefault(
            (offering.school_id, offering.school_class_id), []
        ).append(offering)

    legacy_config_by_key = {}
    config_offerings = {}
    effective_pass_marks = {}
    for config in class_subjects:
        school_ids = {
            config.school_id,
            config.school_class.school_id,
            config.subject.school_id,
        }
        if len(school_ids) != 1:
            issues.append(
                f'ClassSubject {config.pk} has contradictory school/class/subject ownership'
            )
            continue

        key = (config.school_id, config.school_class_id, config.subject_id)
        if key in legacy_config_by_key:
            issues.append(
                f'ClassSubject {config.pk} duplicates ClassSubject '
                f'{legacy_config_by_key[key].pk} for school/class/subject {key}'
            )
            continue
        legacy_config_by_key[key] = config

        targets = offerings_by_class.get(
            (config.school_id, config.school_class_id), []
        )
        if not targets:
            issues.append(
                f'ClassSubject {config.pk} (class={config.school_class_id}, '
                f'subject={config.subject_id}) has no ClassOffering; create the '
                'required offering(s) before migrating'
            )
            continue
        config_offerings[config.pk] = targets
        effective_pass_marks[config.pk] = (
            config.pass_mark
            if config.pass_mark is not None
            else config.subject.pass_mark
        )

    assignment_plan = {}
    for assignment in (
        TeacherAssignment.objects.using(db_alias)
        .select_related('teacher', 'subject', 'school_class', 'session')
        .order_by('pk')
    ):
        school_ids = {
            assignment.school_id,
            assignment.teacher.school_id,
            assignment.subject.school_id,
            assignment.school_class.school_id,
            assignment.session.school_id,
        }
        if len(school_ids) != 1:
            issues.append(
                f'TeacherAssignment {assignment.pk} has contradictory tenant ownership'
            )
            continue
        offering = offering_by_key.get(
            (
                assignment.school_id,
                assignment.school_class_id,
                assignment.session_id,
            )
        )
        if offering is None:
            issues.append(
                f'TeacherAssignment {assignment.pk} has no ClassOffering for '
                f'class={assignment.school_class_id}, session={assignment.session_id}'
            )
            continue
        config = legacy_config_by_key.get(
            (
                assignment.school_id,
                assignment.school_class_id,
                assignment.subject_id,
            )
        )
        if config is None:
            issues.append(
                f'TeacherAssignment {assignment.pk} has no legacy ClassSubject for '
                f'class={assignment.school_class_id}, subject={assignment.subject_id}'
            )
            continue
        assignment_plan[assignment.pk] = (config.pk, offering.pk)

    score_plan = {}
    for score in (
        Score.objects.using(db_alias)
        .select_related('student', 'subject', 'term__session')
        .order_by('pk')
    ):
        school_ids = {
            score.school_id,
            score.student.school_id,
            score.subject.school_id,
            score.term.school_id,
            score.term.session.school_id,
        }
        if len(school_ids) != 1:
            issues.append(f'Score {score.pk} has contradictory tenant ownership')
            continue

        enrolments = list(
            ClassEnrollment.objects.using(db_alias).filter(
                student_id=score.student_id,
                session_id=score.term.session_id,
            )[:2]
        )
        if len(enrolments) != 1:
            issues.append(
                f'Score {score.pk} requires exactly one ClassEnrollment for '
                f'student={score.student_id}, session={score.term.session_id}; '
                f'found {len(enrolments)}'
            )
            continue
        enrolment = enrolments[0]
        if enrolment.school_id != score.school_id:
            issues.append(
                f'Score {score.pk} enrollment {enrolment.pk} belongs to a different school'
            )
            continue

        offering = offering_by_key.get(
            (
                score.school_id,
                enrolment.school_class_id,
                score.term.session_id,
            )
        )
        if offering is None:
            issues.append(
                f'Score {score.pk} has no ClassOffering for enrollment '
                f'{enrolment.pk} (class={enrolment.school_class_id}, '
                f'session={score.term.session_id})'
            )
            continue
        if (
            enrolment.class_offering_id is not None
            and enrolment.class_offering_id != offering.pk
        ):
            issues.append(
                f'Score {score.pk} enrollment {enrolment.pk} points to '
                f'ClassOffering {enrolment.class_offering_id}, expected {offering.pk}'
            )
            continue

        config = legacy_config_by_key.get(
            (score.school_id, enrolment.school_class_id, score.subject_id)
        )
        if config is None:
            issues.append(
                f'Score {score.pk} has no legacy ClassSubject for '
                f'class={enrolment.school_class_id}, subject={score.subject_id}'
            )
            continue
        score_plan[score.pk] = (config.pk, offering.pk)

    if issues:
        _diagnostic_error('Session-scoped academic migration cannot map legacy data', issues)

    config_mapping = {}
    created_configs = 0
    for config in class_subjects:
        targets = config_offerings[config.pk]
        effective_pass_mark = effective_pass_marks[config.pk]

        # Keep the original primary key for the earliest existing offering;
        # additional sessions receive independent configuration rows.
        first = targets[0]
        config.class_offering_id = first.pk
        config.pass_mark = effective_pass_mark
        config.save(update_fields=['class_offering', 'pass_mark'])
        config_mapping[(config.pk, first.pk)] = config.pk

        for offering in targets[1:]:
            clone = ClassSubject.objects.using(db_alias).create(
                school_id=config.school_id,
                school_class_id=config.school_class_id,
                class_offering_id=offering.pk,
                subject_id=config.subject_id,
                pass_mark=effective_pass_mark,
            )
            config_mapping[(config.pk, offering.pk)] = clone.pk
            created_configs += 1

    for assignment_pk, mapping_key in assignment_plan.items():
        TeacherAssignment.objects.using(db_alias).filter(pk=assignment_pk).update(
            class_subject_id=config_mapping[mapping_key]
        )

    for score_pk, mapping_key in score_plan.items():
        Score.objects.using(db_alias).filter(pk=score_pk).update(
            class_subject_id=config_mapping[mapping_key]
        )

    null_counts = {
        'ClassSubject': ClassSubject.objects.using(db_alias).filter(
            class_offering__isnull=True
        ).count(),
        'TeacherAssignment': TeacherAssignment.objects.using(db_alias).filter(
            class_subject__isnull=True
        ).count(),
        'Score': Score.objects.using(db_alias).filter(
            class_subject__isnull=True
        ).count(),
    }
    if any(null_counts.values()):
        raise RuntimeError(
            'Session-scoped academic migration left unmapped rows: '
            + ', '.join(f'{name}={count}' for name, count in null_counts.items())
        )

    print(
        'Session-scoped academics migration: mapped '
        f'{len(class_subjects)} legacy configuration(s), created '
        f'{created_configs} session clone(s), mapped '
        f'{len(assignment_plan)} assignment(s) and {len(score_plan)} score(s).'
    )


def reverse_session_scope(apps, schema_editor):
    """Collapse identical session configs back to the legacy class scope.

    Reversal is intentionally refused when session pass marks differ because a
    single legacy ClassSubject cannot represent those values without data loss.
    """
    ClassSubject = apps.get_model('academics', 'ClassSubject')
    TeacherAssignment = apps.get_model('academics', 'TeacherAssignment')
    Score = apps.get_model('academics', 'Score')
    db_alias = schema_editor.connection.alias

    configs = list(
        ClassSubject.objects.using(db_alias)
        .select_related('class_offering')
        .order_by('pk')
    )
    issues = []
    groups = {}
    for config in configs:
        if config.class_offering_id is None:
            issues.append(f'ClassSubject {config.pk} has no ClassOffering')
            continue
        offering = config.class_offering
        if config.school_id != offering.school_id:
            issues.append(
                f'ClassSubject {config.pk} and ClassOffering {offering.pk} '
                'belong to different schools'
            )
            continue
        key = (config.school_id, offering.school_class_id, config.subject_id)
        groups.setdefault(key, []).append(config)

    for key, group in groups.items():
        pass_marks = {config.pass_mark for config in group}
        if len(pass_marks) > 1:
            details = ', '.join(
                f'{config.pk}:{config.pass_mark}' for config in group
            )
            issues.append(
                f'cannot collapse school/class/subject {key}; session pass marks '
                f'differ ({details})'
            )

    if issues:
        _diagnostic_error('Cannot reverse session-scoped academic migration', issues)

    # Restore legacy fields before repointing/deleting session clones.
    for assignment in (
        TeacherAssignment.objects.using(db_alias)
        .select_related('class_subject__class_offering')
        .order_by('pk')
    ):
        config = assignment.class_subject
        offering = config.class_offering
        assignment.subject_id = config.subject_id
        assignment.school_class_id = offering.school_class_id
        assignment.session_id = offering.academic_session_id
        assignment.save(update_fields=['subject', 'school_class', 'session'])

    for score in (
        Score.objects.using(db_alias)
        .select_related('class_subject')
        .order_by('pk')
    ):
        # QuerySet.update bypasses post_save/audit signals, which would
        # otherwise fail in migration reversal because the audit receiver
        # imports AuditLog from the current apps registry.
        Score.objects.using(db_alias).filter(pk=score.pk).update(
            subject_id=score.class_subject.subject_id
        )

    deleted_clones = 0
    for key, group in groups.items():
        canonical = group[0]
        school_class_id = key[1]
        canonical.school_class_id = school_class_id
        canonical.save(update_fields=['school_class'])

        duplicate_ids = [config.pk for config in group[1:]]
        if not duplicate_ids:
            continue

        # New references disappear later in the reverse migration, so point
        # them temporarily at the canonical row to satisfy PROTECT while the
        # duplicate configurations are removed.
        TeacherAssignment.objects.using(db_alias).filter(
            class_subject_id__in=duplicate_ids
        ).update(class_subject_id=canonical.pk)
        Score.objects.using(db_alias).filter(
            class_subject_id__in=duplicate_ids
        ).update(class_subject_id=canonical.pk)
        ClassSubject.objects.using(db_alias).filter(pk__in=duplicate_ids).delete()
        deleted_clones += len(duplicate_ids)

    print(
        'Reversed session-scoped academics migration: collapsed '
        f'{deleted_clones} session clone(s).'
    )


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0011_subject_pass_mark'),
        ('students', '0011_classoffering_and_enrollment_offering'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='classsubject',
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name='teacherassignment',
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name='score',
            unique_together=set(),
        ),
        migrations.AlterField(
            model_name='classsubject',
            name='school_class',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='class_subjects',
                to='students.schoolclass',
                verbose_name='class',
            ),
        ),
        migrations.AlterField(
            model_name='teacherassignment',
            name='school_class',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='teacher_assignments',
                to='students.schoolclass',
                verbose_name='class',
            ),
        ),
        migrations.AlterField(
            model_name='teacherassignment',
            name='session',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='teacher_assignments',
                to='core.academicsession',
                verbose_name='academic session',
            ),
        ),
        migrations.AlterField(
            model_name='teacherassignment',
            name='subject',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='teacher_assignments',
                to='academics.subject',
                verbose_name='subject',
            ),
        ),
        migrations.AlterField(
            model_name='score',
            name='subject',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='scores',
                to='academics.subject',
                verbose_name='subject',
            ),
        ),
        migrations.AddField(
            model_name='classsubject',
            name='class_offering',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='class_subjects',
                to='students.classoffering',
                verbose_name='class offering',
            ),
        ),
        migrations.AddField(
            model_name='teacherassignment',
            name='class_subject',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='teacher_assignments',
                to='academics.classsubject',
                verbose_name='class subject',
            ),
        ),
        migrations.AddField(
            model_name='score',
            name='class_subject',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='scores',
                to='academics.classsubject',
                verbose_name='class subject',
            ),
        ),
        migrations.RunPython(
            backfill_session_scope,
            reverse_code=reverse_session_scope,
        ),
    ]
