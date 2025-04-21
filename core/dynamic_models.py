from django.db import models
from django.apps import apps
from django.db import connection
import uuid
from django.core.validators import EmailValidator
import logging

logger = logging.getLogger(__name__)

def create_dynamic_model(model_name, fields, table_name, app_label='core'):
    """
    Creates a dynamic Django model with the specified fields.
    
    Args:
        model_name: Name of the model class
        fields: Dictionary of field definitions
        table_name: Name of the database table
        app_label: Django app label (default: 'core')
    """
    try:
        # Check if model is already registered
        try:
            existing_model = apps.get_model(app_label, model_name)
            if existing_model:
                logger.warning(f"Model {app_label}.{model_name} already exists, skipping creation")
                return existing_model
        except LookupError:
            pass  # Model doesn't exist, continue with creation

        # Create the model class
        attrs = {
            '__module__': f'{app_label}.models',
            'Meta': type('Meta', (), {
                'db_table': table_name,
                'app_label': app_label,
            })
        }

        # Add fields to the model
        for field_name, field_def in fields.items():
            field_type = field_def.pop('type')
            field_class = getattr(models, field_type)
            attrs[field_name] = field_class(**field_def)

        # Create the model class
        model = type(model_name, (models.Model,), attrs)

        # Register the model with Django
        apps.register_model(app_label, model)

        # Create the table in the database
        with connection.schema_editor() as schema_editor:
            schema_editor.create_model(model)

        logger.info(f"Created dynamic model {model_name} with table {table_name}")
        return model

    except Exception as e:
        logger.error(f"Error creating dynamic model {model_name}: {str(e)}")
        raise

def delete_dynamic_model(model_name, table_name, app_label='core'):
    """
    Deletes a dynamic Django model and its table.
    
    Args:
        model_name: Name of the model class
        table_name: Name of the database table
        app_label: Django app label (default: 'core')
    """
    try:
        # Get the model
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:
            logger.warning(f"Model {app_label}.{model_name} not found, attempting direct table drop")
            with connection.cursor() as cursor:
                cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
            return

        # Drop the table
        with connection.schema_editor() as schema_editor:
            schema_editor.delete_model(model)

        # Note: We don't unregister the model as Django doesn't support this
        # The model will be removed from the registry on the next server restart

        logger.info(f"Deleted dynamic model {model_name} and table {table_name}")

    except Exception as e:
        logger.error(f"Error in delete_dynamic_model for {model_name}: {str(e)}")
        # Attempt direct table drop as fallback
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
            logger.info(f"Attempted final direct table drop for {table_name}")
        except Exception as drop_error:
            logger.error(f"Failed to drop table {table_name}: {str(drop_error)}")
        raise 