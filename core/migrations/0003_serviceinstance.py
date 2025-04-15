# Generated by Django 5.2 on 2025-04-13 23:57

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_raingullstandardmessage'),
    ]

    operations = [
        migrations.CreateModel(
            name='ServiceInstance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('enabled', models.BooleanField(default=True)),
                ('configuration', models.JSONField(blank=True, default=dict)),
                ('plugin', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.plugin')),
            ],
        ),
    ]
