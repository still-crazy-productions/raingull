# Generated by Django 5.2 on 2025-04-14 23:55

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_serviceinstance'),
    ]

    operations = [
        migrations.RenameField(
            model_name='plugin',
            old_name='enabled',
            new_name='active',
        ),
        migrations.RemoveField(
            model_name='plugin',
            name='created_at',
        ),
        migrations.RemoveField(
            model_name='plugin',
            name='description',
        ),
        migrations.AddField(
            model_name='plugin',
            name='friendly_name',
            field=models.CharField(default='Default Plugin', max_length=100),
            preserve_default=False,
        ),
    ]
