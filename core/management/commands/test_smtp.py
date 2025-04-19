from django.core.management.base import BaseCommand
from core.models import RaingullStandardMessage, UserServiceActivation, ServiceInstance
from plugins.smtp_plugin.plugin import SMTPPlugin
import json

class Command(BaseCommand):
    help = 'Test sending a message through SMTP'

    def handle(self, *args, **options):
        # Get the first unprocessed message
        message = RaingullStandardMessage.objects.first()
        if not message:
            self.stdout.write(self.style.ERROR('No messages found'))
            return

        # Get the user's service activation
        service_activation = UserServiceActivation.objects.filter(
            user_id=2,  # Your user ID
            service_instance_id=2,  # Your SMTP service instance ID
            is_active=True
        ).first()

        if not service_activation:
            self.stdout.write(self.style.ERROR('No active service activation found'))
            return

        # Get the service instance
        service_instance = ServiceInstance.objects.get(id=2)  # Your SMTP service instance ID

        # Create the plugin instance
        plugin = SMTPPlugin(service_instance.plugin)

        # Prepare message data
        message_data = {
            'to': service_activation.config.get('email_address'),
            'subject': message.subject,
            'body': message.body
        }

        try:
            # Send the message
            plugin.send_message(service_instance, message_data)
            self.stdout.write(self.style.SUCCESS('Message sent successfully'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error sending message: {str(e)}')) 