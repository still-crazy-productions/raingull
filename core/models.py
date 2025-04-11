from django.db import models

class ServerInfo(models.Model):
    server_name = models.CharField(max_length=100)
    description = models.TextField()

    def __str__(self):
        return self.server_name