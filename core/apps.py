from django.apps import AppConfig
import logging
from django.db import connection
from django.db.utils import OperationalError

logger = logging.getLogger(__name__)


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        """Initialize the core app."""
        try:
            # Check if we can safely access the database
            try:
                # This is a lightweight check that won't trigger the warning
                connection.introspection.table_names()
            except OperationalError:
                # Database not ready or not accessible
                logger.debug("Database not ready")
        except Exception as e:
            logger.error(f"Error in CoreConfig.ready(): {e}")
