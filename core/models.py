from django.db import models
from django.contrib.auth.models import User
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

logger = logging.getLogger(__name__)

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
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
            with open(manifest_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading manifest for plugin {self.name}: {e}")
            return None

    def get_plugin_class(self):
        try:
            module_path = f"plugins.{self.name}.plugin"
            module = importlib.import_module(module_path)
            return module.Plugin
        except Exception as e:
            logger.error(f"Error loading plugin class for {self.name}: {e}")
            return None

    def get_plugin_instance(self):
        try:
            plugin_class = self.get_plugin_class()
            if plugin_class:
                return plugin_class(self)
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

            # Create the dynamic model
            return create_dynamic_model(model_name, table_name, schema)
        except Exception as e:
            logger.error(f"Error creating message model for {self.name}: {e}")
            return None

class PluginInstance(models.Model):
    service_instance = models.OneToOneField('ServiceInstance', on_delete=models.CASCADE, related_name='plugin_instance')
    app_config = models.CharField(max_length=255)  # e.g., 'plugins.imap_plugin.apps.ImapPluginConfig'
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.service_instance.name} ({self.app_config})"

class Message(models.Model):
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    subject = models.CharField(max_length=255)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=50, default='queued')

    def __str__(self):
        return f"{self.subject} (status: {self.status})"

class RainGullStandardMessage(models.Model):
    raingull_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    
    processing_status = models.CharField(max_length=20, choices=[
        ('new', 'New'),
        ('queued', 'Queued'),
        ('sending', 'Sending'),
        ('distributed', 'Distributed'),
        ('failed', 'Failed'),
    ], default='new')
    
    origin_service_id = models.CharField(max_length=100)
    message_type = models.CharField(max_length=20, choices=[
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('telegram', 'Telegram'),
        ('discord', 'Discord'),
        ('signal', 'Signal'),
        ('whatsapp', 'WhatsApp'),
        ('slack', 'Slack'),
        ('teams', 'Teams'),
        ('other', 'Other'),
    ], default='other')

    sent_timestamp = models.DateTimeField(null=True, blank=True)
    received_timestamp = models.DateTimeField(auto_now_add=True)
    processed_timestamp = models.DateTimeField(auto_now_add=True)

    original_sender = models.CharField(max_length=255)
    original_sender_name = models.CharField(max_length=255, null=True, blank=True)
    original_recipient_list = models.JSONField(null=True, blank=True)

    member_display_name = models.CharField(max_length=255, null=True, blank=True)

    subject = models.CharField(max_length=255, null=True, blank=True)
    snippet = models.CharField(max_length=255, null=True, blank=True)
    message_body = models.TextField()

    additional_headers = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "rg_standard_messages"

    def __str__(self):
        return f"{self.raingull_id} | {self.message_type} | {self.processing_status}"

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
    if created:
        try:
            manifest = instance.plugin.get_manifest()
            if manifest and 'message_schemas' in manifest:
                # Create incoming table if plugin supports incoming
                if manifest.get('incoming', False):
                    incoming_schema = manifest['message_schemas'].get('incoming', {})
                    if incoming_schema:
                        model_name = f"{instance.plugin.name}IncomingMessage_{instance.id}"
                        table_name = f"{instance.plugin.name}_incoming_{instance.id}"
                        logger.info(f"Creating incoming message table {table_name}")
                        create_dynamic_model(model_name, table_name, incoming_schema)
                
                # Create outgoing table if plugin supports outgoing
                if manifest.get('outgoing', False):
                    outgoing_schema = manifest['message_schemas'].get('outgoing', {})
                    if outgoing_schema:
                        model_name = f"{instance.plugin.name}OutgoingMessage_{instance.id}"
                        table_name = f"{instance.plugin.name}_outgoing_{instance.id}"
                        logger.info(f"Creating outgoing message table {table_name}")
                        create_dynamic_model(model_name, table_name, outgoing_schema)
        except Exception as e:
            logger.error(f"Error creating message tables for {instance.name}: {e}")

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
