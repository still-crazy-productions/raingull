import uuid
from django.db import models

class TwilioSMSMessage(models.Model):
    raingull_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    to_number = models.CharField(max_length=20)
    body = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=[
            ('queued', 'Queued'),
            ('sending', 'Sending'),
            ('sent', 'Sent'),
            ('failed', 'Failed')
        ],
        default='queued'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    twilio_message_id = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"Twilio SMS {self.raingull_id} - {self.to_number}" 