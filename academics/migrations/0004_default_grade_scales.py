"""Seed default Nigerian school grade scales for every school."""

from django.db import migrations


GRADES = [
    {'min_score': 75, 'max_score': 100, 'label': 'A', 'remark': 'Excellent'},
    {'min_score': 60, 'max_score': 74,  'label': 'B', 'remark': 'Very Good'},
    {'min_score': 50, 'max_score': 59,  'label': 'C', 'remark': 'Credit'},
    {'min_score': 40, 'max_score': 49,  'label': 'D', 'remark': 'Pass'},
    {'min_score': 0,  'max_score': 39,  'label': 'F', 'remark': 'Fail'},
]


def seed_grade_scales(apps, schema_editor):
    School = apps.get_model('core', 'School')
    GradeScale = apps.get_model('academics', 'GradeScale')

    for school in School.objects.all():
        for grade in GRADES:
            GradeScale.objects.get_or_create(
                school=school,
                label=grade['label'],
                defaults={
                    'min_score': grade['min_score'],
                    'max_score': grade['max_score'],
                    'remark': grade['remark'],
                },
            )


def unseed_grade_scales(apps, schema_editor):
    GradeScale = apps.get_model('academics', 'GradeScale')
    GradeScale.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_school_logo_school_principal_name'),
        ('academics', '0003_gradescale_termresult'),
    ]

    operations = [
        migrations.RunPython(seed_grade_scales, unseed_grade_scales),
    ]
