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
import logging
import importlib
from core.plugin_base import BasePlugin
from abc import abstractmethod
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

class PluginInterface(BasePlugin):
    """Interface class that extends BasePlugin with model-specific functionality.
    
    This class provides the connection between the abstract BasePlugin and the
    concrete model implementations.
    """
    
    def __init__(self, service: 'Service'):
        """Initialize the plugin with a service instance.
        
        Args:
            service (Service): The service instance this plugin is associated with
        """
        super().__init__(service)
        self.config = service.config
        
    def get_manifest(self) -> Dict[str, Any]:
        """Get the plugin manifest.
        
        Returns:
            dict: The plugin manifest
        """
        return self._get_manifest()
        
    def fetch_messages(self) -> List[Dict[str, Any]]:
        """Fetch messages from the service.
        
        Returns:
            list: List of messages fetched from the service
        """
        return self._fetch_messages()
        
    def send_message(self, message: 'Message') -> bool:
        """Send a message through the service.
        
        Args:
            message (Message): The message to send
            
        Returns:
            bool: True if the message was sent successfully, False otherwise
        """
        # Convert Message model to payload dict
        message_payload = {
            'content': message.payload.get('content', ''),
            'attachments': message.payload.get('attachments', []),
            'sender': message.sender,
            'recipient': message.recipient,
            'subject': message.subject,
            'metadata': message.payload.get('metadata', {})
        }
        
        # Format the message for outgoing delivery
        formatted_payload = self.format_for_outgoing(message_payload)
        
        # Send the message
        return self._send_message(formatted_payload)
        
    def test_connection(self) -> bool:
        """Test the connection to the service.
        
        Returns:
            bool: True if the connection is successful, False otherwise
        """
        return self._test_connection()
        
    @abstractmethod
    def _get_manifest(self) -> Dict[str, Any]:
        """Internal method to get the plugin manifest."""
        pass
        
    @abstractmethod
    def _fetch_messages(self) -> List[Dict[str, Any]]:
        """Internal method to fetch messages."""
        pass
        
    @abstractmethod
    def _send_message(self, message_payload: Dict[str, Any]) -> bool:
        """Internal method to send a message.
        
        Args:
            message_payload (Dict): The message payload to send
            
        Returns:
            bool: True if the message was sent successfully, False otherwise
        """
        pass
        
    @abstractmethod
    def _test_connection(self) -> bool:
        """Internal method to test the connection."""
        pass

def get_plugin_models():
    """Get all plugin models"""
    # Since we're using a unified Message model, we can just return Message
    return [Message]

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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
    """Plugin model for storing plugin information"""
    name = models.CharField(max_length=100, unique=True)
    friendly_name = models.CharField(max_length=100)
    version = models.CharField(max_length=20)
    manifest = models.JSONField()
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.friendly_name} ({self.name}) v{self.version}"

    def get_manifest(self):
        try:
            manifest_path = os.path.join(settings.BASE_DIR, 'plugins', self.name, 'manifest.json')
            logger.debug(f"Loading manifest from {manifest_path}")
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
                logger.debug(f"Successfully loaded manifest for plugin {self.name}: {manifest}")
                return manifest
        except Exception as e:
            logger.error(f"Error loading manifest for plugin {self.name}: {e}", exc_info=True)
            return None

    def get_plugin_class(self):
        """Get the plugin class for this plugin.
        
        Returns:
            The plugin class if found, None otherwise
        """
        try:
            module_path = f'plugins.{self.name}.plugin'
            logger.debug(f"Loading plugin class from {module_path}")
            
            # Check if the module exists
            import importlib.util
            spec = importlib.util.find_spec(module_path)
            if spec is None:
                logger.error(f"Module {module_path} not found in Python path")
                return None
                
            logger.debug(f"Found module spec: {spec}")
            
            # Import the module
            module = importlib.import_module(module_path)
            logger.debug(f"Imported module: {module}")
            
            # Look for a class that is a subclass of PluginInterface
            plugin_class = None
            for name, obj in module.__dict__.items():
                if (isinstance(obj, type) and 
                    issubclass(obj, PluginInterface) and 
                    obj != PluginInterface and 
                    obj.__module__ == module_path):
                    plugin_class = obj
                    logger.debug(f"Found plugin class {name} in {module_path}")
                    break
                    
            if not plugin_class:
                logger.error(f"No plugin class found in {module_path}")
                return None
                
            # Verify the plugin class implements all required methods
            required_methods = ['get_manifest', 'fetch_messages', 'send_message', 'test_connection']
            missing_methods = [method for method in required_methods if not hasattr(plugin_class, method)]
            if missing_methods:
                logger.error(f"Plugin class {plugin_class.__name__} is missing required methods: {', '.join(missing_methods)}")
                return None
                
            logger.debug(f"Successfully loaded plugin class {plugin_class.__name__}")
            return plugin_class
            
        except ImportError as e:
            logger.error(f"Error importing plugin module {module_path}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error loading plugin class: {str(e)}", exc_info=True)
            return None

    def get_plugin_instance(self, service_instance=None):
        try:
            plugin_class = self.get_plugin_class()
            if plugin_class:
                return plugin_class(service=service_instance)
            return None
        except Exception as e:
            logger.error(f"Error getting plugin instance: {str(e)}")
            return None

    def get_service_config(self, service_instance):
        """Get the service configuration for a plugin instance."""
        if not service_instance:
            raise ValueError("Service instance is required")
        return service_instance.config

    def get_user_config(self, service_instance):
        """Get the user configuration for a plugin instance."""
        if not service_instance:
            raise ValueError("Service instance is required")
        return service_instance.app_config

    def get_message_model(self, service_instance, direction='incoming'):
        """Get the message model for this plugin and service instance"""
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

            # Return the unified Message model
            return Message

        except Exception as e:
            logger.error(f"Error getting message model for {self.name}: {str(e)}")
            return None

    class Meta:
        db_table = 'core_plugins'
        verbose_name = 'plugin'
        verbose_name_plural = 'plugins'

class Service(models.Model):
    """Service model for storing service configurations"""
    name = models.CharField(max_length=100)
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
        return f"{self.name} ({self.plugin.name})"

    def get_config_value(self, key):
        """Get a specific configuration value."""
        return self.config.get(key)

    def get_plugin_instance(self):
        """Get an instance of the plugin for this service."""
        return self.plugin.get_plugin_instance(service_instance=self)

class Message(models.Model):
    """Unified message model for all messages in the system."""
    raingull_id = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)
    service = models.ForeignKey('Service', on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    direction = models.CharField(
        max_length=10, 
        choices=[('incoming', 'Incoming'), ('outgoing', 'Outgoing')], 
        db_index=True
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ('new', 'New'),
            ('processed', 'Processed'),
            ('formatted', 'Formatted'),
            ('queued', 'Queued'),
            ('sent', 'Sent'),
            ('failed', 'Failed')
        ],
        default='new',
        db_index=True
    )
    service_message_id = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    subject = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    sender = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    recipient = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    timestamp = models.DateTimeField(blank=True, null=True, db_index=True)
    payload = models.JSONField(default=dict)
    attachments = models.JSONField(default=list, blank=True)
    retry_count = models.IntegerField(default=0)
    last_retry_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    is_urgent = models.BooleanField(default=False)
    source_service = models.ForeignKey('Service', on_delete=models.SET_NULL, null=True, blank=True, related_name='source_messages')

    # Processing step tracking
    processing_step = models.CharField(
        max_length=20,
        choices=[
            ('ingested', 'Ingested'),  # Step 1
            ('standardized', 'Standardized'),  # Step 2
            ('formatted', 'Formatted'),  # Step 3
            ('queued', 'Queued'),  # Step 4
            ('sent', 'Sent'),  # Step 5
        ],
        null=True,
        blank=True,
        help_text="Last processing step that handled this message"
    )
    
    # Processing metrics
    step_processing_time = models.JSONField(
        default=dict,
        help_text="Time spent in each processing step (in seconds)"
    )

    class Meta:
        db_table = 'core_messages'
        indexes = [
            models.Index(fields=['service', 'direction', 'status']),
            models.Index(fields=['timestamp']),
            models.Index(fields=['service_message_id']),
        ]

    def __str__(self):
        return f"{self.direction.title()} message via {self.service.name} [{self.status}]"

    def increment_retry(self):
        """Increment retry count and update last retry timestamp."""
        self.retry_count += 1
        self.last_retry_at = timezone.now()
        self.save()

class MessageQueue(models.Model):
    """Queue for managing message processing"""
    message = models.ForeignKey('Message', on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    service = models.ForeignKey('Service', on_delete=models.CASCADE)
    priority = models.IntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('completed', 'Completed'),
            ('failed', 'Failed')
        ],
        default='pending'
    )
    retry_count = models.IntegerField(default=0)
    last_retry_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'core_message_queue'
        indexes = [
            models.Index(fields=['status', 'priority', 'created_at']),
        ]

    def __str__(self):
        return f"Queue entry for {self.message}"

    def increment_retry(self):
        """Increment the retry count and update last_retry_at"""
        self.retry_count += 1
        self.last_retry_at = timezone.now()
        self.save()

class UserService(models.Model):
    """User-specific service configuration."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    service = models.ForeignKey('Service', on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)
    config = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'service')
        db_table = 'core_user_services'

    def __str__(self):
        return f"{self.user.username} - {self.service.name}"

class AuditLog(models.Model):
    """Audit log model for tracking system events"""
    event_type = models.CharField(max_length=50)
    status = models.CharField(max_length=20)
    details = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'core_audit_log'

    def __str__(self):
        return f"{self.event_type} - {self.status}"

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
