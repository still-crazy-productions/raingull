"""
Base Plugin Interface for Raingull

This module defines the base interface that all Raingull plugins must implement.
The interface provides a standardized way for plugins to interact with the Raingull core system.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from django.utils import timezone
from core.models import Message, Service
import logging

logger = logging.getLogger(__name__)

class BasePlugin(ABC):
    """
    Base class for all Raingull plugins.
    
    This abstract base class defines the interface that all Raingull plugins must implement.
    It provides default implementations for common functionality while requiring plugins
    to implement service-specific behavior.
    
    Attributes:
        service (Service): The service instance this plugin is associated with
        config (Dict): The service configuration
    """
    
    def __init__(self, service: Service):
        """
        Initialize the plugin with a service instance.
        
        Args:
            service (Service): The service instance this plugin is associated with
        """
        self.service = service
        self.config = service.config

    @abstractmethod
    def get_manifest(self) -> Dict[str, Any]:
        """
        Return the plugin's manifest.
        
        The manifest defines the plugin's capabilities, configuration schema,
        and formatting preferences.
        
        Returns:
            Dict containing the plugin manifest with the following structure:
            {
                "name": str,                    # Plugin identifier (e.g., "imap")
                "friendly_name": str,           # Human-readable name (e.g., "IMAP Email")
                "version": str,                 # Plugin version
                "description": str,             # Plugin description
                "capabilities": {
                    "incoming": bool,           # Whether plugin supports incoming messages
                    "outgoing": bool            # Whether plugin supports outgoing messages
                },
                "formatting": {
                    "header_template": str,     # Template for message attribution
                    "message_format": str       # Default message format (e.g., "markdown")
                },
                "config_schema": {              # Configuration field definitions
                    "field_name": {
                        "type": str,            # Field type (string, integer, boolean)
                        "required": bool,       # Whether field is required
                        "default": Any,         # Default value
                        "help_text": str        # Field description
                    }
                }
            }
        """
        pass

    @abstractmethod
    def fetch_messages(self) -> List[Dict[str, Any]]:
        """
        Fetch new messages from the service.
        
        This method should retrieve new messages from the service and return them
        in a standardized format. The method is only called for plugins that support
        incoming messages.
        
        Returns:
            List of message dictionaries with the following structure:
            [{
                "service_message_id": str,      # Original message ID from service
                "subject": str,                 # Message subject
                "sender": str,                  # Message sender
                "recipient": str,               # Message recipient (if available)
                "timestamp": datetime,          # Message timestamp
                "payload": {                    # Message content and metadata
                    "content": str,             # Message body
                    "attachments": List,        # List of attachments
                    "metadata": Dict           # Service-specific metadata
                }
            }]
        """
        pass

    @abstractmethod
    def send_message(self, message: Message) -> bool:
        """
        Send a message through the service.
        
        This method should send a message through the service and return whether
        the operation was successful. The method is only called for plugins that
        support outgoing messages.
        
        Args:
            message (Message): The message to send
            
        Returns:
            bool: True if message was sent successfully, False otherwise
        """
        pass

    @abstractmethod
    def test_connection(self) -> bool:
        """
        Test the connection to the service.
        
        This method should verify that the plugin can connect to the service
        using the current configuration.
        
        Returns:
            bool: True if connection was successful, False otherwise
        """
        pass

    def standardize_payload(self, raw_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert service-specific payload to Raingull standard format.
        
        This method provides a default implementation for converting service-specific
        message payloads to the Raingull standard format. Plugins can override this
        method to provide custom conversion logic.
        
        Args:
            raw_payload (Dict): The service-specific message payload
            
        Returns:
            Dict containing the standardized payload with the following structure:
            {
                "content": str,                 # Message body
                "attachments": List,            # List of attachments
                "metadata": {                   # Message metadata
                    "format": str,              # Message format (e.g., "markdown")
                    "original_format": str      # Original message format
                }
            }
        """
        manifest = self.get_manifest()
        return {
            'content': raw_payload.get('body', ''),
            'attachments': raw_payload.get('attachments', []),
            'metadata': {
                'format': manifest.get('formatting', {}).get('message_format', 'text'),
                'original_format': raw_payload.get('format', 'text')
            }
        }

    def format_for_outgoing(self, message: Message) -> Dict[str, Any]:
        """
        Format a Raingull message for outgoing delivery.
        
        This method provides a default implementation for formatting Raingull messages
        for outgoing delivery. Plugins can override this method to provide custom
        formatting logic.
        
        Args:
            message (Message): The message to format
            
        Returns:
            Dict containing the formatted message with the following structure:
            {
                "content": str,                 # Formatted message body
                "attachments": List,            # List of attachments
                "format": str                   # Message format
            }
        """
        manifest = self.get_manifest()
        header_template = manifest.get('formatting', {}).get('header_template', '')
        
        # Add attribution header
        content = message.payload.get('content', '')
        if header_template:
            content = header_template.format(
                user=message.sender or 'Unknown User'
            ) + content

        return {
            'content': content,
            'attachments': message.payload.get('attachments', []),
            'format': manifest.get('formatting', {}).get('message_format', 'text')
        } 