# Data migration: backfill the three standard terms for every academic session.

from datetime import timedelta

from django.db import migrations


def ensure_three_terms(apps, schema_editor):
    AcademicSession = apps.get_model('core', 'AcademicSession')
    Term = apps.get_model('core', 'Term')

    standard = [
        ('First Term', 0, 1),
        ('Second Term', 1, 2),
        ('Third Term', 2, 3),
    ]

    for session in AcademicSession.objects.all().iterator():
        total_days = (session.end_date - session.start_date).days
        third = max(total_days // 3, 1)

        existing = set(
            Term.objects.filter(session=session).values_list('name', flat=True)
        )
        school_has_current = Term.objects.filter(
            school_id=session.school_id, is_current=True
        ).exists()

        for name, lo, hi in standard:
            if name in existing:
                continue
            term = Term(
                school_id=session.school_id,
                session=session,
                name=name,
                start_date=session.start_date + timedelta(days=lo * third),
                end_date=(
                    session.end_date
                    if hi == 3
                    else session.start_date + timedelta(days=hi * third)
                ),
                is_current=False,
            )
            term.save()
            if not school_has_current:
                term.is_current = True
                term.save()
                school_has_current = True


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_school_logo_school_principal_name'),
    ]

    operations = [
        migrations.RunPython(ensure_three_terms, noop),
    ]
