"""
Base Plugin Interface for Raingull

This module defines the base interface that all Raingull plugins must implement.
The interface provides a standardized way for plugins to interact with the Raingull core system.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)

class BasePlugin(ABC):
    """Base class for all plugins.
    
    This is an abstract base class that defines the interface that all plugins must implement.
    """
    
    def __init__(self, service=None):
        """Initialize the plugin with a service instance.
        
        Args:
            service: The service instance this plugin is associated with
        """
        self.service = service
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
    @abstractmethod
    def get_manifest(self):
        """Get the plugin manifest.
        
        Returns:
            dict: The plugin manifest
        """
        pass
        
    @abstractmethod
    def fetch_messages(self):
        """Fetch messages from the service.
        
        Returns:
            list: List of messages fetched from the service
        """
        pass
        
    @abstractmethod
    def send_message(self, message):
        """Send a message through the service.
        
        Args:
            message: The message to send
            
        Returns:
            bool: True if the message was sent successfully, False otherwise
        """
        pass
        
    @abstractmethod
    def test_connection(self):
        """Test the connection to the service.
        
        Returns:
            bool: True if the connection is successful, False otherwise
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

    def format_for_outgoing(self, message_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format a Raingull message for outgoing delivery.
        
        This method provides a default implementation for formatting Raingull messages
        for outgoing delivery. Plugins can override this method to provide custom
        formatting logic.
        
        Args:
            message_payload (Dict): The message payload to format
            
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
        content = message_payload.get('content', '')
        if header_template:
            content = header_template.format(
                user=message_payload.get('sender', 'Unknown User')
            ) + content

        return {
            'content': content,
            'attachments': message_payload.get('attachments', []),
            'format': manifest.get('formatting', {}).get('message_format', 'text')
        } 