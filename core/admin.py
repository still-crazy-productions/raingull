from django.contrib import admin
from .models import UserProfile, Plugin, Message, RainGullStandardMessage

# Register your models here.
admin.site.register(UserProfile)
admin.site.register(Plugin)
admin.site.register(Message)
admin.site.register(RainGullStandardMessage)
