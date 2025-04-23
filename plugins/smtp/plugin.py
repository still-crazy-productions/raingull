import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json
from typing import Dict, List, Optional, Any
import logging
from pathlib import Path

from core.models import PluginInterface, Message

logger = logging.getLogger(__name__)

class SMTPPlugin(PluginInterface):
    """SMTP email plugin for sending messages via email servers."""
    
    def __init__(self, service):
        """Initialize the SMTP plugin with a service instance.
        
        Args:
            service: The service instance this plugin is associated with
        """
        super().__init__(service)
        self.connection = None
        self._load_manifest()
        
    def _load_manifest(self) -> None:
        """Load the plugin manifest from manifest.json."""
        manifest_path = Path(__file__).parent / "manifest.json"
        with open(manifest_path) as f:
            self.manifest = json.load(f)
            
    def _get_manifest(self) -> Dict:
        """Get the plugin manifest.
        
        Returns:
            Dict containing the plugin manifest.
        """
        return self.manifest
        
    def connect(self) -> None:
        """Establish connection to the SMTP server."""
        try:
            if self.config.get("use_tls", True):
                self.connection = smtplib.SMTP(
                    self.config["host"],
                    self.config["port"]
                )
                self.connection.starttls()
            else:
                self.connection = smtplib.SMTP_SSL(
                    self.config["host"],
                    self.config["port"]
                )
                
            self.connection.login(
                self.config["username"],
                self.config["password"]
            )
            logger.info(f"Connected to SMTP server {self.config['host']}")
            
        except Exception as e:
            logger.error(f"Failed to connect to SMTP server: {str(e)}")
            raise
            
    def disconnect(self) -> None:
        """Close the connection to the SMTP server."""
        if self.connection:
            try:
                self.connection.quit()
                logger.info("Disconnected from SMTP server")
            except Exception as e:
                logger.error(f"Error disconnecting from SMTP server: {str(e)}")
            finally:
                self.connection = None
                
    def _create_email(self, message_payload: Dict[str, Any], recipient: str) -> MIMEMultipart:
        """Create an email message from a message payload.
        
        Args:
            message_payload: Dictionary containing message data
            recipient: Email address of the recipient
            
        Returns:
            MIMEMultipart object containing the email
        """
        # Create message container
        msg = MIMEMultipart('alternative')
        
        # Set headers
        msg['Subject'] = message_payload.get('subject', 'No subject')
        msg['From'] = f"{self.config.get('from_name', '')} <{self.config['from_address']}>"
        msg['To'] = recipient
        
        # Create the body of the message
        text = message_payload.get('content', '')
        html = f"<html><body><pre>{text}</pre></body></html>"
        
        # Record the MIME types of both parts - text/plain and text/html
        part1 = MIMEText(text, 'plain')
        part2 = MIMEText(html, 'html')
        
        # Attach parts into message container
        msg.attach(part1)
        msg.attach(part2)
        
        return msg
        
    def _send_message(self, message_payload: Dict[str, Any]) -> bool:
        """Send a message via SMTP.
        
        Args:
            message_payload: Dictionary containing message data
            
        Returns:
            True if message was sent successfully, False otherwise
        """
        if not self.connection:
            self.connect()
            
        try:
            # Get recipient from message payload or use default
            recipient = message_payload.get('to', self.config.get('default_recipient'))
            if not recipient:
                logger.error("No recipient specified and no default recipient configured")
                return False
                
            # Create email message
            email_msg = self._create_email(message_payload, recipient)
            
            # Send the message
            self.connection.send_message(email_msg)
            logger.info(f"Message sent to {recipient}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            return False
            
    def _fetch_messages(self) -> List[Dict[str, Any]]:
        """SMTP plugin does not support fetching messages.
        
        Returns:
            Empty list as SMTP is write-only
        """
        return []
        
    def _test_connection(self) -> bool:
        """Test the connection to the SMTP server.
        
        Returns:
            True if connection is successful, False otherwise
        """
        try:
            self.connect()
            self.disconnect()
            return True
        except Exception as e:
            logger.error(f"Connection test failed: {str(e)}")
            return False

    def format_for_outgoing(self, message_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Format a Raingull message for outgoing delivery via SMTP.
        
        Args:
            message_payload: The message payload to format
            
        Returns:
            Dict containing the formatted message
        """
        # Get the message format from the manifest
        manifest = self._get_manifest()
        message_format = manifest.get('formatting', {}).get('message_format', 'text')
        
        # Format the content based on the message format
        content = message_payload.get('content', '')
        if message_format == 'markdown':
            # TODO: Add markdown to HTML conversion if needed
            pass
            
        # Add any attachments
        attachments = message_payload.get('attachments', [])
        
        return {
            'content': content,
            'attachments': attachments,
            'format': message_format,
            'subject': message_payload.get('subject', ''),
            'to': message_payload.get('recipient', ''),
            'metadata': message_payload.get('metadata', {})
        }

    def translate_from_raingull(self, message: 'Message') -> Dict[str, Any]:
        """Translate a Raingull message to SMTP format.
        
        Args:
            message: The Raingull message to translate
            
        Returns:
            Dict containing the translated message
        """
        return {
            'content': message.payload.get('content', ''),
            'subject': message.subject,
            'to': message.recipient,
            'attachments': message.attachments,
            'metadata': message.payload.get('metadata', {})
        }

    def send(self, message: 'Message') -> bool:
        """Send a message via SMTP.
        
        Args:
            message: The message to send
            
        Returns:
            True if message was sent successfully, False otherwise
        """
        try:
            # Format the message for SMTP
            message_payload = self.format_for_outgoing({
                'content': message.payload.get('content', ''),
                'subject': message.subject,
                'recipient': message.recipient,
                'attachments': message.attachments,
                'metadata': message.payload.get('metadata', {})
            })
            
            # Send the message
            return self._send_message(message_payload)
            
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            return False 