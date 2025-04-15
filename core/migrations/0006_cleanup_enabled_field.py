from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_serviceinstance'),
    ]

    operations = [
        # This migration is a no-op since we're already using 'enabled'
        # It's here to document that we've reviewed and confirmed the field name
    ] 