import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from django.utils import timezone
import os

logger = logging.getLogger(__name__)

class Plugin:
    def __init__(self, service_instance):
        self.service_instance = service_instance
        # Load manifest from file instead of trying to get it from plugin_model
        manifest_path = os.path.join(os.path.dirname(__file__), 'manifest.json')
        with open(manifest_path, 'r') as f:
            self.manifest = json.load(f)

    def get_config(self, service_instance):
        """Get the configuration for a service instance"""
        return service_instance.config

    def translate_from_raingull(self, raingull_message):
        """
        Translate a Raingull standard message to SMTP format
        """
        try:
            # Extract the first recipient as the 'to' address
            to_address = raingull_message.recipients[0] if raingull_message.recipients else None
            
            # Return the translated message data
            return {
                'raingull_id': raingull_message.raingull_id,
                'to': to_address,
                'subject': raingull_message.subject,
                'body': raingull_message.body,
                'headers': raingull_message.headers if hasattr(raingull_message, 'headers') else {},
                'status': 'queued'
            }
            
        except Exception as e:
            logger.error(f"Error translating message {raingull_message.raingull_id}: {str(e)}")
            raise

    def send_message(self, message):
        """Send a message using SMTP."""
        try:
            # Update message status to sending
            message.status = 'sending'
            message.save()

            # Get service configuration
            config = self.get_service_config(message.service)
            user_config = self.get_user_config(message.service)

            # Connect to SMTP server
            if config['encryption'] == 'SSL/TLS':
                server = smtplib.SMTP_SSL(config['smtp_server'], config['smtp_port'])
            else:
                server = smtplib.SMTP(config['smtp_server'], config['smtp_port'])
                if config['encryption'] == 'STARTTLS':
                    server.starttls()

            # Login
            server.login(config['username'], config['password'])

            # Create message
            msg = MIMEMultipart()
            msg['From'] = user_config['email_address']
            msg['To'] = message.recipients.get('to', [])[0]  # Use first recipient as primary
            msg['Subject'] = message.subject

            # Add CC and BCC if present
            if 'cc' in message.recipients:
                msg['Cc'] = ', '.join(message.recipients['cc'])
            if 'bcc' in message.recipients:
                msg['Bcc'] = ', '.join(message.recipients['bcc'])

            # Add any additional headers
            if message.headers:
                for key, value in message.headers.items():
                    msg[key] = value

            # Add body
            msg.attach(MIMEText(message.body, 'plain'))

            # Send message
            all_recipients = []
            all_recipients.extend(message.recipients.get('to', []))
            all_recipients.extend(message.recipients.get('cc', []))
            all_recipients.extend(message.recipients.get('bcc', []))
            
            server.send_message(msg)
            server.quit()

            # Update message status
            message.status = 'sent'
            message.sent_at = timezone.now()
            message.save()

            logger.info(f"Message {message.raingull_id} sent successfully via SMTP")

        except Exception as e:
            logger.error(f"Error sending message {message.raingull_id}: {str(e)}")
            message.status = 'failed'
            message.error_message = str(e)
            message.save()
            raise

    def test_connection(self, config):
        """
        Test the SMTP connection with the given configuration
        """
        try:
            server = config['smtp_server']
            port = int(config['smtp_port'])
            user = config['username']
            password = config['password']
            encryption = config['encryption']

            if encryption == "SSL/TLS":
                smtp_server = smtplib.SMTP_SSL(server, port)
            else:
                smtp_server = smtplib.SMTP(server, port)
                if encryption == "STARTTLS":
                    smtp_server.starttls()

            smtp_server.login(user, password)
            smtp_server.quit()

            return {"success": True, "message": "SMTP connection successful."}

        except smtplib.SMTPException as e:
            return {"success": False, "message": f"SMTP error: {e}"}
        except Exception as e:
            return {"success": False, "message": str(e)}
