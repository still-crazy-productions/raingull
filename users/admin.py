from django.contrib import admin
from django.contrib.auth.models import Group

# Unregister default Group admin
admin.site.unregister(Group)

# Register the Group admin
class GroupAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

admin.site.register(Group, GroupAdmin) 