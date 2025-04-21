from django.db import models
from django.contrib.auth.models import AbstractUser
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

class User(AbstractUser):
    """Custom user model that extends Django's AbstractUser."""
    email = models.EmailField(blank=True, null=True)
    is_moderator = models.BooleanField(default=False)
    is_admin = models.BooleanField(default=False)
    web_login_enabled = models.BooleanField(default=False, help_text="Whether the user can log into the web interface")
    preferred_contact_method = models.CharField(max_length=50, blank=True, null=True)
    timezone = models.CharField(max_length=50, default='UTC')
    mfa_enabled = models.BooleanField(default=False)
    mfa_secret = models.CharField(max_length=32, blank=True)

    # Add related_name to avoid conflicts
    groups = models.ManyToManyField(
        'auth.Group',
        related_name='core_user_set',
        blank=True,
        help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.',
        verbose_name='groups',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='core_user_set',
        blank=True,
        help_text='Specific permissions for this user.',
        verbose_name='user permissions',
        db_table='core_user_permissions',
    )

    # Use username as the primary identifier
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = []

    class Meta:
        db_table = 'core_users'
        verbose_name = 'user'
        verbose_name_plural = 'users'

    def __str__(self):
        return self.username

    def can_manage_user(self, target_user):
        """Check if this user can manage the target user"""
        if self.is_admin:
            return True
        if self.is_moderator and not target_user.is_admin and not target_user.is_moderator:
            return True
        return False

    def can_manage_service(self, service_instance):
        """Check if this user can manage the service instance"""
        if self.is_admin:
            return True
        return service_instance.user == self

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
                logger.error(f"Could not get manifest for plugin {self.name}")
                return None

            # Get the appropriate schema based on direction
            schema = manifest.get('message_schemas', {}).get(direction, {})
            if not schema:
                logger.error(f"No {direction} message schema found in manifest for plugin {self.name}")
                return None

            # Create a unique model name and table name
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

            # Create the model
            logger.info(f"Creating model {model_name} for table {table_name}")
            model = create_dynamic_model(model_name, schema, table_name, app_label='core')
            return model

        except Exception as e:
            logger.error(f"Error creating message model for {self.name}: {str(e)}")
            return None

    class Meta:
        db_table = 'core_plugins'
        verbose_name = 'plugin'
        verbose_name_plural = 'plugins'

class Service(models.Model):
    name = models.CharField(max_length=255)
    plugin = models.ForeignKey(Plugin, on_delete=models.CASCADE)
    incoming_enabled = models.BooleanField(default=True)
    outgoing_enabled = models.BooleanField(default=True)
    config = models.JSONField()
    app_config = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'core_services'

    def __str__(self):
        return f"{self.name} ({self.plugin.friendly_name})"

    def get_config_value(self, key):
        return self.config.get(key)

    def get_message_model(self, direction):
        return self.plugin.get_message_model(self, direction)

    def get_plugin_instance(self):
        """Get an instance of the plugin class for this service"""
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

@receiver(post_save, sender=Service)
def create_message_tables(sender, instance, created, **kwargs):
    """
    Creates dynamic tables for storing messages when a service is created.
    """
    try:
        manifest = instance.plugin.get_manifest()
        if manifest and 'message_schemas' in manifest:
            # Create incoming table if plugin supports incoming
            if manifest.get('incoming', False):
                incoming_schema = manifest['message_schemas'].get('incoming', {})
                if incoming_schema:
                    model_name = f"{instance.plugin.name}IncomingMessage_{instance.id}"
                    table_name = f"{instance.plugin.name}_{instance.id}_in"
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
                    
                    # Create new table
                    create_dynamic_model(model_name, incoming_schema, table_name, app_label='core')
                    logger.info(f"Created new table {table_name}")
            
            # Create outgoing table if plugin supports outgoing
            if manifest.get('outgoing', False):
                outgoing_schema = manifest['message_schemas'].get('outgoing', {})
                if outgoing_schema:
                    model_name = f"{instance.plugin.name}OutgoingMessage_{instance.id}"
                    table_name = f"{instance.plugin.name}_{instance.id}_out"
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

@receiver(post_delete, sender=Service)
def delete_message_tables(sender, instance, **kwargs):
    """
    Deletes the dynamic tables when the service is deleted.
    """
    try:
        manifest = instance.plugin.get_manifest()
        if manifest and 'message_schemas' in manifest:
            # Delete incoming table if plugin supports incoming
            if manifest.get('incoming', False):
                incoming_schema = manifest['message_schemas'].get('incoming', {})
                if incoming_schema:
                    model_name = f"{instance.plugin.name}IncomingMessage_{instance.id}"
                    table_name = f"{instance.plugin.name}_{instance.id}_in"
                    logger.info(f"Deleting incoming message table {table_name}")
                    delete_dynamic_model(model_name, table_name)
            
            # Delete outgoing table if plugin supports outgoing
            if manifest.get('outgoing', False):
                outgoing_schema = manifest['message_schemas'].get('outgoing', {})
                if outgoing_schema:
                    model_name = f"{instance.plugin.name}OutgoingMessage_{instance.id}"
                    table_name = f"{instance.plugin.name}_{instance.id}_out"
                    logger.info(f"Deleting outgoing message table {table_name}")
                    delete_dynamic_model(model_name, table_name)
    except Exception as e:
        logger.error(f"Error deleting message tables for {instance.name}: {e}")

@receiver(pre_delete, sender=Service)
def pre_delete_service_instance(sender, instance, **kwargs):
    """
    Handles cleanup tasks that need to happen before the Service is deleted.
    """
    try:
        # Log the deletion
        logger.info(f"Deleting service instance {instance.name} (ID: {instance.id})")
        
        logger.info(f"Service instance {instance.name} cleanup completed")
    except Exception as e:
        logger.error(f"Error during pre-delete cleanup for {instance.name}: {e}")

class Message(models.Model):
    """Standardized message format for all incoming messages."""
    raingull_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    source_service = models.ForeignKey('Service', on_delete=models.CASCADE)
    source_message_id = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    body = models.TextField()
    snippet = models.CharField(max_length=200, blank=True)  # First 200 chars of body
    sender_email = models.CharField(max_length=255)
    recipients = models.JSONField()
    date = models.DateTimeField()
    headers = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'core_messages'
        indexes = [
            models.Index(fields=['source_service', 'source_message_id']),
            models.Index(fields=['date']),
        ]

    def __str__(self):
        return f"{self.subject} ({self.sender_email})"

    @classmethod
    def create_standard_message(cls, source_service, source_message_id, subject, body, sender_email, recipients, date, headers, raingull_id):
        """Create a new standard message."""
        # Create snippet from first 200 chars of body
        snippet = body[:200].strip()
        
        return cls.objects.create(
            raingull_id=raingull_id,
            source_service=source_service,
            source_message_id=source_message_id,
            subject=subject,
            body=body,
            snippet=snippet,
            sender_email=sender_email,
            recipients=recipients,
            date=date,
            headers=headers
        )

class UserService(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    service_instance = models.ForeignKey('Service', on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)
    config = models.JSONField(default=dict)  # Store user-specific config like email address
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'service_instance')  # Each user can only activate a service instance once
        db_table = 'core_user_services'

    def __str__(self):
        return f"{self.user.username} - {self.service_instance.name}"

class MessageQueue(models.Model):
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('processing', 'Processing'),
        ('sent', 'Sent'),
        ('failed', 'Failed')
    ]
    
    # Foreign key to the original message - allows direct access to message data
    raingull_message = models.ForeignKey('Message', on_delete=models.CASCADE)
    
    # The tracking ID that follows the message through its lifecycle
    # This is the same value as raingull_message.raingull_id
    raingull_id = models.UUIDField()
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    service_instance = models.ForeignKey('Service', on_delete=models.CASCADE)
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
        db_table = 'core_message_queue'

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
    service_instance = models.ForeignKey('Service', on_delete=models.SET_NULL, null=True)
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

class ServiceMessageTemplate(models.Model):
    class MessageType(models.TextChoices):
        INVITATION = 'invitation', 'Invitation'
        ERROR = 'error', 'Error'
        NOTIFICATION = 'notification', 'Notification'
    
    service_instance = models.ForeignKey('Service', on_delete=models.CASCADE)
    message_type = models.CharField(max_length=20, choices=MessageType.choices)
    subject = models.CharField(max_length=200)
    message = models.TextField()
    activation_url = models.URLField(null=True, blank=True, help_text="URL for the activation link. Use {token} as a placeholder for the activation token.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('service_instance', 'message_type')
        db_table = 'core_servicemessagetemplate'

    def __str__(self):
        return f"{self.service_instance.name} - {self.get_message_type_display()}"

    def get_message_with_token(self, token):
        """Replace placeholders in the message with actual values."""
        message = self.message
        if self.activation_url:
            message = message.replace('{activation_url}', self.get_activation_url(token))
        return message

    def get_activation_url(self, token):
        """Get the activation URL with the token."""
        if self.activation_url:
            return self.activation_url.format(token=token)
        return None

class SystemMessageTemplate(models.Model):
    class MessageType(models.TextChoices):
        PASSWORD_RESET = 'password_reset', 'Password Reset'
        ADMIN_NOTIFICATION = 'admin_notification', 'Admin Notification'
        SYSTEM_ERROR = 'system_error', 'System Error'
    
    message_type = models.CharField(max_length=20, choices=MessageType.choices, unique=True)
    subject = models.CharField(max_length=200)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'core_systemmessagetemplate'

    def __str__(self):
        return self.get_message_type_display()

    def get_message_with_values(self, **kwargs):
        """Replace placeholders in the message with actual values."""
        message = self.message
        for key, value in kwargs.items():
            message = message.replace(f"{{{key}}}", str(value))
        return message
