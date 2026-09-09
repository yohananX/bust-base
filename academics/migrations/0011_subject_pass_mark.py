# Generated migration for adding pass_mark to Subject
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('academics', '0010_remove_subject_pass_mark'),
    ]

    operations = [
        migrations.AddField(
            model_name='subject',
            name='pass_mark',
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=None,
                help_text='Default pass mark for this subject. Can be overridden per class in ClassSubject.',
                null=True,
                verbose_name='pass mark',
            ),
        ),
    ]
