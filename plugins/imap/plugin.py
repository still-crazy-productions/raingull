import imaplib
import email
from email.header import decode_header
import json
from typing import Dict, List, Optional
from datetime import datetime
import logging
from pathlib import Path

from core.plugin_base import BasePlugin
from core.models import Message

logger = logging.getLogger(__name__)

class IMAPPlugin(BasePlugin):
    """IMAP email plugin for fetching messages from email servers."""
    
    def __init__(self, config: Dict):
        """Initialize the IMAP plugin with configuration.
        
        Args:
            config: Plugin configuration dictionary containing:
                - host: IMAP server hostname
                - port: IMAP server port
                - username: Email account username
                - password: Email account password
                - use_ssl: Whether to use SSL/TLS
                - folder: IMAP folder to monitor
                - mark_as_read: Whether to mark messages as read
                - delete_after_fetch: Whether to delete messages after fetching
                - fetch_interval: Interval between fetches in seconds
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
        """Establish connection to the IMAP server."""
        try:
            if self.config.get("use_ssl", True):
                self.connection = imaplib.IMAP4_SSL(
                    self.config["host"],
                    self.config["port"]
                )
            else:
                self.connection = imaplib.IMAP4(
                    self.config["host"],
                    self.config["port"]
                )
                
            self.connection.login(
                self.config["username"],
                self.config["password"]
            )
            logger.info(f"Connected to IMAP server {self.config['host']}")
            
        except Exception as e:
            logger.error(f"Failed to connect to IMAP server: {str(e)}")
            raise
            
    def disconnect(self) -> None:
        """Close the connection to the IMAP server."""
        if self.connection:
            try:
                self.connection.logout()
                logger.info("Disconnected from IMAP server")
            except Exception as e:
                logger.error(f"Error disconnecting from IMAP server: {str(e)}")
            finally:
                self.connection = None
                
    def _decode_header(self, header: str) -> str:
        """Decode email header value.
        
        Args:
            header: Header value to decode
            
        Returns:
            Decoded header value as string
        """
        decoded = []
        for part, encoding in decode_header(header):
            if isinstance(part, bytes):
                decoded.append(part.decode(encoding or 'utf-8', errors='replace'))
            else:
                decoded.append(str(part))
        return ''.join(decoded)
        
    def _parse_email(self, email_data: bytes) -> Dict:
        """Parse email message into a dictionary.
        
        Args:
            email_data: Raw email message data
            
        Returns:
            Dictionary containing parsed email data
        """
        msg = email.message_from_bytes(email_data)
        
        # Get basic fields
        subject = self._decode_header(msg.get('Subject', ''))
        from_addr = self._decode_header(msg.get('From', ''))
        date = msg.get('Date', '')
        
        # Get message body
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode(
                        part.get_content_charset() or 'utf-8',
                        errors='replace'
                    )
                    break
        else:
            body = msg.get_payload(decode=True).decode(
                msg.get_content_charset() or 'utf-8',
                errors='replace'
            )
            
        return {
            'subject': subject,
            'from': from_addr,
            'date': date,
            'body': body
        }
        
    def fetch_messages(self) -> List[Message]:
        """Fetch new messages from the IMAP server.
        
        Returns:
            List of Message objects containing the fetched messages
        """
        if not self.connection:
            self.connect()
            
        try:
            # Select the folder
            self.connection.select(self.config.get('folder', 'INBOX'))
            
            # Search for unread messages
            _, message_numbers = self.connection.search(None, 'UNSEEN')
            message_numbers = message_numbers[0].split()
            
            messages = []
            for num in message_numbers:
                try:
                    # Fetch the message
                    _, msg_data = self.connection.fetch(num, '(RFC822)')
                    email_data = msg_data[0][1]
                    
                    # Parse the message
                    parsed = self._parse_email(email_data)
                    
                    # Create Message object
                    message = Message(
                        source_id=str(num),
                        source_type='imap',
                        content=parsed['body'],
                        sender=parsed['from'],
                        timestamp=datetime.now(),
                        metadata={
                            'subject': parsed['subject'],
                            'date': parsed['date']
                        }
                    )
                    messages.append(message)
                    
                    # Mark as read if configured
                    if self.config.get('mark_as_read', True):
                        self.connection.store(num, '+FLAGS', '\\Seen')
                        
                    # Delete if configured
                    if self.config.get('delete_after_fetch', False):
                        self.connection.store(num, '+FLAGS', '\\Deleted')
                        
                except Exception as e:
                    logger.error(f"Error processing message {num}: {str(e)}")
                    continue
                    
            # Expunge deleted messages
            if self.config.get('delete_after_fetch', False):
                self.connection.expunge()
                
            return messages
            
        except Exception as e:
            logger.error(f"Error fetching messages: {str(e)}")
            raise
            
    def send_message(self, message: Message) -> bool:
        """IMAP plugin does not support sending messages.
        
        Args:
            message: Message to send
            
        Returns:
            False as IMAP is read-only
        """
        return False
        
    def test_connection(self) -> bool:
        """Test the connection to the IMAP server.
        
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
