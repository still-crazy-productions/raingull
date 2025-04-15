from django import forms
from .models import ImapConfiguration

class ImapConfigurationForm(forms.ModelForm):
    class Meta:
        model = ImapConfiguration
        fields = '__all__'
