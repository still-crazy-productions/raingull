from django.apps import AppConfig

class CeleryAppConfig(AppConfig):
    name = 'raingull'
    verbose_name = 'Raingull'

    def ready(self):
        """Initialize the app when Django is ready."""
        pass 