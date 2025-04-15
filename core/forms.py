from django import forms
from core.models import ServiceInstance, Plugin
from pathlib import Path
import json

BASE_DIR = Path(__file__).resolve().parent.parent

class DynamicServiceInstanceForm(forms.ModelForm):
    class Meta:
        model = ServiceInstance
        fields = ['name', 'plugin', 'enabled']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        plugins_dir = BASE_DIR / "plugins"
        self.fields['plugin'].queryset = Plugin.objects.filter(enabled=True)

        if 'plugin' in self.data:
            try:
                plugin_id = int(self.data.get('plugin'))
                plugin_instance = Plugin.objects.get(pk=plugin_id)
            except (ValueError, Plugin.DoesNotExist):
                plugin_instance = None
        elif self.instance.pk:
            plugin_instance = self.instance.plugin
        else:
            plugin_instance = None

        if plugin_instance:
            manifest_path = plugins_dir / plugin_instance.name / "manifest.json"
            if manifest_path.exists():
                with open(manifest_path) as file:
                    manifest = json.load(file)
                for field_def in manifest['config_fields']:
                    field_name = field_def['name']
                    field_type = field_def['type']
                    required = field_def.get('required', False)
                    initial = self.instance.configuration.get(field_name) if self.instance.configuration else field_def.get('default')
                    help_text = field_def.get('label', '')

                    if field_type == 'string':
                        field = forms.CharField(required=required, initial=initial, help_text=help_text)
                    elif field_type == 'integer':
                        field = forms.IntegerField(required=required, initial=initial, help_text=help_text)
                    elif field_type == 'password':
                        field = forms.CharField(required=required, widget=forms.PasswordInput, help_text=help_text)
                    elif field_type == 'select':
                        options = field_def.get('options', [])
                        field = forms.ChoiceField(required=required, choices=[(o, o) for o in options], initial=initial, help_text=help_text)
                    else:
                        continue  # handle other types if necessary

                    self.fields[f'config_{field_name}'] = field

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.configuration = {
            k.replace('config_', ''): v for k, v in self.cleaned_data.items() if k.startswith('config_')
        }
        if commit:
            instance.save()
        return instance
