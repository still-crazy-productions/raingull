import json
import imaplib
from django.utils.module_loading import import_string
import logging
import uuid
from django.utils import timezone
import email
from core.models import Plugin as BasePlugin
from django.apps import apps
from core.dynamic_models import create_dynamic_model
from django.db.models.signals import post_save
from django.dispatch import receiver
from core.models import Service

logger = logging.getLogger(__name__)

class Plugin:
    def __init__(self, service_instance):
        self.service_instance = service_instance

    def get_manifest(self):
        try:
            manifest_path = f'plugins.{self.service_instance.plugin.name}.manifest'
            return import_string(manifest_path)
        except ImportError:
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

    def get_incoming_model(self, service_instance):
        """Get the dynamic model for incoming messages."""
        try:
            model_name = f"{self.service_instance.plugin.name}IncomingMessage_{service_instance.id}"
            
            # Try to get the existing model
            try:
                return apps.get_model('core', model_name)
            except LookupError:
                # Model doesn't exist, trigger the signal handler to create it
                # Save the service instance to trigger the signal
                service_instance.save()
                
                # Try to get the model again
                try:
                    return apps.get_model('core', model_name)
                except LookupError:
                    logger.error(f"Could not find incoming model for service {service_instance.id} after creation attempt")
                    return None
            
        except Exception as e:
            logger.error(f"Error getting incoming model: {str(e)}")
            return None

    def test_connection(self, request):
        data = json.loads(request.body)
        required_fields = ['imap_server', 'imap_port', 'username', 'password', 'encryption']
        missing_fields = [f for f in required_fields if not data.get(f)]
        if missing_fields:
            return {
                "success": False,
                "message": f"Missing fields: {', '.join(missing_fields)}"
            }

        server = data['imap_server']
        try:
            port = int(data['imap_port'])
        except ValueError:
            return {
                "success": False,
                "message": "Invalid port number."
            }

        user = data['username']
        password = data['password']
        encryption = data['encryption']

        try:
            if encryption == "SSL/TLS":
                mail = imaplib.IMAP4_SSL(server, port)
            else:
                mail = imaplib.IMAP4(server, port)
                if encryption == "STARTTLS":
                    mail.starttls()

            mail.login(user, password)
            mail.logout()

            return {"success": True, "message": "IMAP Connection successful."}

        except imaplib.IMAP4.error as e:
            return {"success": False, "message": f"IMAP error: {e}"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def retrieve_messages(self, service_instance):
        """Retrieve messages from the IMAP inbox."""
        try:
            # Get service configuration
            config = self.get_service_config(service_instance)
            user_config = self.get_user_config(service_instance)

            # Connect to IMAP server
            if config['encryption'] == 'SSL/TLS':
                mail = imaplib.IMAP4_SSL(config['imap_server'], config['imap_port'])
            else:
                mail = imaplib.IMAP4(config['imap_server'], config['imap_port'])
                if config['encryption'] == 'STARTTLS':
                    mail.starttls()

            # Login
            mail.login(config['username'], config['password'])

            # Select inbox folder
            inbox_folder = config.get('inbox_folder', 'INBOX')
            processed_folder = config.get('processed_folder', 'Processed')
            mail.select(inbox_folder)

            # Search for all messages
            _, message_numbers = mail.search(None, 'ALL')
            message_numbers = message_numbers[0].split()

            # Get the incoming model for this service instance
            incoming_model = self.get_incoming_model(service_instance)
            if not incoming_model:
                logger.error(f"Could not get incoming model for service {service_instance.id}")
                mail.logout()
                return None

            stored_count = 0
            processed_count = 0

            for num in message_numbers:
                try:
                    # Fetch the message
                    _, msg_data = mail.fetch(num, '(RFC822)')
                    msg = email.message_from_bytes(msg_data[0][1])
                    message_id = msg.get('Message-ID', '')

                    # Get message body
                    body = ''
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == 'text/plain':
                                body = part.get_payload(decode=True).decode()
                                break
                    else:
                        body = msg.get_payload(decode=True).decode()

                    # Store in database if we have a model
                    try:
                        # Create a new message record with fields from schema
                        message = incoming_model(
                            raingull_id=uuid.uuid4(),  # Generate a new UUID for Raingull's tracking
                            source_message_id=message_id,  # Store the IMAP message ID
                            subject=msg.get('Subject', ''),
                            sender=msg.get('From', ''),
                            recipients={'to': msg.get('To', ''), 'cc': msg.get('Cc', ''), 'bcc': msg.get('Bcc', '')},
                            date=msg.get('Date', ''),
                            body=body,
                            headers=dict(msg.items()),
                            status='new'
                        )
                        message.save()
                        stored_count += 1
                        logger.info(f"Stored message {message_id} in database")
                    except Exception as e:
                        logger.error(f"Error storing message {message_id} in database: {str(e)}")
                        continue

                    # Move the message to processed folder
                    try:
                        mail.copy(num, processed_folder)
                        mail.store(num, '+FLAGS', '\\Deleted')
                        processed_count += 1
                        logger.info(f"Moved message {message_id} to processed folder")
                    except Exception as e:
                        logger.error(f"Error moving message {message_id} to processed folder: {str(e)}")
                        continue

                except Exception as e:
                    logger.error(f"Error processing message: {str(e)}")
                    continue

            # Expunge deleted messages
            mail.expunge()
            mail.close()
            mail.logout()

            return {
                'stored': stored_count,
                'processed': processed_count
            }

        except Exception as e:
            logger.error(f"Error retrieving messages: {str(e)}")
            try:
                mail.logout()
            except:
                pass
            return None

    def connect(self):
        """Connect to the IMAP server"""
        try:
            logger.info(f"Attempting to connect to IMAP server: {self.service_instance.config.get('imap_server')}:{self.service_instance.config.get('imap_port')} with encryption: {self.service_instance.config.get('encryption')}")
            
            if self.service_instance.config.get('encryption') == 'SSL/TLS':
                self.imap = imaplib.IMAP4_SSL(self.service_instance.config.get('imap_server'), self.service_instance.config.get('imap_port'))
            else:
                self.imap = imaplib.IMAP4(self.service_instance.config.get('imap_server'), self.service_instance.config.get('imap_port'))
                if self.service_instance.config.get('encryption') == 'STARTTLS':
                    self.imap.starttls()
            
            logger.info("Connected to IMAP server, attempting login...")
            self.imap.login(self.service_instance.config.get('username'), self.service_instance.config.get('password'))
            logger.info("Login successful, selecting inbox folder...")
            self.imap.select(self.service_instance.config.get('imap_inbox_folder', 'INBOX'))
            
        except Exception as e:
            logger.error(f"IMAP connection error: {str(e)}")
            raise

    def store_message_in_database(self, message_data, service_instance):
        """Store a message in the database using the incoming model."""
        try:
            # Get the incoming model for this service instance
            incoming_model = self.get_incoming_model(service_instance)
            
            # Create a new message instance
            message = incoming_model(
                raingull_id=message_data['raingull_id'],
                source_message_id=message_data['source_message_id'],
                subject=message_data['subject'],
                sender=message_data['sender'],
                recipients=message_data['recipients'],
                date=message_data['date'],
                body=message_data['body'],
                headers=message_data.get('headers', {}),
                status='new'
            )
            
            # Save the message
            message.save()
            return True
        except Exception as e:
            logger.error(f"Error storing message in database: {str(e)}")
            return False
