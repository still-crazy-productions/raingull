import imaplib
import email
from email.header import decode_header
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging
from pathlib import Path
from django.http import JsonResponse
from dateutil.parser import parse as parse_date
from django.utils import timezone

from core.models import PluginInterface, Message, Service

logger = logging.getLogger(__name__)

class IMAPPlugin(PluginInterface):
    """IMAP email plugin for fetching messages from email servers."""
    
    def __init__(self, service: Service):
        """Initialize the IMAP plugin with a service instance.
        
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
        
    def _parse_email(self, msg: email.message.Message) -> Dict:
        """Parse email message into a dictionary.
        
        Args:
            msg: Email message object
            
        Returns:
            Dictionary containing parsed email data
        """
        # Get basic fields
        subject = self._decode_header(msg.get('Subject', ''))
        sender = self._decode_header(msg.get('From', ''))
        recipient = self._decode_header(msg.get('To', ''))
        
        # Parse date string to datetime
        date_str = msg.get('Date', '')
        try:
            timestamp = parse_date(date_str)
        except (TypeError, ValueError):
            logger.warning(f"Could not parse date '{date_str}', using current time")
            timestamp = timezone.now()
        
        # Get message body
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        body = payload.decode(part.get_content_charset() or 'utf-8', errors='replace')
                    else:
                        body = str(payload)
                    break
        else:
            payload = msg.get_payload(decode=True)
            if isinstance(payload, bytes):
                body = payload.decode(msg.get_content_charset() or 'utf-8', errors='replace')
            else:
                body = str(payload)
            
        # Structure the payload
        payload = {
            'content': body,
            'attachments': [],  # TODO: Handle attachments
            'metadata': {
                'subject': subject,
                'date': date_str,
                'headers': dict(msg.items())
            }
        }
            
        return {
            'subject': subject,
            'sender': sender,
            'recipient': recipient,
            'timestamp': timestamp,
            'payload': payload
        }
        
    def _fetch_messages(self) -> List[Dict[str, Any]]:
        """Fetch messages from the IMAP server.
        
        Returns:
            List of dictionaries containing message data
        """
        if not self.connection:
            self.connect()
            
        try:
            # Select the INBOX
            self.connection.select('INBOX')
            
            # Search for all messages
            _, message_numbers = self.connection.search(None, 'ALL')
            
            messages = []
            for num in message_numbers[0].split():
                try:
                    # Fetch the message data - this returns raw email bytes
                    _, msg_data = self.connection.fetch(num, '(RFC822)')
                    if not msg_data or not msg_data[0]:
                        logger.warning(f"No data received for message {num}, skipping")
                        continue
                        
                    # Parse the raw email bytes into an email message
                    email_message = email.message_from_bytes(msg_data[0][1])
                    
                    # Get the Message-ID header
                    message_id = email_message.get('Message-ID', '')
                    if not message_id:
                        logger.warning(f"Message {num} has no Message-ID, skipping")
                        continue
                        
                    # Check if we've already processed this message
                    if Message.objects.filter(
                        service=self.service,
                        service_message_id=message_id,
                        direction='incoming'
                    ).exists():
                        logger.info(f"Skipping duplicate message {message_id} from {self.service.name}")
                        continue
                        
                    # Parse the email into our format
                    message_data = self._parse_email(email_message)
                    message_data['service_message_id'] = message_id
                    
                    messages.append(message_data)
                    
                    # Move to Processed folder
                    try:
                        # Create Processed folder if it doesn't exist
                        self.connection.create('Processed')
                    except:
                        pass  # Folder may already exist
                        
                    # Copy message to Processed folder
                    self.connection.copy(num, 'Processed')
                    # Delete from INBOX
                    self.connection.store(num, '+FLAGS', '\\Deleted')
                    self.connection.expunge()
                        
                except Exception as e:
                    logger.error(f"Error processing message {num}: {str(e)}")
                    continue
                    
            return messages
            
        except Exception as e:
            logger.error(f"Error fetching messages: {str(e)}")
            return []
            
    def _send_message(self, message_payload: Dict[str, Any]) -> bool:
        """IMAP plugin does not support sending messages.
        
        Args:
            message_payload: Message payload to send
            
        Returns:
            False as IMAP is read-only
        """
        return False
        
    def _test_connection(self) -> bool:
        """Test the connection to the IMAP server.
        
        Returns:
            bool: True if connection was successful, False otherwise
        """
        try:
            self.connect()
            self.disconnect()
            return True
        except Exception as e:
            logger.error(f"Connection test failed: {str(e)}")
            return False

    def test_connection_api(self, request, data) -> JsonResponse:
        """API endpoint for testing the connection to the IMAP server.
        
        Args:
            request: The HTTP request object
            data: The configuration data to test
            
        Returns:
            JsonResponse indicating success or failure
        """
        try:
            # Create a temporary service instance with the test configuration
            from core.models import Service
            service = Service(
                plugin=self.plugin,
                config=data
            )
            
            # Create a new plugin instance with the test configuration
            plugin = IMAPPlugin(service)
            
            # Test the connection
            success = plugin.test_connection()
            
            return JsonResponse({
                'success': success,
                'message': 'Connection successful' if success else 'Connection failed'
            })
        except Exception as e:
            logger.error(f"Connection test failed: {str(e)}")
            return JsonResponse({
                'success': False,
                'message': f'Connection failed: {str(e)}'
            })

    def mark_message_processed(self, message_id: str) -> None:
        """Mark a message as processed on the IMAP server.
        
        Args:
            message_id: The email Message-ID or IMAP message number of the message to mark as processed
        """
        if not self.connection:
            self.connect()
            
        try:
            # Select the folder
            self.connection.select(self.config.get('folder', 'INBOX'))
            
            # Get the processed folder from config, default to INBOX.Processed
            processed_folder = self.config.get('processed_folder', 'INBOX.Processed')
            
            # Create the processed folder if it doesn't exist
            try:
                self.connection.create(processed_folder)
            except Exception as e:
                # Folder might already exist, which is fine
                logger.debug(f"Error creating folder {processed_folder}: {str(e)}")
            
            # If message_id looks like an email Message-ID (contains @), search for it
            if '@' in message_id:
                # Clean up the Message-ID by removing any angle brackets
                clean_message_id = message_id.strip('<>')
                
                # Try different search patterns
                search_patterns = [
                    f'(HEADER Message-ID "{clean_message_id}")',
                    f'(HEADER Message-ID "<{clean_message_id}>")',
                    f'(HEADER Message-ID "{message_id}")'
                ]
                
                imap_num = None
                for pattern in search_patterns:
                    _, message_numbers = self.connection.search(None, pattern)
                    if message_numbers[0]:
                        imap_num = message_numbers[0].split()[0]  # Get the first matching message
                        break
                
                if not imap_num:
                    logger.warning(f"Could not find message with Message-ID {message_id} using any search pattern")
                    return
            else:
                imap_num = message_id  # Use the number directly
                
            try:
                # Copy the message to the processed folder
                self.connection.copy(imap_num, processed_folder)
                # Delete the original message
                self.connection.store(imap_num, '+FLAGS', '\\Deleted')
                # Expunge to actually remove the message
                self.connection.expunge()
                logger.info(f"Moved message {message_id} to {processed_folder}")
            except Exception as e:
                logger.error(f"Error moving message {message_id} to processed folder: {str(e)}")
                    
        except Exception as e:
            logger.error(f"Error marking message {message_id} as processed: {str(e)}")
            # Don't raise the exception - we don't want to fail the entire process
            # just because we couldn't move a message to the processed folder
