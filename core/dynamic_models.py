from django.db import models
from django.apps import apps
from django.db import connection
import uuid

def create_dynamic_model(model_name, table_name, schema, create_table=True):
    """Create a dynamic model for a service instance"""
    try:
        # Create the model class
        attrs = {
            '__module__': 'core.models',
            'Meta': type('Meta', (), {
                'db_table': table_name,
                'app_label': 'core',
            }),
        }

        # Add fields based on schema
        for field_name, field_config in schema.items():
            field_type = field_config.get('type')
            field_kwargs = {}
            
            # Handle required field
            if 'required' in field_config:
                field_kwargs['null'] = not field_config['required']
                field_kwargs['blank'] = not field_config['required']
            
            # Handle max_length for CharField and EmailField
            if field_type in ['CharField', 'EmailField'] and 'max_length' in field_config:
                field_kwargs['max_length'] = field_config['max_length']
            
            # Handle default value
            if 'default' in field_config:
                field_kwargs['default'] = field_config['default']
            
            # Map field types to Django model fields
            if field_type == 'CharField':
                attrs[field_name] = models.CharField(**field_kwargs)
            elif field_type == 'EmailField':
                attrs[field_name] = models.EmailField(**field_kwargs)
            elif field_type == 'TextField':
                attrs[field_name] = models.TextField(**field_kwargs)
            elif field_type == 'DateTimeField':
                attrs[field_name] = models.DateTimeField(**field_kwargs)
            elif field_type == 'BooleanField':
                attrs[field_name] = models.BooleanField(**field_kwargs)
            elif field_type == 'IntegerField':
                attrs[field_name] = models.IntegerField(**field_kwargs)
            elif field_type == 'JSONField':
                attrs[field_name] = models.JSONField(**field_kwargs)
            elif field_type == 'UUIDField':
                attrs[field_name] = models.UUIDField(**field_kwargs)

        # Create the model class
        model = type(model_name, (models.Model,), attrs)

        # Register the model
        apps.register_model('core', model)

        # Create the table if requested
        if create_table:
            with connection.schema_editor() as schema_editor:
                schema_editor.create_model(model)

        return model
    except Exception as e:
        print(f"Error creating dynamic model {model_name}: {e}")
        return None

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