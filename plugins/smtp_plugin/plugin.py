import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from django.utils import timezone
import os

logger = logging.getLogger(__name__)

class Plugin:
    def __init__(self, plugin_model):
        self.plugin_model = plugin_model
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

    def send_message(self, service_instance, message_data):
        """
        Send an email message using the configured SMTP server
        """
        config = self.get_config(service_instance)
        
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = config.get('username')
            msg['To'] = message_data.get('to')
            msg['Subject'] = message_data.get('subject')
            
            # Add body
            msg.attach(MIMEText(message_data.get('body', ''), 'plain'))
            
            # Connect to SMTP server
            server = config['smtp_server']
            port = int(config['smtp_port'])
            encryption = config['encryption']
            
            if encryption == "SSL/TLS":
                smtp_server = smtplib.SMTP_SSL(server, port)
            else:
                smtp_server = smtplib.SMTP(server, port)
                if encryption == "STARTTLS":
                    smtp_server.starttls()
            
            # Login and send
            smtp_server.login(config['username'], config['password'])
            smtp_server.send_message(msg)
            smtp_server.quit()
            
            logger.info(f"Successfully sent email to {message_data.get('to')}")
            return True
            
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error while sending email: {e}")
            raise
        except Exception as e:
            logger.error(f"Error sending email: {e}")
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
