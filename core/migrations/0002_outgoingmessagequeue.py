# Generated by Django 5.2 on 2025-04-17 01:09

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='OutgoingMessageQueue',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('processing', 'Processing'), ('sent', 'Sent'), ('failed', 'Failed')], default='queued', max_length=20)),
                ('service_message_id', models.CharField(max_length=255, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('processed_at', models.DateTimeField(null=True)),
                ('error_message', models.TextField(null=True)),
                ('raingull_message', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.raingullstandardmessage')),
                ('service_instance', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.serviceinstance')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'core_outgoingmessagequeue',
                'indexes': [models.Index(fields=['status', 'created_at'], name='core_outgoi_status_523452_idx'), models.Index(fields=['user', 'service_instance'], name='core_outgoi_user_id_7bda3b_idx')],
            },
        ),
    ]
