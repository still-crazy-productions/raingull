import uuid
import logging
import re
from twilio.rest import Client
from django.db import models
from django.conf import settings

logger = logging.getLogger(__name__)

class Plugin:
    def __init__(self, service_instance):
        self.service_instance = service_instance
        self.config = service_instance.config
        self.client = Client(
            self.config.get('account_sid'),
            self.config.get('auth_token')
        )

    def validate_phone_number(self, phone_number):
        """
        Validate that a phone number is in E.164 format
        """
        pattern = r'^\+[1-9]\d{1,14}$'
        if not re.match(pattern, phone_number):
            raise ValueError(f"Invalid phone number format. Must be in E.164 format (e.g., +1234567890)")
        return phone_number

    def translate_from_raingull(self, raingull_message, user_service_activation=None):
        """
        Translate a Raingull standard message to Twilio SMS format
        Uses the message snippet instead of the full body for SMS
        """
        try:
            # Get the first recipient as the phone number
            to_number = raingull_message.recipients[0] if raingull_message.recipients else None
            if not to_number:
                raise ValueError("No recipient phone number provided")

            # Validate the phone number format
            to_number = self.validate_phone_number(to_number)

            # Use the snippet instead of the full body
            body = raingull_message.snippet if hasattr(raingull_message, 'snippet') else raingull_message.body[:160]

            # Create the Twilio message
            twilio_message = {
                'raingull_id': raingull_message.raingull_id,
                'to_number': to_number,
                'body': body,
                'status': 'queued',
                'created_at': raingull_message.created_at,
            }

            return twilio_message
        except Exception as e:
            logger.error(f"Error translating message {raingull_message.raingull_id}: {str(e)}")
            raise

    def send_message(self, message, user_service_activation=None):
        """
        Send an SMS message using Twilio
        """
        try:
            # Update status to sending
            message.status = 'sending'
            message.save()

            # Validate the phone number format
            to_number = self.validate_phone_number(message.to_number)

            # Send the message via Twilio
            twilio_message = self.client.messages.create(
                body=message.body,
                from_=self.config.get('twilio_phone_number'),
                to=to_number
            )

            # Update message with Twilio response
            message.status = 'sent'
            message.sent_at = twilio_message.date_created
            message.twilio_message_id = twilio_message.sid
            message.save()

            return True
        except Exception as e:
            logger.error(f"Error sending message {message.raingull_id}: {str(e)}")
            message.status = 'failed'
            message.error_message = str(e)
            message.save()
            return False 