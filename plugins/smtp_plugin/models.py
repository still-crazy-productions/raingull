from django.db import models
from core.models import ServiceInstance

class SmtpConfiguration(models.Model):
    service_instance = models.OneToOneField(ServiceInstance, on_delete=models.CASCADE)
    smtp_server = models.CharField(max_length=255)
    smtp_port = models.IntegerField(default=587)
    encryption = models.CharField(max_length=20, choices=[
        ('None', 'None'), ('STARTTLS', 'STARTTLS'), ('SSL/TLS', 'SSL/TLS')
    ], default='STARTTLS')
    username = models.CharField(max_length=255)
    password = models.CharField(max_length=255)

    def __str__(self):
        return f"SMTP config for {self.service_instance.name}"
