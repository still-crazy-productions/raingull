# This file is intentionally empty as we're using dynamic models
# The outgoing message schema is defined in manifest.json

from django.db import models
import uuid

class SMTPOutgoingMessage(models.Model):
    raingull_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    to = models.EmailField(max_length=255)
    subject = models.CharField(max_length=255)
    body = models.TextField()
    headers = models.JSONField(default=dict, blank=True)
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

    class Meta:
        db_table = 'smtp_outgoing_message'
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"SMTP Message {self.raingull_id} - {self.subject}"
