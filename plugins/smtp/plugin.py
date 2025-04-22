import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json
from typing import Dict, List, Optional
import logging
from pathlib import Path

from core.plugin_base import BasePlugin
from core.models import Message

logger = logging.getLogger(__name__)

class SMTPPlugin(BasePlugin):
    """SMTP email plugin for sending messages via email servers."""
    
    def __init__(self, config: Dict):
        """Initialize the SMTP plugin with configuration.
        
        Args:
            config: Plugin configuration dictionary containing:
                - host: SMTP server hostname
                - port: SMTP server port
                - username: Email account username
                - password: Email account password
                - use_tls: Whether to use TLS
                - from_address: Email address to send from
                - from_name: Display name for the sender
                - default_recipient: Default recipient email address
        """
        super().__init__(config)
        self.connection = None
        self._load_manifest()
        
    def _load_manifest(self) -> None:
        """Load the plugin manifest from manifest.json."""
        manifest_path = Path(__file__).parent / "manifest.json"
        with open(manifest_path) as f:
            self.manifest = json.load(f)
            
    def get_manifest(self) -> Dict:
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
                
    def _create_email(self, message: Message, recipient: str) -> MIMEMultipart:
        """Create an email message from a Message object.
        
        Args:
            message: Message object to convert to email
            recipient: Email address of the recipient
            
        Returns:
            MIMEMultipart object containing the email
        """
        # Create message container
        msg = MIMEMultipart('alternative')
        
        # Set headers
        msg['Subject'] = message.metadata.get('subject', 'No subject')
        msg['From'] = f"{self.config.get('from_name', '')} <{self.config['from_address']}>"
        msg['To'] = recipient
        
        # Create the body of the message
        text = message.content
        html = f"<html><body><pre>{message.content}</pre></body></html>"
        
        # Record the MIME types of both parts - text/plain and text/html
        part1 = MIMEText(text, 'plain')
        part2 = MIMEText(html, 'html')
        
        # Attach parts into message container
        msg.attach(part1)
        msg.attach(part2)
        
        return msg
        
    def send_message(self, message: Message) -> bool:
        """Send a message via SMTP.
        
        Args:
            message: Message to send
            
        Returns:
            True if message was sent successfully, False otherwise
        """
        if not self.connection:
            self.connect()
            
        try:
            # Get recipient from message metadata or use default
            recipient = message.metadata.get('recipient', self.config.get('default_recipient'))
            if not recipient:
                logger.error("No recipient specified and no default recipient configured")
                return False
                
            # Create email message
            email_msg = self._create_email(message, recipient)
            
            # Send the message
            self.connection.send_message(email_msg)
            logger.info(f"Message sent to {recipient}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            return False
            
    def fetch_messages(self) -> List[Message]:
        """SMTP plugin does not support fetching messages.
        
        Returns:
            Empty list as SMTP is write-only
        """
        return []
        
    def test_connection(self) -> bool:
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