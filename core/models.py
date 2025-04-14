from django.db import models
from django.contrib.auth.models import User

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    preferred_contact_method = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return self.user.username

class Plugin(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Message(models.Model):
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    subject = models.CharField(max_length=255)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=50, default='queued')

    def __str__(self):
        return f"{self.subject} (status: {self.status})"

import uuid

class RainGullStandardMessage(models.Model):
    raingull_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    
    processing_status = models.CharField(max_length=20, choices=[
        ('new', 'New'),
        ('queued', 'Queued'),
        ('sending', 'Sending'),
        ('distributed', 'Distributed'),
        ('failed', 'Failed'),
    ], default='new')
    
    origin_service_id = models.CharField(max_length=100)
    message_type = models.CharField(max_length=20, choices=[
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('telegram', 'Telegram'),
        ('discord', 'Discord'),
        ('signal', 'Signal'),
        ('whatsapp', 'WhatsApp'),
        ('slack', 'Slack'),
        ('teams', 'Teams'),
        ('other', 'Other'),
    ], default='other')

    sent_timestamp = models.DateTimeField(null=True, blank=True)
    received_timestamp = models.DateTimeField(auto_now_add=True)
    processed_timestamp = models.DateTimeField(auto_now_add=True)

    original_sender = models.CharField(max_length=255)
    original_sender_name = models.CharField(max_length=255, null=True, blank=True)
    original_recipient_list = models.JSONField(null=True, blank=True)

    member_display_name = models.CharField(max_length=255, null=True, blank=True)

    subject = models.CharField(max_length=255, null=True, blank=True)
    snippet = models.CharField(max_length=255, null=True, blank=True)
    message_body = models.TextField()

    additional_headers = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "rg_standard_messages"

    def __str__(self):
        return f"{self.raingull_id} | {self.message_type} | {self.processing_status}"

class ServiceInstance(models.Model):
    plugin = models.ForeignKey('Plugin', on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    active = models.BooleanField(default=True)
    configuration = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.name} ({self.plugin.name})"
