from django import forms
from core.models import ServiceInstance, Plugin
from pathlib import Path
import json

BASE_DIR = Path(__file__).resolve().parent.parent

class DynamicServiceInstanceForm(forms.ModelForm):
    class Meta:
        model = ServiceInstance
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Get the plugin from the form data or instance
        plugin = None
        if 'plugin' in self.data:
            try:
                plugin_id = int(self.data.get('plugin'))
                plugin = Plugin.objects.get(id=plugin_id)
            except (ValueError, Plugin.DoesNotExist):
                pass
        elif self.instance and self.instance.plugin:
            plugin = self.instance.plugin

        if plugin:
            manifest = plugin.get_manifest()
            if manifest and 'config_fields' in manifest:
                for field in manifest['config_fields']:
                    field_name = f"config_{field['name']}"
                    
                    # Get the current value from the instance's config if it exists
                    current_value = None
                    if self.instance and self.instance.config:
                        current_value = self.instance.config.get(field['name'])
                    
                    if field['type'] == 'select':
                        self.fields[field_name] = forms.ChoiceField(
                            choices=[(opt, opt) for opt in field['options']],
                            required=field.get('required', False),
                            initial=current_value or field.get('default', ''),
                            label=field.get('label', field['name'].replace('_', ' ').title())
                        )
                    elif field['type'] == 'integer':
                        self.fields[field_name] = forms.IntegerField(
                            required=field.get('required', False),
                            initial=current_value or field.get('default', 0),
                            label=field.get('label', field['name'].replace('_', ' ').title())
                        )
                    elif field['type'] == 'password':
                        self.fields[field_name] = forms.CharField(
                            widget=forms.PasswordInput(),
                            required=field.get('required', False),
                            initial=current_value or '',
                            label=field.get('label', field['name'].replace('_', ' ').title())
                        )
                    else:  # string, text, etc.
                        self.fields[field_name] = forms.CharField(
                            required=field.get('required', False),
                            initial=current_value or field.get('default', ''),
                            label=field.get('label', field['name'].replace('_', ' ').title())
                        )

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

class ServiceInstanceForm(forms.ModelForm):
    class Meta:
        model = ServiceInstance
        fields = ['name', 'plugin', 'config', 'incoming_enabled', 'outgoing_enabled']
        widgets = {
            'config': forms.HiddenInput(),  # Hide the raw config field
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Get the plugin from the form data or instance
        plugin = None
        if 'plugin' in self.data:
            try:
                plugin_id = int(self.data.get('plugin'))
                plugin = Plugin.objects.get(id=plugin_id)
            except (ValueError, Plugin.DoesNotExist):
                pass
        elif self.instance and self.instance.plugin:
            plugin = self.instance.plugin

        if plugin:
            manifest = plugin.get_manifest()
            if manifest and 'config_fields' in manifest:
                # Create dynamic fields based on the manifest
                for field_config in manifest['config_fields']:
                    field_name = field_config['name']
                    field_type = field_config['type']
                    required = field_config.get('required', True)
                    default = field_config.get('default', None)
                    label = field_config.get('label', field_name.replace('_', ' ').title())
                    
                    if field_type == 'select':
                        self.fields[f'config_{field_name}'] = forms.ChoiceField(
                            required=required,
                            initial=default,
                            choices=[(opt, opt) for opt in field_config['options']],
                            label=label
                        )
                    elif field_type == 'integer':
                        self.fields[f'config_{field_name}'] = forms.IntegerField(
                            required=required,
                            initial=default,
                            label=label
                        )
                    elif field_type == 'password':
                        self.fields[f'config_{field_name}'] = forms.CharField(
                            required=required,
                            initial=default,
                            widget=forms.PasswordInput(),
                            label=label
                        )
                    else:  # string, text, etc.
                        self.fields[f'config_{field_name}'] = forms.CharField(
                            required=required,
                            initial=default,
                            label=label
                        )

    def clean(self):
        cleaned_data = super().clean()
        config = {}
        
        # Collect all config_* fields
        for key, value in cleaned_data.items():
            if key.startswith('config_'):
                field_name = key[7:]  # Remove 'config_' prefix
                config[field_name] = value
        
        cleaned_data['config'] = config
        return cleaned_data
