from django.contrib import admin
from django import forms
from .models import UserProfile, Plugin, Message, RainGullStandardMessage, ServiceInstance
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

class DynamicServiceInstanceAdminForm(forms.ModelForm):
    class Meta:
        model = ServiceInstance
        fields = ['name', 'plugin', 'enabled']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['plugin'].queryset = Plugin.objects.filter(enabled=True)

        plugin_instance = None
        if 'plugin' in self.data:
            try:
                plugin_id = int(self.data.get('plugin'))
                plugin_instance = Plugin.objects.get(pk=plugin_id)
            except (ValueError, Plugin.DoesNotExist):
                pass
        elif self.instance and self.instance.plugin:
            plugin_instance = self.instance.plugin

        if plugin_instance:
            manifest_path = BASE_DIR / "plugins" / plugin_instance.name / "manifest.json"
            if manifest_path.exists():
                with open(manifest_path, 'r') as file:
                    manifest = json.load(file)

                for field_def in manifest.get('config_fields', []):
                    field_name = field_def['name']
                    field_type = field_def['type']
                    required = field_def.get('required', False)
                    initial = self.instance.configuration.get(field_name, field_def.get('default')) if self.instance.configuration else field_def.get('default')
                    help_text = field_def.get('label', '')

                    if field_type == 'string':
                        field = forms.CharField(required=required, initial=initial, help_text=help_text)
                    elif field_type == 'integer':
                        field = forms.IntegerField(required=required, initial=initial, help_text=help_text)
                    elif field_type == 'password':
                        field = forms.CharField(required=required, widget=forms.PasswordInput, help_text=help_text)
                    elif field_type == 'select':
                        options = field_def.get('options', [])
                        field = forms.ChoiceField(choices=[(opt, opt) for opt in options], required=required, initial=initial, help_text=help_text)
                    else:
                        continue

                    self.fields[f'config_{field_name}'] = field

class ServiceInstanceAdmin(admin.ModelAdmin):
    form = DynamicServiceInstanceAdminForm
    list_display = ['name', 'plugin', 'enabled']
    list_filter = ['plugin', 'enabled']

    def get_form(self, request, obj=None, **kwargs):
        defaults = {}
        defaults.update(kwargs)
        defaults['form'] = self.form
        return super().get_form(request, obj, **defaults)

    def get_fieldsets(self, request, obj=None):
        basic_fields = ['name', 'plugin', 'enabled']
        dynamic_fields = []

        if obj and obj.plugin:
            manifest_path = BASE_DIR / "plugins" / obj.plugin.name / "manifest.json"
            if manifest_path.exists():
                with open(manifest_path, 'r') as file:
                    manifest = json.load(file)
                    dynamic_fields = [f'config_{field["name"]}' for field in manifest.get('config_fields', [])]

        fieldsets = [("Basic Information", {'fields': basic_fields})]
        if dynamic_fields:
            fieldsets.append(("Plugin Configuration", {'fields': dynamic_fields}))

        return fieldsets

    def save_model(self, request, obj, form, change):
        config_fields = {k.replace('config_', ''): v for k, v in form.cleaned_data.items() if k.startswith('config_')}
        obj.configuration = config_fields
        super().save_model(request, obj, form, change)

admin.site.register(UserProfile)
admin.site.register(Plugin)
admin.site.register(Message)
admin.site.register(RainGullStandardMessage)
admin.site.register(ServiceInstance, ServiceInstanceAdmin)
