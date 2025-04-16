import json
import imaplib
from django.utils.module_loading import import_string

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

    def retrieve_messages(self):
        """Retrieve messages from IMAP inbox and move them to processed folder"""
        try:
            # Get configuration
            config = self.service_instance.config
            if not config:
                return {"success": False, "message": "No configuration found for this service instance"}

            server = config.get('imap_server')
            if not server:
                return {"success": False, "message": "IMAP server address not configured"}

            port = int(config.get('imap_port', 993))
            user = config.get('username')
            if not user:
                return {"success": False, "message": "Username not configured"}

            password = config.get('password')
            if not password:
                return {"success": False, "message": "Password not configured"}

            encryption = config.get('encryption', 'SSL/TLS')
            inbox_folder = config.get('imap_inbox_folder', 'INBOX')
            processed_folder = config.get('imap_processed_folder', 'Processed')

            print(f"Attempting to connect to IMAP server: {server}:{port} with encryption: {encryption}")

            # Connect to IMAP server
            try:
                if encryption == "SSL/TLS":
                    mail = imaplib.IMAP4_SSL(server, port)
                else:
                    mail = imaplib.IMAP4(server, port)
                    if encryption == "STARTTLS":
                        mail.starttls()
            except ConnectionRefusedError as e:
                return {"success": False, "message": f"Connection refused to {server}:{port}. Please check if the server is running and the port is correct."}
            except Exception as e:
                return {"success": False, "message": f"Failed to connect to IMAP server: {str(e)}"}

            print("Connected to IMAP server, attempting login...")

            # Login
            try:
                mail.login(user, password)
            except imaplib.IMAP4.error as e:
                return {"success": False, "message": f"Login failed: {str(e)}"}

            print("Login successful, selecting inbox folder...")

            # Select inbox folder
            try:
                mail.select(inbox_folder)
            except imaplib.IMAP4.error as e:
                return {"success": False, "message": f"Failed to select folder '{inbox_folder}': {str(e)}"}

            # Initialize counters
            processed_count = 0
            stored_count = 0
            processed_message_ids = set()  # Keep track of processed message IDs

            # Get all messages
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
                try:
                    mail.create(processed_folder)
                    print(f"Created processed folder: {processed_folder}")
                except:
                    # Folder might already exist, which is fine
                    print(f"Processed folder {processed_folder} already exists")

                # Process each message
                for num in message_numbers:
                    try:
                        # Fetch the message with all its parts
                        _, msg_data = mail.fetch(num, '(RFC822)')
                        email_body = msg_data[0][1]
                        
                        # Parse the email
                        import email
                        import uuid
                        from django.utils import timezone
                        from email import policy
                        
                        # Parse with policy to handle modern email features
                        msg = email.message_from_bytes(email_body, policy=policy.default)
                        
                        # Get the message ID from headers
                        message_id = msg.get('Message-ID', num.decode('utf-8'))
                        
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
                                    raingull_id=uuid.uuid4(),
                                    imap_message_id=message_id,
                                    subject=msg.get('subject', ''),
                                    email_from=msg.get('from', ''),
                                    to=msg.get_all('to', []),  # Get all recipients
                                    date=msg.get('date', ''),
                                    body=body,
                                    headers=dict(msg.items()),
                                    status='new',
                                    processed_at=timezone.now()
                                )
                                message.save()
                                stored_count += 1
                                print(f"Stored message {message_id} in database")
                            except Exception as e:
                                print(f"Error storing message {num} in database: {str(e)}")
                        
                        # Move the message to processed folder
                        mail.copy(num, processed_folder)
                        mail.store(num, '+FLAGS', '\\Deleted')
                        processed_count += 1
                        
                    except Exception as e:
                        print(f"Error processing message {num}: {str(e)}")
                        continue

                # Expunge deleted messages
                mail.expunge()
                print(f"Processed {processed_count} messages, stored {stored_count} in database")

            # Close the mailbox and logout
            mail.close()
            mail.logout()
            print("Connection closed")

            return {
                "success": True,
                "message": f"Retrieved {message_count} messages, processed {processed_count} messages (stored {stored_count} in database) and moved them to the processed folder"
            }

        except imaplib.IMAP4.error as e:
            return {"success": False, "message": f"IMAP error: {str(e)}"}
        except Exception as e:
            return {"success": False, "message": str(e)}
