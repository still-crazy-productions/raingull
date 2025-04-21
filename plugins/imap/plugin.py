import json
import imaplib
from django.utils.module_loading import import_string
import logging
import uuid
from django.utils import timezone

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
        print("Starting message retrieval process...")
        self.service_instance = service_instance
        config = service_instance.config
        processed_message_ids = set()
        processed_count = 0
        stored_count = 0

        try:
            # Connect to the IMAP server
            print(f"Connecting to IMAP server: {config['host']}:{config['port']}")
            mail = imaplib.IMAP4_SSL(config['host'], config['port'])
            
            # Login
            print(f"Logging in as: {config['username']}")
            mail.login(config['username'], config['password'])
            
            # Select the inbox
            print("Selecting inbox folder...")
            mail.select('INBOX')
            
            # Get all messages
            print("Searching for messages...")
            _, message_numbers = mail.search(None, 'ALL')
            message_numbers = message_numbers[0].split()
            message_count = len(message_numbers)
            print(f"Found {message_count} messages in inbox")

            if message_count > 0:
                # Get the incoming message model
                try:
                    incoming_model = self.service_instance.get_message_model('incoming')
                    if not incoming_model:
                        print("Warning: Could not get incoming message model, will only move messages")
                        incoming_model = None
                except Exception as e:
                    print(f"Warning: Error getting message model: {str(e)}, will only move messages")
                    incoming_model = None

                # Create processed folder if it doesn't exist
                processed_folder = 'Processed'
                try:
                    mail.create(processed_folder)
                    print(f"Created processed folder: {processed_folder}")
                except:
                    print(f"Processed folder {processed_folder} already exists")

                # Process each message
                for num in message_numbers:
                    try:
                        print(f"Processing message {num.decode('utf-8')}")
                        # Fetch the message with all its parts
                        _, msg_data = mail.fetch(num, '(RFC822)')
                        if not msg_data or not msg_data[0]:
                            print(f"Warning: No data returned for message {num.decode('utf-8')}")
                            continue
                            
                        email_body = msg_data[0][1]
                        
                        # Parse the email
                        import email
                        from email import policy
                        
                        # Parse with policy to handle modern email features
                        msg = email.message_from_bytes(email_body, policy=policy.default)
                        
                        # Get the message ID from headers
                        message_id = msg.get('Message-ID', num.decode('utf-8'))
                        if not message_id:
                            message_id = num.decode('utf-8')
                            print(f"Warning: No Message-ID found for message {num}, using sequence number")
                        
                        # Skip if we've already processed this message
                        if message_id in processed_message_ids:
                            print(f"Skipping already processed message {message_id}")
                            continue
                        
                        # Add to processed set
                        processed_message_ids.add(message_id)
                        
                        # Extract the message body
                        body = ""
                        if msg.is_multipart():
                            # Walk through all parts of the message
                            for part in msg.walk():
                                content_type = part.get_content_type()
                                content_disposition = str(part.get("Content-Disposition"))
                                
                                # Skip any text/plain (txt) attachments
                                if "attachment" not in content_disposition:
                                    if content_type == "text/plain":
                                        body = part.get_content()
                                        break
                                    elif content_type == "text/html":
                                        # If we haven't found a plain text version, use HTML
                                        body = part.get_content()
                        else:
                            # Not multipart, get the content directly
                            body = msg.get_content()
                        
                        # Store in database if we have a model
                        if incoming_model:
                            try:
                                # Create a new message record with fields from schema
                                message = incoming_model(
                                    raingull_id=uuid.uuid4(),  # Generate a new UUID for Raingull's tracking
                                    message_id=message_id,  # Keep the original IMAP message ID
                                    imap_message_id=num.decode('utf-8'),  # Store the IMAP message ID
                                    subject=msg.get('Subject', ''),
                                    sender_email=msg.get('From', ''),
                                    recipients={'to': msg.get('To', ''), 'cc': msg.get('Cc', ''), 'bcc': msg.get('Bcc', '')},
                                    date=msg.get('Date', ''),
                                    body=body,
                                    headers=dict(msg.items()),
                                    status='new'
                                )
                                message.save()
                                stored_count += 1
                                print(f"Stored message {message_id} in database")
                            except Exception as e:
                                print(f"Error storing message {message_id} in database: {str(e)}")
                        
                        # Move the message to processed folder
                        try:
                            mail.copy(num, processed_folder)
                            mail.store(num, '+FLAGS', '\\Deleted')
                            processed_count += 1
                            print(f"Moved message {message_id} to processed folder")
                        except Exception as e:
                            print(f"Error moving message {message_id} to processed folder: {str(e)}")
                            
                    except Exception as e:
                        print(f"Error processing message {num.decode('utf-8')}: {str(e)}")
                        continue
                
                # Expunge deleted messages
                mail.expunge()
                
                return {
                    "success": True,
                    "message": f"Processed {processed_count} messages, stored {stored_count} in database"
                }
            else:
                return {
                    "success": True,
                    "message": "No new messages found"
                }
                
        except Exception as e:
            print(f"Error in retrieve_messages: {str(e)}")
            return {
                "success": False,
                "message": f"Error retrieving messages: {str(e)}"
            }
        finally:
            try:
                mail.logout()
            except:
                pass

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
                message_id=message_data['message_id'],  # Use message_id instead of imap_message_id
                imap_message_id=message_data['imap_message_id'],
                subject=message_data['subject'],
                sender_email=message_data['email_from'],
                to=message_data['to'],
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
