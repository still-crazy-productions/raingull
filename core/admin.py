from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User, Group
from .models import Plugin, Service, Message, MessageQueue, UserService, AuditLog, ServiceMessageTemplate, SystemMessageTemplate

# Unregister default Group admin
admin.site.unregister(Group)

# Register the Group admin first
class GroupAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)

admin.site.register(Group, GroupAdmin)

# Define a new User admin
@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'is_active', 'is_moderator', 'is_admin', 'web_login_enabled', 'mfa_enabled')
    list_filter = ('is_staff', 'is_active', 'is_moderator', 'is_admin', 'web_login_enabled', 'mfa_enabled')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    ordering = ('username',)
    filter_horizontal = ('groups', 'user_permissions',)

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'is_moderator', 'is_admin', 'groups', 'user_permissions')}),
        ('Security', {'fields': ('web_login_enabled', 'mfa_enabled', 'mfa_secret', 'preferred_contact_method', 'timezone')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

# Register other models
admin.site.register(Plugin)
admin.site.register(Service)
admin.site.register(Message)
admin.site.register(MessageQueue)
admin.site.register(UserService)
admin.site.register(AuditLog)
admin.site.register(ServiceMessageTemplate)
admin.site.register(SystemMessageTemplate) 