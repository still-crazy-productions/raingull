from django.db import models
from django.apps import apps
from django.db import connection
import uuid
import json

def create_dynamic_model(model_name, table_name, schema):
    """
    Creates a dynamic model based on the provided schema.
    """
    # Create the model class
    attrs = {
        '__module__': 'core.models',
        'Meta': type('Meta', (), {
            'db_table': table_name,
            'app_label': 'core',
        }),
    }
    
    # Add fields from the schema
    for field_name, field_config in schema.items():
        field_type = getattr(models, field_config['type'])
        
        # Convert required to null/blank
        field_kwargs = {}
        for k, v in field_config.items():
            if k == 'type':
                continue
            elif k == 'required':
                field_kwargs['null'] = not v
                field_kwargs['blank'] = not v
            else:
                field_kwargs[k] = v
        
        attrs[field_name] = field_type(**field_kwargs)
    
    # Create the model class
    model = type(model_name, (models.Model,), attrs)
    
    # Register the model with Django
    apps.register_model('core', model)
    
    # Create the table
    with connection.schema_editor() as schema_editor:
        schema_editor.create_model(model)
    
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