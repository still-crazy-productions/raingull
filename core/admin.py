from django.contrib import admin
from django.contrib import messages
from django.urls import reverse
from django.utils.html import format_html
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Plugin, Service, Message, UserService, AuditLog, ServiceMessageTemplate, SystemMessageTemplate, User
from .generate_models import generate_models_file
import logging

# Define a new User admin
@admin.register(User)
class CustomUserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'created_at', 'updated_at')
    list_filter = ('is_staff', 'is_superuser', 'created_at')
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email', 'timezone')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'plugin', 'created_at', 'updated_at')
    list_filter = ('plugin', 'created_at', 'updated_at')
    search_fields = ('name',)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        try:
            generate_models_file()
            messages.success(request, 'Service saved successfully. IMPORTANT: Please run "python manage.py makemigrations" and "python manage.py migrate" to create the database tables, then reboot Raingull for changes to take effect.')
        except Exception as e:
            messages.error(request, f'Error generating models: {str(e)}')

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        try:
            generate_models_file()
            messages.success(request, 'Service deleted successfully. IMPORTANT: Please run "python manage.py makemigrations" and "python manage.py migrate" to update the database, then reboot Raingull for changes to take effect.')
        except Exception as e:
            messages.error(request, f'Error generating models: {str(e)}')

@admin.register(Plugin)
class PluginAdmin(admin.ModelAdmin):
    list_display = ('name', 'friendly_name', 'version', 'is_enabled', 'created_at', 'updated_at')
    list_filter = ('enabled', 'created_at', 'updated_at')
    search_fields = ('name', 'friendly_name')
    readonly_fields = ('name', 'friendly_name', 'version', 'manifest')
    actions = ['enable_plugins', 'disable_plugins']

    def is_enabled(self, obj):
        return obj.enabled
    is_enabled.boolean = True
    is_enabled.short_description = 'Enabled'

    def enable_plugins(self, request, queryset):
        queryset.update(enabled=True)
        self.message_user(request, f"Enabled {queryset.count()} plugins")
    enable_plugins.short_description = "Enable selected plugins"

    def disable_plugins(self, request, queryset):
        queryset.update(enabled=False)
        self.message_user(request, f"Disabled {queryset.count()} plugins")
    disable_plugins.short_description = "Disable selected plugins"

    def has_add_permission(self, request):
        return False  # Plugins can only be added through discovery

    def has_delete_permission(self, request, obj=None):
        return False  # Plugins can only be removed through discovery

# Register other models
admin.site.register(Message)
admin.site.register(UserService)
admin.site.register(ServiceMessageTemplate)
admin.site.register(SystemMessageTemplate)

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'status', 'created_at')
    list_filter = ('event_type', 'status', 'created_at')
    search_fields = ('details',)
    readonly_fields = ('created_at',)