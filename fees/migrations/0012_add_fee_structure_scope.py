from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('fees', '0012_backfill_invoice_payment_school'),
        ('students', '0004_plan_updates'),
    ]

    operations = [
        migrations.AddField(
            model_name='feestructure',
            name='scope',
            field=models.CharField(
                choices=[('CLASS', 'Class-specific'), ('SCHOOL_WIDE', 'School-wide (all classes)')],
                default='CLASS',
                help_text='Class-specific applies to one class. School-wide applies to all classes.',
                max_length=20,
                verbose_name='scope',
            ),
        ),
        migrations.AlterField(
            model_name='feestructure',
            name='school_class',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to='students.schoolclass',
                verbose_name='school class',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='feestructure',
            unique_together={('school', 'scope', 'school_class', 'term', 'category', 'student_type')},
        ),
    ]
