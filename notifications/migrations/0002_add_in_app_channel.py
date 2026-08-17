from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='notificationlog',
            name='channel',
            field=models.CharField(
                choices=[('EMAIL', 'Email'), ('SMS', 'SMS'), ('IN_APP', 'In-App')],
                max_length=10,
                verbose_name='channel',
            ),
        ),
    ]
