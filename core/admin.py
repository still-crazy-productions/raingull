from django.contrib import admin
from django import forms
from django.contrib.auth.admin import UserAdmin
from .models import UserProfile, Plugin, Message, RaingullStandardMessage, ServiceInstance, PluginInstance, UserServiceActivation, RaingullUser, AuditLog
import json
from pathlib import Path
from .forms import ServiceInstanceForm
from django.utils import timezone
from datetime import timedelta
from django.db import models
from django.db.models import Count

BASE_DIR = Path(__file__).resolve().parent.parent

class DynamicServiceInstanceAdminForm(forms.ModelForm):
    class Meta:
        model = ServiceInstance
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'plugin' in self.data:
            try:
                plugin_id = int(self.data.get('plugin'))
                plugin = Plugin.objects.get(id=plugin_id)
                manifest = plugin.get_manifest()
                if manifest and 'config_fields' in manifest:
                    for field in manifest['config_fields']:
                        field_name = f"config_{field['name']}"
                        if field['type'] == 'select':
                            self.fields[field_name] = forms.ChoiceField(
                                choices=[(opt, opt) for opt in field['options']],
                                required=field.get('required', False),
                                initial=field.get('default', '')
                            )
                        elif field['type'] == 'integer':
                            self.fields[field_name] = forms.IntegerField(
                                required=field.get('required', False),
                                initial=field.get('default', 0)
                            )
                        elif field['type'] == 'password':
                            self.fields[field_name] = forms.CharField(
                                widget=forms.PasswordInput(),
                                required=field.get('required', False)
                            )
                        else:  # string, text, etc.
                            self.fields[field_name] = forms.CharField(
                                required=field.get('required', False),
                                initial=field.get('default', '')
                            )
            except (ValueError, Plugin.DoesNotExist):
                pass

    def clean(self):
        cleaned_data = super().clean()
        plugin = cleaned_data.get('plugin')
        if plugin:
            manifest = plugin.get_manifest()
            if manifest and 'config_fields' in manifest:
                config = {}
                for field in manifest['config_fields']:
                    field_name = f"config_{field['name']}"
                    if field_name in cleaned_data:
                        config[field['name']] = cleaned_data[field_name]
                cleaned_data['config'] = config
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
        return instance

class PluginForm(forms.ModelForm):
    class Meta:
        model = Plugin
        fields = ['name', 'friendly_name', 'version', 'enabled']

class PluginInstanceInline(admin.StackedInline):
    model = PluginInstance
    can_delete = False
    verbose_name_plural = 'Plugin Instance'
    fields = ('app_config', 'is_active')
    readonly_fields = ('app_config',)

@admin.register(ServiceInstance)
class ServiceInstanceAdmin(admin.ModelAdmin):
    form = ServiceInstanceForm
    list_display = ('name', 'plugin', 'incoming_status', 'outgoing_status', 'created_at')
    list_filter = ('plugin', 'incoming_enabled', 'outgoing_enabled')
    search_fields = ('name', 'plugin__name', 'plugin__friendly_name')
    readonly_fields = ('created_at', 'updated_at')
    
    def incoming_status(self, obj):
        if not obj.plugin.get_manifest().get('capabilities', {}).get('incoming', False):
            return 'Not Supported'
        return 'Enabled' if obj.incoming_enabled else 'Disabled'
    incoming_status.short_description = 'Incoming'

    def outgoing_status(self, obj):
        if not obj.plugin.get_manifest().get('capabilities', {}).get('outgoing', False):
            return 'Not Supported'
        return 'Enabled' if obj.outgoing_enabled else 'Disabled'
    outgoing_status.short_description = 'Outgoing'
    
    fieldsets = (
        ('General', {
            'fields': ('name', 'plugin')
        }),
        ('Configuration', {
            'fields': ('config',)
        }),
        ('Status', {
            'fields': ('incoming_enabled', 'outgoing_enabled')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:
            manifest = obj.plugin.get_manifest()
            capabilities = manifest.get('capabilities', {})
            readonly = list(super().get_readonly_fields(request, obj))
            if not capabilities.get('outgoing', False):
                readonly.append('outgoing_enabled')
            if not capabilities.get('incoming', False):
                readonly.append('incoming_enabled')
            return readonly
        return super().get_readonly_fields(request, obj)

@admin.register(Plugin)
class PluginAdmin(admin.ModelAdmin):
    form = PluginForm
    list_display = ('name', 'friendly_name', 'version', 'enabled')
    list_filter = ('enabled',)
    search_fields = ('name', 'friendly_name')
    fields = ('name', 'friendly_name', 'version', 'enabled')

@admin.register(UserServiceActivation)
class UserServiceActivationAdmin(admin.ModelAdmin):
    list_display = ('user', 'service_instance', 'is_active', 'created_at')
    list_filter = ('is_active', 'service_instance__plugin', 'service_instance')
    search_fields = ('user__username', 'service_instance__name')
    readonly_fields = ('created_at', 'updated_at')

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj and obj.service_instance.plugin.name == 'smtp_plugin':
            # Add email field for SMTP plugin
            form.base_fields['email_address'] = forms.EmailField(
                required=True,
                initial=obj.config.get('email_address') if obj else None
            )
        return form

    def save_model(self, request, obj, form, change):
        if obj.service_instance.plugin.name == 'smtp_plugin':
            # Save email address to config for SMTP plugin
            obj.config = {'email_address': form.cleaned_data['email_address']}
        super().save_model(request, obj, form, change)

admin.site.register(UserProfile)
admin.site.register(Message)
admin.site.register(RaingullStandardMessage)

@admin.register(RaingullUser)
class RaingullUserAdmin(UserAdmin):
    # Fields to show in the add user form
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2'),
        }),
        ('Personal info', {
            'fields': ('first_name', 'last_name', 'email'),
        }),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
    )

    # Fields to show in the change user form
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email')}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

    # Fields to show in the list view
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'is_active')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'groups')
    search_fields = ('username', 'first_name', 'last_name', 'email')
    ordering = ('username',)

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'service_instance', 'event_type', 'status', 'details')
    list_filter = ('event_type', 'status', 'service_instance')
    search_fields = ('details', 'service_instance__name')
    date_hierarchy = 'timestamp'
    change_list_template = 'admin/core/auditlog/change_list.html'
    readonly_fields = ('timestamp', 'service_instance', 'event_type', 'status', 'details')
    
    def has_add_permission(self, request):
        return False  # Prevent manual creation of audit logs
    
    def has_delete_permission(self, request, obj=None):
        return False  # Prevent deletion of audit logs
    
    def has_change_permission(self, request, obj=None):
        return False  # Prevent modification of audit logs

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        
        # Get 24-hour activity summary
        twenty_four_hours_ago = timezone.now() - timedelta(hours=24)
        
        # Get recent activity by type
        recent_activity = AuditLog.objects.filter(
            timestamp__gte=twenty_four_hours_ago
        ).values('event_type').annotate(count=Count('id')).order_by('-count')
        
        # Get service activity
        service_activity = AuditLog.objects.filter(
            timestamp__gte=twenty_four_hours_ago
        ).values('service_instance__name').annotate(count=Count('id')).order_by('-count')
        
        # Get error count
        error_count = AuditLog.objects.filter(
            timestamp__gte=twenty_four_hours_ago,
            status='error'
        ).count()
        
        extra_context.update({
            'recent_activity': recent_activity,
            'service_activity': service_activity,
            'error_count': error_count,
        })
        
        return super().changelist_view(request, extra_context=extra_context)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('service_instance')
