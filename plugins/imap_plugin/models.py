from django.db import models

class ImapConfiguration(models.Model):
    service_instance = models.OneToOneField('core.ServiceInstance', on_delete=models.CASCADE)
    imap_server = models.CharField(max_length=255)
    imap_port = models.IntegerField(default=993)
    encryption = models.CharField(max_length=10, choices=[('None', 'None'), ('STARTTLS', 'STARTTLS'), ('SSL/TLS', 'SSL/TLS')], default='SSL/TLS')
    username = models.CharField(max_length=255)
    password = models.CharField(max_length=255)
    poll_frequency = models.IntegerField(default=5)
    imap_inbox = models.CharField(max_length=255, default='INBOX')
    imap_processed_folder = models.CharField(max_length=255, default='INBOX/Processed')
    imap_rejected_folder = models.CharField(max_length=255, default='INBOX/Rejected')

    def __str__(self):
        return f"{self.service_instance.name} IMAP Configuration"
