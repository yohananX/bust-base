"""Phase 1: introduce ClassOffering and link ClassEnrollment to an offering.

Steps (forward):
  1. Create the ``ClassOffering`` model (school_class + academic_session, unique
     together, ordered by descending session start date then class name).
  2. Add a nullable ``ClassEnrollment.class_offering`` FK.
  3. Create offerings from every distinct ``(school_class, session)`` pair found
     in existing ``ClassEnrollment`` rows.
  4. Create offerings for active classes in each school's current session.
  5. Backfill every existing enrolment to exactly one offering. Fail loudly if
     any enrolment cannot be mapped.

Reversing:
  - The ``class_offering`` column is dropped from ``ClassEnrollment`` (enrolment
    rows are kept; only the newly added offering pointer is lost).
  - The ``ClassOffering`` table is dropped, removing the offerings created by
    this migration.
  - No pre-existing enrolment/student/class/session data is deleted.
"""

import django.db.models.deletion
from django.db import migrations, models


def create_offerings_and_backfill(apps, schema_editor):
    ClassOffering = apps.get_model('students', 'ClassOffering')
    ClassEnrollment = apps.get_model('students', 'ClassEnrollment')
    SchoolClass = apps.get_model('students', 'SchoolClass')
    AcademicSession = apps.get_model('core', 'AcademicSession')
    School = apps.get_model('core', 'School')
    db_alias = schema_editor.connection.alias

    offerings_created = 0
    enrolments_mapped = 0

    # Validate the source rows before creating anything. Cross-table tenant
    # equality was not database-enforced by the legacy schema, so a corrupted
    # row could otherwise produce an offering owned by the wrong school.
    source_rows = (
        ClassEnrollment.objects.using(db_alias)
        .values_list(
            'pk',
            'school_id',
            'student__school_id',
            'school_class__school_id',
            'session__school_id',
        )
        .iterator(chunk_size=500)
    )
    for enrolment_pk, school_id, student_school_id, class_school_id, session_school_id in source_rows:
        school_ids = {
            school_id,
            student_school_id,
            class_school_id,
            session_school_id,
        }
        if len(school_ids) != 1:
            raise RuntimeError(
                'Cannot map ClassEnrollment %(pk)s: enrolment, student, '
                'class and session must belong to the same school.'
                % {'pk': enrolment_pk}
            )

    # 1. Offerings for every distinct (school_class, session) pair already
    # enrolled. Every enrolment must resolve to exactly one offering.
    pairs = (
        ClassEnrollment.objects.using(db_alias).values_list(
            'school_class_id', 'session_id', 'school_id'
        )
        .distinct()
    )
    for school_class_id, session_id, school_id in pairs:
        _, created = ClassOffering.objects.using(db_alias).get_or_create(
            school_class_id=school_class_id,
            academic_session_id=session_id,
            school_id=school_id,
        )
        if created:
            offerings_created += 1

    # 2. Offerings for active classes in each school's current session, so that
    # classes without historical enrolments still have an offering to enrol into.
    for school in School.objects.using(db_alias).all():
        current_session = AcademicSession.objects.using(db_alias).filter(
            school=school, is_current=True
        ).first()
        if not current_session:
            continue
        for school_class in SchoolClass.objects.using(db_alias).filter(
            school=school, is_active=True
        ):
            _, created = ClassOffering.objects.using(db_alias).get_or_create(
                school_class=school_class,
                academic_session=current_session,
                school=school,
            )
            if created:
                offerings_created += 1

    # 3. Backfill every existing enrolment to exactly one offering. ``get``
    # fails loudly (DoesNotExist/MultipleObjectsReturned) if an enrolment
    # cannot be mapped to a single offering.
    for enrolment in ClassEnrollment.objects.using(db_alias).iterator(
        chunk_size=500
    ):
        offering = ClassOffering.objects.using(db_alias).get(
            school_class_id=enrolment.school_class_id,
            academic_session_id=enrolment.session_id,
            school_id=enrolment.school_id,
        )
        enrolment.class_offering = offering
        enrolment.save(update_fields=['class_offering'])
        enrolments_mapped += 1

    unmapped = ClassEnrollment.objects.using(db_alias).filter(
        class_offering__isnull=True
    ).count()
    if unmapped:
        raise RuntimeError(
            'ClassOffering migration failed: %(count)d enrolment(s) could not '
            'be mapped to an offering.' % {'count': unmapped}
        )

    print(
        'ClassOffering migration: created %(created)d offering(s), '
        'mapped %(mapped)d enrolment(s).'
        % {'created': offerings_created, 'mapped': enrolments_mapped}
    )


class Migration(migrations.Migration):

    dependencies = [
        ('students', '0010_remove_schoolclass_level'),
        ('core', '0009_auditlog_content_type_auditlog_object_id_int'),
    ]

    operations = [
        migrations.CreateModel(
            name='ClassOffering',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'school',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to='core.school',
                        verbose_name='school',
                    ),
                ),
                (
                    'academic_session',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='offerings',
                        to='core.academicsession',
                        verbose_name='academic session',
                    ),
                ),
                (
                    'school_class',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name='offerings',
                        to='students.schoolclass',
                        verbose_name='class',
                    ),
                ),
            ],
            options={
                'verbose_name': 'class offering',
                'verbose_name_plural': 'class offerings',
                'ordering': ['-academic_session__start_date', 'school_class__name'],
                'unique_together': {('school_class', 'academic_session')},
            },
        ),
        migrations.AddField(
            model_name='classenrollment',
            name='class_offering',
            field=models.ForeignKey(
                blank=True,
                help_text='The class offering this enrolment belongs to. Nullable during the transition period; new enrolments created via the enrolment service always resolve an existing offering.',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='enrollments',
                to='students.classoffering',
                verbose_name='class offering',
            ),
        ),
        migrations.RunPython(
            create_offerings_and_backfill,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
