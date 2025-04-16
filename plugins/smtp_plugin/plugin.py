import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging

logger = logging.getLogger(__name__)

class SMTPPlugin:
    def __init__(self, plugin_model):
        self.plugin_model = plugin_model
        self.manifest = plugin_model.get_manifest()

    def get_config(self, service_instance):
        """Get the configuration for a service instance"""
        return service_instance.config

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
