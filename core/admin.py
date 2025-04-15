from django.contrib import admin
from django import forms
from .models import UserProfile, Plugin, Message, RainGullStandardMessage, ServiceInstance, PluginInstance
import json
from pathlib import Path
from .forms import ServiceInstanceForm

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

admin.site.register(UserProfile)
admin.site.register(Message)
admin.site.register(RainGullStandardMessage)
