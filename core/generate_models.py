import os
import logging
from django.apps import apps
from django.conf import settings
from django.db import models
from django.db.models import Model, JSONField
from django.db.models.fields import CharField, TextField, DateTimeField, BooleanField
from django.db.models.fields.related import ForeignKey, ManyToManyField
from django.utils import timezone

logger = logging.getLogger(__name__)

def generate_models_file():
    """
    Generate a models.py file for plugin models based on the current services.
    This allows for dynamic model creation for plugins.
    """
    try:
        # Get all enabled services
        Service = apps.get_model('core', 'Service')
        services = Service.objects.filter(enabled=True)
        
        if not services.exists():
            logger.info("No enabled services found, skipping model generation")
            return
            
        # Start building the models.py content
        content = [
            "from django.db import models",
            "from django.utils import timezone",
            "from core.models import Service",
            "",
            "# This file is auto-generated. Do not edit manually.",
            "# Changes will be overwritten when services are modified.",
            "",
        ]
        
        # Generate model for each service
        for service in services:
            model_name = f"{service.name}Message"
            content.extend([
                f"class {model_name}(models.Model):",
                "    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='%(class)s_messages')",
                "    subject = models.CharField(max_length=255)",
                "    body = models.TextField()",
                "    sender = models.CharField(max_length=255)",
                "    recipients = models.JSONField()",
                "    metadata = models.JSONField(default=dict)",
                "    created_at = models.DateTimeField(default=timezone.now)",
                "    processed_at = models.DateTimeField(null=True, blank=True)",
                "    status = models.CharField(max_length=20, default='pending')",
                "",
                "    class Meta:",
                "        db_table = f'plugin_{service.name.lower()}_message'",
                "",
                "    def __str__(self):",
                "        return f'{self.service.name} - {self.subject}'",
                "",
            ])
        
        # Write the file
        models_path = os.path.join(settings.BASE_DIR, 'core', 'plugin_models.py')
        with open(models_path, 'w') as f:
            f.write('\n'.join(content))
            
        logger.info(f"Successfully generated plugin models file at {models_path}")
        
    except Exception as e:
        logger.error(f"Error generating models file: {str(e)}")
        raise 