"""Finalize ClassOffering-owned academic configuration fields."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('academics', '0012_backfill_session_scoped_academics'),
        ('students', '0011_classoffering_and_enrollment_offering'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='subject',
            name='school_classes',
        ),
        migrations.AddField(
            model_name='subject',
            name='class_offerings',
            field=models.ManyToManyField(
                related_name='subjects',
                through='academics.ClassSubject',
                to='students.classoffering',
                verbose_name='class offerings',
            ),
        ),
        migrations.RemoveField(
            model_name='classsubject',
            name='school_class',
        ),
        migrations.RemoveField(
            model_name='teacherassignment',
            name='school_class',
        ),
        migrations.RemoveField(
            model_name='teacherassignment',
            name='session',
        ),
        migrations.RemoveField(
            model_name='teacherassignment',
            name='subject',
        ),
        migrations.RemoveField(
            model_name='score',
            name='subject',
        ),
        migrations.AlterField(
            model_name='classsubject',
            name='class_offering',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='class_subjects',
                to='students.classoffering',
                verbose_name='class offering',
            ),
        ),
        migrations.AlterField(
            model_name='classsubject',
            name='subject',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='class_subjects',
                to='academics.subject',
                verbose_name='subject',
            ),
        ),
        migrations.AlterField(
            model_name='classsubject',
            name='pass_mark',
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=None,
                help_text=(
                    'Pass mark for this subject in this class offering. The '
                    'subject default is copied here when a new configuration is created.'
                ),
                null=True,
                verbose_name='pass mark',
            ),
        ),
        migrations.AlterField(
            model_name='teacherassignment',
            name='class_subject',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='teacher_assignments',
                to='academics.classsubject',
                verbose_name='class subject',
            ),
        ),
        migrations.AlterField(
            model_name='score',
            name='class_subject',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='scores',
                to='academics.classsubject',
                verbose_name='class subject',
            ),
        ),
        migrations.AlterField(
            model_name='subject',
            name='pass_mark',
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=None,
                help_text=(
                    'Default copied into new class-offering configurations. Changing '
                    'this value does not alter existing or historical configurations.'
                ),
                null=True,
                verbose_name='pass mark',
            ),
        ),
        migrations.AlterModelOptions(
            name='classsubject',
            options={
                'ordering': [
                    'class_offering__school_class__name',
                    '-class_offering__academic_session__start_date',
                    'subject__name',
                ],
                'verbose_name': 'class subject',
                'verbose_name_plural': 'class subjects',
            },
        ),
        migrations.AlterUniqueTogether(
            name='classsubject',
            unique_together={('class_offering', 'subject')},
        ),
        migrations.AlterUniqueTogether(
            name='teacherassignment',
            unique_together={('teacher', 'class_subject')},
        ),
        migrations.AlterUniqueTogether(
            name='score',
            unique_together={('student', 'class_subject', 'term')},
        ),
    ]
