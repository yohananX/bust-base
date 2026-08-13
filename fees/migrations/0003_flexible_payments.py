# Manually written migration for flexible fee payments.
# Makes Payment.invoice optional and adds Payment.student + Payment.description
# to support partial payments (any amount up to the balance) and payments not
# tied to an invoice (e.g. books).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fees', '0002_paystack_metadata_webhooklog_receipt'),
    ]

    operations = [
        migrations.AlterField(
            model_name='payment',
            name='invoice',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='payments', to='fees.invoice', verbose_name='invoice'),
        ),
        migrations.AddField(
            model_name='payment',
            name='student',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='payments', to='students.student', verbose_name='student'),
        ),
        migrations.AddField(
            model_name='payment',
            name='description',
            field=models.CharField(blank=True, default='', max_length=255, verbose_name='description'),
        ),
    ]
