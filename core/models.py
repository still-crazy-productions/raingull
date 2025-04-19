from django.db import models
from django.contrib.auth.models import User, AbstractUser
import uuid
from django.db.models.signals import post_save, post_delete, pre_delete
from django.dispatch import receiver
import json
import os
from django.utils import timezone
from django.apps import apps
from django.conf import settings
from .dynamic_models import create_dynamic_model, delete_dynamic_model
import importlib
import logging
from django.db import connection

logger = logging.getLogger(__name__)

class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    preferred_contact_method = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return self.user.username

class Plugin(models.Model):
    name = models.CharField(max_length=100, unique=True)
    friendly_name = models.CharField(max_length=100)
    version = models.CharField(max_length=20)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.friendly_name} ({self.name})"

    def get_manifest(self):
        try:
            manifest_path = os.path.join(settings.BASE_DIR, 'plugins', self.name, 'manifest.json')
            logger.info(f"Loading manifest from {manifest_path}")
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
                logger.info(f"Successfully loaded manifest for plugin {self.name}: {manifest}")
                return manifest
        except Exception as e:
            logger.error(f"Error loading manifest for plugin {self.name}: {e}", exc_info=True)
            return None

    def get_plugin_class(self):
        try:
            module_path = f"plugins.{self.name}.plugin"
            module = importlib.import_module(module_path)
            return module.Plugin
        except Exception as e:
            logger.error(f"Error loading plugin class for {self.name}: {e}")
            return None

    def get_plugin_instance(self, service_instance=None):
        try:
            plugin_class = self.get_plugin_class()
            if plugin_class:
                return plugin_class(service_instance)
            return None
        except Exception as e:
            logger.error(f"Error creating plugin instance for {self.name}: {e}")
            return None

    def get_message_model(self, service_instance, direction='incoming'):
        """Get the dynamic message model for this plugin and service instance"""
        try:
            manifest = self.get_manifest()
            if not manifest:
                return None

            # Get the appropriate schema based on direction
            schema = manifest.get('message_schemas', {}).get(direction, {})
            if not schema:
                return None

            # Create a unique model name
            model_name = f"{self.name}{direction.capitalize()}Message_{service_instance.id}"
            table_name = f"{self.name}_{direction}_{service_instance.id}"

            # Check if the model is already registered
            try:
                model = apps.get_model('core', model_name)
                if model:
                    print(f"Found existing model {model_name}")
                    return model
            except LookupError:
                # Model not found, create it
                pass

            # Create the model without trying to create the table
            print(f"Creating model for existing table {table_name}")
            return create_dynamic_model(model_name, table_name, schema, create_table=False)

        except Exception as e:
            print(f"Error creating message model for {self.name}: {e}")
            return None

class PluginInstance(models.Model):
    service_instance = models.OneToOneField('ServiceInstance', on_delete=models.CASCADE, related_name='plugin_instance')
    app_config = models.CharField(max_length=255)  # e.g., 'plugins.imap_plugin.apps.ImapPluginConfig'
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.service_instance.name} ({self.app_config})"

class Message(models.Model):
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    subject = models.CharField(max_length=255)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=50, default='queued')

    def __str__(self):
        return f"{self.subject} (status: {self.status})"

class ServiceInstance(models.Model):
    name = models.CharField(max_length=255)
    plugin = models.ForeignKey(Plugin, on_delete=models.CASCADE)
    incoming_enabled = models.BooleanField(default=True)
    outgoing_enabled = models.BooleanField(default=True)
    config = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.plugin.friendly_name})"

    def get_config_value(self, key):
        return self.config.get(key)

    def get_message_model(self, direction):
        return self.plugin.get_message_model(self, direction)

    def get_plugin_instance(self):
        """Get an instance of the plugin class for this service instance"""
        return self.plugin.get_plugin_instance(service_instance=self)

    def save(self, *args, **kwargs):
        # Get plugin capabilities from manifest
        manifest = self.plugin.get_manifest()
        if manifest:
            # If plugin doesn't support outgoing, force outgoing_enabled to False
            if not manifest.get('outgoing', False):
                self.outgoing_enabled = False
            # If plugin doesn't support incoming, force incoming_enabled to False
            if not manifest.get('incoming', False):
                self.incoming_enabled = False
        super().save(*args, **kwargs)

@receiver(post_save, sender=ServiceInstance)
def create_plugin_instance(sender, instance, created, **kwargs):
    """
    Creates a PluginInstance when a ServiceInstance is created.
    """
    if created:
        app_config = f'plugins.{instance.plugin.name}.apps.{instance.plugin.name.title()}PluginConfig'
        PluginInstance.objects.create(
            service_instance=instance,
            app_config=app_config,
            is_active=instance.incoming_enabled or instance.outgoing_enabled
        )

@receiver(post_save, sender=ServiceInstance)
def update_plugin_instance(sender, instance, **kwargs):
    """
    Updates the PluginInstance when a ServiceInstance is enabled/disabled.
    """
    try:
        plugin_instance = instance.plugin_instance
        plugin_instance.is_active = instance.incoming_enabled or instance.outgoing_enabled
        plugin_instance.save()
    except PluginInstance.DoesNotExist:
        pass

@receiver(post_save, sender=ServiceInstance)
def create_message_tables(sender, instance, created, **kwargs):
    """
    Creates dynamic tables for the service instance when it's created.
    """
    try:
        logger.info(f"Creating message tables for service instance {instance.name} (plugin: {instance.plugin.name})")
        manifest = instance.plugin.get_manifest()
        logger.info(f"Loaded manifest: {manifest}")
        
        if manifest and 'message_schemas' in manifest:
            logger.info(f"Found message schemas: {manifest['message_schemas']}")
            
            # Create incoming table if plugin supports incoming
            if manifest.get('incoming', False):
                incoming_schema = manifest['message_schemas'].get('incoming', {})
                if incoming_schema:
                    model_name = f"{instance.plugin.name}IncomingMessage_{instance.id}"
                    table_name = f"{instance.plugin.name}_incoming_{instance.id}"
                    logger.info(f"Creating incoming message table {table_name}")
                    
                    # Drop existing table if it exists
                    with connection.cursor() as cursor:
                        cursor.execute(f'DROP TABLE IF EXISTS "{table_name}"')
                        logger.info(f"Dropped existing table {table_name}")
                    
                    # Create new table
                    create_dynamic_model(model_name, table_name, incoming_schema)
                    logger.info(f"Created new table {table_name}")
            
            # Create outgoing table if plugin supports outgoing
            if manifest.get('outgoing', False):
                outgoing_schema = manifest['message_schemas'].get('outgoing', {})
                if outgoing_schema:
                    model_name = f"{instance.plugin.name}OutgoingMessage_{instance.id}"
                    table_name = f"{instance.plugin.name}_outgoing_{instance.id}"
                    logger.info(f"Creating outgoing message table {table_name}")
                    
                    # Drop existing table if it exists
                    with connection.cursor() as cursor:
                        cursor.execute(f'DROP TABLE IF EXISTS "{table_name}"')
                        logger.info(f"Dropped existing table {table_name}")
                    
                    # Create new table
                    create_dynamic_model(model_name, table_name, outgoing_schema)
                    logger.info(f"Created new table {table_name}")
                else:
                    logger.warning(f"No outgoing schema found in manifest for {instance.plugin.name}")
            else:
                logger.info(f"Plugin {instance.plugin.name} does not support outgoing messages")
        else:
            logger.warning(f"No message schemas found in manifest for {instance.plugin.name}")
    except Exception as e:
        logger.error(f"Error creating message tables for {instance.name}: {e}", exc_info=True)

@receiver(post_delete, sender=ServiceInstance)
def delete_message_tables(sender, instance, **kwargs):
    """
    Deletes the dynamic tables when the service instance is deleted.
    """
    try:
        manifest = instance.plugin.get_manifest()
        if manifest and 'message_schemas' in manifest:
            # Delete incoming table if plugin supports incoming
            if manifest.get('incoming', False):
                incoming_schema = manifest['message_schemas'].get('incoming', {})
                if incoming_schema:
                    model_name = f"{instance.plugin.name}IncomingMessage_{instance.id}"
                    table_name = f"{instance.plugin.name}_incoming_{instance.id}"
                    logger.info(f"Deleting incoming message table {table_name}")
                    delete_dynamic_model(model_name, table_name)
            
            # Delete outgoing table if plugin supports outgoing
            if manifest.get('outgoing', False):
                outgoing_schema = manifest['message_schemas'].get('outgoing', {})
                if outgoing_schema:
                    model_name = f"{instance.plugin.name}OutgoingMessage_{instance.id}"
                    table_name = f"{instance.plugin.name}_outgoing_{instance.id}"
                    logger.info(f"Deleting outgoing message table {table_name}")
                    delete_dynamic_model(model_name, table_name)
    except Exception as e:
        logger.error(f"Error deleting message tables for {instance.name}: {e}")

@receiver(pre_delete, sender=ServiceInstance)
def pre_delete_service_instance(sender, instance, **kwargs):
    """
    Handles cleanup tasks that need to happen before the ServiceInstance is deleted.
    """
    try:
        # Log the deletion
        logger.info(f"Deleting service instance {instance.name} (ID: {instance.id})")
        
        # Delete the plugin instance if it exists
        try:
            plugin_instance = instance.plugin_instance
            logger.info(f"Deleting plugin instance for {instance.name}")
            plugin_instance.delete()
        except PluginInstance.DoesNotExist:
            pass
            
        logger.info(f"Service instance {instance.name} cleanup completed")
    except Exception as e:
        logger.error(f"Error during pre-delete cleanup for {instance.name}: {e}")

class RaingullStandardMessage(models.Model):
    """Standardized message format for all incoming messages."""
    raingull_id = models.UUIDField(primary_key=True, editable=False)  # No default, will be copied from source
    source_service = models.ForeignKey(ServiceInstance, on_delete=models.CASCADE)
    source_message_id = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    body = models.TextField()
    snippet = models.CharField(max_length=200, blank=True)  # First 200 chars of body
    sender = models.CharField(max_length=255)
    recipients = models.JSONField()
    date = models.DateTimeField()
    headers = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['source_service', 'source_message_id']),
            models.Index(fields=['date']),
        ]

    def __str__(self):
        return f"{self.subject} ({self.sender})"

    @classmethod
    def create_standard_message(cls, source_service, source_message_id, subject, body, sender, recipients, date, headers, raingull_id):
        """Create a new standard message."""
        # Create snippet from first 200 chars of body
        snippet = body[:200].strip()
        
        return cls.objects.create(
            raingull_id=raingull_id,  # Use the provided raingull_id
            source_service=source_service,
            source_message_id=source_message_id,
            subject=subject,
            body=body,
            snippet=snippet,
            sender=sender,
            recipients=recipients,
            date=date,
            headers=headers
        )

class UserServiceActivation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    service_instance = models.ForeignKey(ServiceInstance, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)
    config = models.JSONField(default=dict)  # Store user-specific config like email address
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'service_instance')  # Each user can only activate a service instance once
        indexes = [
            models.Index(fields=['user', 'service_instance']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.service_instance.name}"

class RaingullUser(AbstractUser):
    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    groups = models.ManyToManyField(
        'auth.Group',
        verbose_name='groups',
        blank=True,
        help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.',
        related_name='raingull_user_set',
        related_query_name='raingull_user',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        verbose_name='user permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        related_name='raingull_user_set',
        related_query_name='raingull_user',
    )

class OutgoingMessageQueue(models.Model):
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('processing', 'Processing'),
        ('sent', 'Sent'),
        ('failed', 'Failed')
    ]
    
    raingull_message = models.ForeignKey('RaingullStandardMessage', on_delete=models.CASCADE)
    user = models.ForeignKey('RaingullUser', on_delete=models.CASCADE)
    service_instance = models.ForeignKey('ServiceInstance', on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued')
    service_message_id = models.CharField(max_length=255, null=True)  # Links to service-specific message
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True)
    error_message = models.TextField(null=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['user', 'service_instance']),
        ]
        db_table = 'core_outgoingmessagequeue'
