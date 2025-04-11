from django.contrib import admin
from .models import ServerInfo

class SingleInstanceAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        # Allow adding only if there isn't already an instance
        if ServerInfo.objects.exists():
            return False
        return True

admin.site.register(ServerInfo, SingleInstanceAdmin)