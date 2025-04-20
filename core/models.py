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
                    logger.info(f"Found existing model {model_name}")
                    return model
            except LookupError:
                # Model not found, create it
                pass

            # Create the model without trying to create the table
            logger.info(f"Creating model for existing table {table_name}")
            return create_dynamic_model(model_name, schema, table_name, app_label='core')

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
    Creates dynamic tables for storing messages when a service instance is created.
    """
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
                    
                    # Drop existing table if it exists
                    with connection.cursor() as cursor:
                        cursor.execute(f'DROP TABLE IF EXISTS "{table_name}"')
                        logger.info(f"Dropped existing table {table_name}")
                    
                    # Add message_id field with unique constraint if not present
                    if 'message_id' not in incoming_schema:
                        incoming_schema['message_id'] = {
                            'type': 'CharField',
                            'max_length': 255,
                            'unique': True,
                            'required': True,
                            'help_text': 'Unique identifier for the message'
                        }
                    else:
                        incoming_schema['message_id']['unique'] = True
                    
                    # Add raingull_id field with unique constraint if not present
                    if 'raingull_id' not in incoming_schema:
                        incoming_schema['raingull_id'] = {
                            'type': 'UUIDField',
                            'unique': True,
                            'required': True,
                            'help_text': 'Unique identifier for the message in Raingull system'
                        }
                    else:
                        incoming_schema['raingull_id']['unique'] = True
                    
                    # Create new table
                    create_dynamic_model(model_name, incoming_schema, table_name, app_label='core')
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
                    
                    # Add raingull_id field with unique constraint if not present
                    if 'raingull_id' not in outgoing_schema:
                        outgoing_schema['raingull_id'] = {
                            'type': 'UUIDField',
                            'unique': True,
                            'required': True,
                            'help_text': 'Unique identifier for the message in Raingull system'
                        }
                    else:
                        outgoing_schema['raingull_id']['unique'] = True
                    
                    # Create new table
                    create_dynamic_model(model_name, outgoing_schema, table_name, app_label='core')
                    logger.info(f"Created new table {table_name}")
                    
    except Exception as e:
        logger.error(f"Error creating message tables for {instance.name}: {str(e)}")
        raise

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
    raingull_id = models.UUIDField(primary_key=True)  # Make raingull_id the primary key
    source_service = models.ForeignKey('ServiceInstance', on_delete=models.CASCADE)
    source_message_id = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    body = models.TextField()
    snippet = models.CharField(max_length=200, blank=True)  # First 200 chars of body
    sender = models.CharField(max_length=255)
    recipients = models.JSONField()
    date = models.DateTimeField()
    headers = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'core_raingullstandardmessage'
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
    service_instance = models.ForeignKey('ServiceInstance', on_delete=models.CASCADE)
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
    class UserRole(models.TextChoices):
        MEMBER = 'member', 'Member'
        MODERATOR = 'moderator', 'Moderator'
        ADMIN = 'admin', 'Admin'

    class AccountStatus(models.TextChoices):
        ACTIVE = 'active', 'Active'
        DEACTIVATED = 'deactivated', 'Deactivated'
        BANNED = 'banned', 'Banned'

    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.MEMBER,
        help_text="User's role in the system"
    )
    
    status = models.CharField(
        max_length=20,
        choices=AccountStatus.choices,
        default=AccountStatus.ACTIVE,
        help_text="Account status"
    )
    
    full_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="User's full name"
    )
    
    timezone = models.CharField(
        max_length=50,
        default='UTC',
        help_text="User's preferred timezone"
    )
    
    mfa_enabled = models.BooleanField(
        default=False,
        help_text="Whether MFA is enabled for this user"
    )
    
    mfa_secret = models.CharField(
        max_length=32,
        blank=True,
        help_text="MFA secret key"
    )
    
    last_login_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address of last login"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the account was created"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="When the account was last updated"
    )

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    @property
    def is_moderator(self):
        return self.role in [self.UserRole.MODERATOR, self.UserRole.ADMIN]

    @property
    def is_admin(self):
        return self.role == self.UserRole.ADMIN

    def can_manage_user(self, target_user):
        """Check if this user can manage the target user"""
        if self.is_admin:
            return True
        if self.is_moderator and target_user.role == self.UserRole.MEMBER:
            return True
        return False

    def can_manage_service(self, service_instance):
        """Check if this user can manage the service instance"""
        if self.is_admin:
            return True
        return service_instance.user == self

class OutgoingMessageQueue(models.Model):
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('processing', 'Processing'),
        ('sent', 'Sent'),
        ('failed', 'Failed')
    ]
    
    # Foreign key to the original message - allows direct access to message data
    raingull_message = models.ForeignKey('RaingullStandardMessage', on_delete=models.CASCADE)
    
    # The tracking ID that follows the message through its lifecycle
    # This is the same value as raingull_message.raingull_id
    raingull_id = models.UUIDField()
    
    user = models.ForeignKey('RaingullUser', on_delete=models.CASCADE)
    service_instance = models.ForeignKey('ServiceInstance', on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued')
    service_message_id = models.CharField(max_length=255, null=True, blank=True)  # Original service's message ID (e.g., IMAP message ID)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True)
    error_message = models.TextField(null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['user', 'service_instance']),
            models.Index(fields=['raingull_id']),  # Add index for raingull_id
        ]
        db_table = 'core_outgoingmessagequeue'

class AuditLog(models.Model):
    EVENT_TYPE_CHOICES = [
        ('info', 'Information'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('debug', 'Debug')
    ]
    
    STATUS_CHOICES = [
        ('success', 'Success'),
        ('error', 'Error'),
        ('warning', 'Warning')
    ]
    
    timestamp = models.DateTimeField(auto_now_add=True)
    service_instance = models.ForeignKey(ServiceInstance, on_delete=models.SET_NULL, null=True)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    details = models.TextField()
    
    class Meta:
        indexes = [
            models.Index(fields=['timestamp']),
            models.Index(fields=['service_instance']),
            models.Index(fields=['event_type']),
            models.Index(fields=['status']),
        ]
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.timestamp} - {self.event_type} - {self.status}"
