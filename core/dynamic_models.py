from django.db import models
from django.apps import apps
from django.db import connection
import uuid

def create_dynamic_model(model_name, fields, table_name, app_label='core'):
    """
    Create a dynamic Django model with the specified fields.
    
    Args:
        model_name (str): Name of the model class
        fields (dict): Dictionary of field definitions
        table_name (str): Name of the database table
        app_label (str): Django app label
    
    Returns:
        type: Dynamic model class
    """
    # First check if the model is already registered
    try:
        existing_model = apps.get_model(app_label, model_name)
        if existing_model:
            return existing_model
    except LookupError:
        pass

    # Create the model's attributes dictionary
    attrs = {
        '__module__': f'{app_label}.models',
    }
    
    # Create the Meta class with the correct app_label
    meta_attrs = {
        'app_label': app_label,
        'db_table': table_name,
        'managed': True
    }
    attrs['Meta'] = type('Meta', (), meta_attrs)
    
    # Add fields to the model
    for field_name, field_config in fields.items():
        field_type = field_config.get('type')
        field_kwargs = {
            'null': not field_config.get('required', True),
            'blank': not field_config.get('required', True),
            'help_text': field_config.get('help_text', ''),
        }
        
        # Handle field-specific attributes
        if field_type == 'CharField':
            field_kwargs['max_length'] = field_config.get('max_length', 255)
        elif field_type == 'IntegerField':
            field_kwargs['default'] = field_config.get('default', 0)
        elif field_type == 'BooleanField':
            field_kwargs['default'] = field_config.get('default', False)
        elif field_type == 'DateTimeField':
            if field_config.get('auto_now_add'):
                field_kwargs['auto_now_add'] = True
            if field_config.get('auto_now'):
                field_kwargs['auto_now'] = True
        
        # Handle choices if present
        if 'choices' in field_config:
            field_kwargs['choices'] = [(choice, choice) for choice in field_config['choices']]
        
        # Handle unique constraint if present
        if field_config.get('unique', False):
            field_kwargs['unique'] = True
        
        # Create the field instance
        field_class = getattr(models, field_type)
        attrs[field_name] = field_class(**field_kwargs)
    
    # Create the model class
    model = type(model_name, (models.Model,), attrs)
    
    # Register the model with Django
    try:
        apps.register_model(app_label, model)
    except RuntimeError as e:
        if "already registered" not in str(e):
            raise
    
    # Create the table if it doesn't exist
    try:
        with connection.schema_editor() as schema_editor:
            schema_editor.create_model(model)
    except Exception as e:
        if "already exists" not in str(e):
            raise
    
    return model

def delete_dynamic_model(model_name, table_name):
    """
    Deletes a dynamic model.
    """
    try:
        # Try to get the model from Django's app registry
        try:
            model = apps.get_model('core', model_name)
            # If we found the model, unregister it first
            apps.unregister_model('core', model)
        except LookupError:
            # If the model isn't registered, create a minimal model class
            attrs = {
                '__module__': 'core.models',
                'Meta': type('Meta', (), {
                    'db_table': table_name,
                    'app_label': 'core',
                }),
            }
            model = type(model_name, (models.Model,), attrs)
        
        # Delete the table
        with connection.schema_editor() as schema_editor:
            try:
                schema_editor.delete_model(model)
                print(f"Successfully deleted table {table_name}")
            except Exception as e:
                print(f"Error deleting table {table_name}: {e}")
                # Try to drop the table directly if the model deletion fails
                with connection.cursor() as cursor:
                    cursor.execute(f'DROP TABLE IF EXISTS "{table_name}"')
                    print(f"Attempted direct table drop for {table_name}")
    except Exception as e:
        print(f"Error in delete_dynamic_model for {model_name}: {e}")
        # As a last resort, try to drop the table directly
        try:
            with connection.cursor() as cursor:
                cursor.execute(f'DROP TABLE IF EXISTS "{table_name}"')
                print(f"Attempted final direct table drop for {table_name}")
        except Exception as e2:
            print(f"Final error dropping table {table_name}: {e2}") 