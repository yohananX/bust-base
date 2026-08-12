# Manually written migration for Paystack payment metadata.
# Adds online-payment metadata fields to Payment, plus WebhookLog and FeeReceipt models.

from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fees', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='authorization_url',
            field=models.URLField(blank=True, max_length=500, verbose_name='authorization url'),
        ),
        migrations.AddField(
            model_name='payment',
            name='access_code',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='access code'),
        ),
        migrations.AddField(
            model_name='payment',
            name='fees_charged',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10, verbose_name='fees charged'),
        ),
        migrations.AddField(
            model_name='payment',
            name='channel',
            field=models.CharField(blank=True, default='', max_length=30, verbose_name='channel'),
        ),
        migrations.AddField(
            model_name='payment',
            name='currency',
            field=models.CharField(default='NGN', max_length=3, verbose_name='currency'),
        ),
        migrations.AddField(
            model_name='payment',
            name='paid_by_email',
            field=models.EmailField(blank=True, default='', verbose_name='paid by email'),
        ),
        migrations.AddField(
            model_name='payment',
            name='paid_by_name',
            field=models.CharField(blank=True, default='', max_length=200, verbose_name='paid by name'),
        ),
        migrations.AddField(
            model_name='payment',
            name='paid_by_phone',
            field=models.CharField(blank=True, default='', max_length=20, verbose_name='paid by phone'),
        ),
        migrations.AddField(
            model_name='payment',
            name='card_last4',
            field=models.CharField(blank=True, default='', max_length=4, verbose_name='card last 4'),
        ),
        migrations.AddField(
            model_name='payment',
            name='card_brand',
            field=models.CharField(blank=True, default='', max_length=50, verbose_name='card brand'),
        ),
        migrations.AddField(
            model_name='payment',
            name='bank_name',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='bank name'),
        ),
        migrations.AddField(
            model_name='payment',
            name='initiated_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='initiated at'),
        ),
        migrations.AddField(
            model_name='payment',
            name='verified_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='verified at'),
        ),
        migrations.AddField(
            model_name='payment',
            name='webhook_processed',
            field=models.BooleanField(default=False, verbose_name='webhook processed'),
        ),
        migrations.AddField(
            model_name='payment',
            name='webhook_payload',
            field=models.JSONField(blank=True, default=dict, verbose_name='webhook payload'),
        ),
        migrations.CreateModel(
            name='WebhookLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('school', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.school', verbose_name='school')),
                ('event', models.CharField(max_length=50, verbose_name='event')),
                ('payload', models.JSONField(verbose_name='payload')),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True, verbose_name='ip address')),
                ('processed', models.BooleanField(default=False, verbose_name='processed')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='created at')),
            ],
            options={
                'verbose_name': 'webhook log',
                'verbose_name_plural': 'webhook logs',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='FeeReceipt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('school', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.school', verbose_name='school')),
                ('receipt_number', models.CharField(max_length=50, verbose_name='receipt number')),
                ('payment', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='receipt', to='fees.payment', verbose_name='payment')),
                ('issued_at', models.DateTimeField(auto_now_add=True, verbose_name='issued at')),
            ],
            options={
                'verbose_name': 'fee receipt',
                'verbose_name_plural': 'fee receipts',
                'ordering': ['-issued_at'],
                'unique_together': {('school', 'receipt_number')},
            },
        ),
    ]