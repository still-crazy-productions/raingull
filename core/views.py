# core/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from core.models import ServiceInstance, Plugin, RaingullStandardMessage, UserServiceActivation, RaingullUser, OutgoingMessageQueue, AuditLog, ServiceMessageTemplate
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.module_loading import import_string
import json
import os
import imaplib
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from django.utils import timezone
import logging
from django.contrib.auth.models import User
from django.db.models import Count
import pytz
from django.conf import settings
from django.template.loader import get_template, render_to_string
from django.core.mail import send_mail
from django.utils.html import strip_tags
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
import secrets
import uuid

logger = logging.getLogger(__name__)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def service_instance_list(request):
    instances = ServiceInstance.objects.select_related('plugin').all()
    plugins = Plugin.objects.filter(enabled=True)
    
    # Set plugin capabilities for each instance
    for instance in instances:
        manifest = instance.plugin.get_manifest()
        if manifest:
            instance._supports_incoming = manifest.get('incoming', False)
            instance._supports_outgoing = manifest.get('outgoing', False)
        else:
            instance._supports_incoming = False
            instance._supports_outgoing = False
    
    return render(request, 'core/service_instance_list.html', {
        'instances': instances,
        'plugins': plugins
    })

@login_required
@user_passes_test(lambda u: u.is_superuser)
def get_plugin_fields(request):
    plugin_name = request.GET.get('plugin')
    if not plugin_name:
        return JsonResponse({'error': 'Plugin name is required'}, status=400)
    
    plugin = get_object_or_404(Plugin, name=plugin_name, enabled=True)
    
    try:
        # Get the plugin's manifest
        manifest_path = os.path.join(settings.BASE_DIR, 'plugins', plugin.name, 'manifest.json')
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
        
        fields = manifest.get('user_config_fields', [])
        
        # Check if the plugin has a test connection function
        try:
            import_string(f'plugins.{plugin.name}.views.test_connection')
            has_test_connection = True
        except ImportError:
            has_test_connection = False
            
        return JsonResponse({
            'fields': fields,
            'has_test_connection': has_test_connection
        })
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return JsonResponse({'error': f'Error loading plugin manifest: {str(e)}'}, status=404)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def create_service_instance(request):
    # Get plugin from URL parameter
    plugin_id = request.GET.get('plugin')
    plugin_name = request.GET.get('plugin_name')
    
    if not plugin_id and not plugin_name:
        messages.error(request, 'No plugin specified')
        return redirect('core:service_instance_list')
    
    try:
        # Try to get plugin by ID first, then by name
        if plugin_id:
            plugin = get_object_or_404(Plugin, id=plugin_id, enabled=True)
        else:
            plugin = get_object_or_404(Plugin, name=plugin_name, enabled=True)
    except Plugin.DoesNotExist:
        messages.error(request, 'Plugin not found or not enabled')
        return redirect('core:service_instance_list')
    
    # Get the plugin's manifest
    try:
        manifest = plugin.get_manifest()
        if not manifest:
            messages.error(request, 'Could not load plugin manifest')
            return redirect('core:service_instance_list')
            
        config_fields = manifest.get('config_fields', [])
        print(f"Debug: Plugin {plugin.name} config fields: {config_fields}")  # Debug log
        
        # Check if the plugin has a test connection function
        try:
            import_string(f'plugins.{plugin.name}.views.test_connection')
            has_test_connection = True
        except ImportError:
            has_test_connection = False
            
    except Exception as e:
        messages.error(request, f'Error loading plugin manifest: {str(e)}')
        return redirect('core:service_instance_list')
    
    if request.method == 'POST':
        try:
            # Create new service instance
            instance = ServiceInstance(
                plugin=plugin,
                name=request.POST.get('name'),
                incoming_enabled=manifest.get('incoming', False),
                outgoing_enabled=manifest.get('outgoing', False)
            )
            
            # Build config dictionary
            config = {}
            for field in config_fields:
                field_name = field['name']
                config[field_name] = request.POST.get(f'config_{field_name}')
            
            instance.config = config
            instance.save()
            
            messages.success(request, 'Service instance created successfully')
            return redirect('core:service_instance_list')
            
        except Exception as e:
            messages.error(request, f'Error creating service instance: {str(e)}')
            return redirect('core:service_instance_list')
    
    context = {
        'plugin': plugin,
        'config_fields': config_fields,
        'manifest': manifest,
        'has_test_connection': has_test_connection
    }
    print(f"Debug: Context being passed to template: {context}")  # Debug log
    
    # Force template reloading
    template = get_template('core/create_service_instance.html')
    print(f"Debug: Template path: {template.origin.name}")
    
    return render(request, 'core/create_service_instance.html', context)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_service_instance(request, instance_id=None):
    instance = get_object_or_404(ServiceInstance, pk=instance_id) if instance_id else None
    
    # Get the plugin manifest to check capabilities
    manifest = instance.plugin.get_manifest() if instance else None
    
    # Get configuration fields from manifest
    config_fields = []
    if manifest:
        config_fields = manifest.get('config_fields', [])
        # Add current values to the fields
        for field in config_fields:
            field['value'] = instance.config.get(field['name'], '')
    
    # Check if the plugin has a test connection function
    has_test_connection = False
    if instance:
        try:
            module_path = f'plugins.{instance.plugin.name}.views'
            module = __import__(module_path, fromlist=['test_connection'])
            has_test_connection = hasattr(module, 'test_connection')
            print(f"Test connection available for {instance.plugin.name}: {has_test_connection}")
        except ImportError:
            print(f"Error importing views for {instance.plugin.name}")
            has_test_connection = False
    
    if request.method == 'POST':
        print("Form data:", request.POST)
        # Handle the POST data directly
        if instance:
            instance.name = request.POST.get('name')
            instance.incoming_enabled = request.POST.get('incoming_enabled') == 'on'
            instance.outgoing_enabled = request.POST.get('outgoing_enabled') == 'on'
            
            # Update config
            config = {}
            for key, value in request.POST.items():
                if key.startswith('config_'):
                    config[key[7:]] = value
            instance.config = config
            
            instance.save()
            messages.success(request, 'Service instance saved successfully.')
            return redirect('core:service_instance_list')
        else:
            messages.error(request, 'Instance not found.')
            return redirect('core:service_instance_list')
    
    return render(request, 'core/manage_service_instance.html', {
        'instance': instance,
        'manifest': manifest,
        'has_test_connection': has_test_connection,
        'config_fields': config_fields
    })

@login_required
@user_passes_test(lambda u: u.is_superuser)
@csrf_exempt
def test_plugin_connection(request, plugin_name):
    print(f"Test connection request for plugin: {plugin_name}")
    
    if request.method != 'POST':
        print("Invalid method:", request.method)
        return JsonResponse({'success': False, 'message': 'Only POST method is allowed'})
    
    plugin = get_object_or_404(Plugin, name=plugin_name, enabled=True)
    print(f"Found plugin: {plugin.name}")
    
    try:
        # Import the test_connection function from the plugin's views
        print(f"Importing views from plugins.{plugin.name}.views")
        module_path = f'plugins.{plugin.name}.views'
        module = __import__(module_path, fromlist=['test_connection'])
        test_connection = getattr(module, 'test_connection')
        print("Found test_connection function")
        
        # Parse the JSON data from the request body
        print("Request body:", request.body)
        try:
            data = json.loads(request.body)
            print("Parsed data:", data)
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON: {str(e)}")
            return JsonResponse({
                'success': False,
                'message': f'Invalid JSON data: {str(e)}'
            })
        
        # Call the plugin's test_connection function
        print("Calling test_connection function")
        try:
            response = test_connection(request, data)
            print("Test connection response:", response)
            
            # If the response is already a JsonResponse, return it directly
            if isinstance(response, JsonResponse):
                return response
            # If it's a dictionary, convert it to a JsonResponse
            elif isinstance(response, dict):
                return JsonResponse(response)
            # If it's a string, assume it's an error message
            elif isinstance(response, str):
                return JsonResponse({
                    'success': False,
                    'message': response
                })
            # For any other type, return an error
            else:
                print(f"Unexpected response type: {type(response)}")
                return JsonResponse({
                    'success': False,
                    'message': 'Invalid response from plugin'
                })
                
        except Exception as e:
            print(f"Error in test_connection function: {str(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'message': f'Error in test connection: {str(e)}'
            })
            
    except (ImportError, AttributeError) as e:
        print(f"Error loading test connection function: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': f'Error loading test connection function: {str(e)}'
        })
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'message': f'Unexpected error: {str(e)}'
        })

@login_required
@user_passes_test(lambda u: u.is_superuser)
def delete_service_instance(request, instance_id):
    instance = get_object_or_404(ServiceInstance, pk=instance_id)
    if request.method == 'POST':
        instance_name = instance.name
        instance.delete()
        messages.success(request, f'Service instance "{instance_name}" has been deleted.')
        return redirect('core:service_instance_list')
    return redirect('core:manage_service_instance', instance_id=instance_id)

@login_required
def test_services(request):
    """
    Test page for manually running service operations
    """
    # Get all service instances with their plugin instances
    service_instances = ServiceInstance.objects.select_related('plugin', 'plugin_instance').all()
    
    # Debug logging
    logger.debug(f"Found {len(service_instances)} service instances")
    for instance in service_instances:
        logger.debug(f"Instance: {instance.name}, Plugin: {instance.plugin.name}")
        try:
            # Get the manifest first
            manifest = instance.plugin.get_manifest()
            if manifest:
                instance.plugin.manifest = manifest
                logger.debug(f"Manifest loaded: {manifest}")
                
                # Update instance capabilities based on manifest
                instance._supports_incoming = manifest.get('incoming', False)
                instance._supports_outgoing = manifest.get('outgoing', False)
            else:
                logger.error(f"Failed to load manifest for {instance.name}")
                instance._supports_incoming = False
                instance._supports_outgoing = False
            
            # Get the plugin instance
            plugin_instance = instance.get_plugin_instance()
            if plugin_instance:
                # Store the plugin instance in a temporary attribute
                instance._plugin_instance = plugin_instance
                logger.debug(f"Plugin instance loaded: {plugin_instance}")
            else:
                logger.error(f"Failed to load plugin instance for {instance.name}")
            
        except Exception as e:
            logger.error(f"Error loading plugin instance or manifest for {instance.name}: {e}")
            instance._supports_incoming = False
            instance._supports_outgoing = False
    
    # Get all users for the activation form
    users = RaingullUser.objects.all()
    
    return render(request, 'core/test_services.html', {
        'service_instances': service_instances,
        'users': users
    })

@login_required
def test_imap_retrieve(request, instance_id):
    try:
        service_instance = ServiceInstance.objects.get(id=instance_id)
        plugin = service_instance.get_plugin_instance()
        result = plugin.retrieve_messages()
        return JsonResponse(result)
    except ServiceInstance.DoesNotExist:
        return JsonResponse({"success": False, "message": "Service instance not found"})
    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)})

@login_required
def test_translate_messages(request, instance_id):
    try:
        service_instance = ServiceInstance.objects.get(id=instance_id)
        plugin = service_instance.get_plugin_instance()
        
        # Get the incoming message model
        incoming_model = service_instance.get_message_model('incoming')
        if not incoming_model:
            return JsonResponse({"success": False, "message": "No incoming message model found"})
            
        # Get all unprocessed messages
        messages = incoming_model.objects.filter(status='new')
        message_count = messages.count()
        print(f"Found {message_count} unprocessed messages")
        
        # Log details of each message
        for msg in messages:
            print(f"\nMessage ID: {msg.id}")
            print(f"Subject: {msg.subject}")
            print(f"From: {msg.email_from}")
            print(f"Date: {msg.date}")
            print(f"Status: {msg.status}")
            print(f"Body length: {len(msg.body) if msg.body else 0}")
            if hasattr(msg, 'headers'):
                print(f"Headers: {msg.headers}")
            print("-" * 50)
        
        translated_count = 0
        
        # Get the Raingull standard message model
        from email.utils import parsedate_to_datetime
        
        for message in messages:
            try:
                print(f"\nAttempting to translate message {message.id}:")
                print(f"Subject: {message.subject}")
                
                # Parse the IMAP date string
                received_at = parsedate_to_datetime(message.date)
                print(f"Parsed date: {received_at}")
                
                # Create a new Raingull standard message
                standard_message = RaingullStandardMessage.create_standard_message(
                    raingull_id=message.raingull_id,  # Copy the raingull_id from the source message
                    source_service=service_instance,
                    source_message_id=message.imap_message_id,
                    subject=message.subject,
                    body=message.body,
                    sender=message.email_from,
                    recipients=message.to,  # Already a list, no need to convert to JSON
                    date=received_at,
                    headers=message.headers if hasattr(message, 'headers') else {}
                )
                print(f"Successfully created standard message with raingull_id: {standard_message.raingull_id}")
                
                # Mark the original message as processed
                message.status = 'processed'
                message.processed_at = timezone.now()
                message.save()
                print(f"Marked original message as processed")
                
                translated_count += 1
                
            except Exception as e:
                print(f"Error translating message {message.id}: {str(e)}")
                print(f"Error type: {type(e)}")
                import traceback
                print(f"Traceback: {traceback.format_exc()}")
                continue
        
        return JsonResponse({
            "success": True,
            "message": f"Found {message_count} messages, translated {translated_count} to Raingull standard format"
        })
        
    except ServiceInstance.DoesNotExist:
        return JsonResponse({"success": False, "message": "Service instance not found"})
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        print(f"Error type: {type(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({"success": False, "message": str(e)})

@login_required
def test_smtp_send(request, instance_id):
    """Test sending messages via SMTP service instance."""
    try:
        service_instance = ServiceInstance.objects.get(id=instance_id)
        if service_instance.plugin.name != 'smtp_plugin':
            return JsonResponse({
                'success': False,
                'message': 'This endpoint is only for SMTP service instances'
            })

        # Get the plugin instance
        plugin_instance = service_instance.get_plugin_instance()
        if not plugin_instance:
            return JsonResponse({
                'success': False,
                'message': 'Could not create plugin instance'
            })

        # Get messages that have been processed by IMAP but not by SMTP
        unprocessed_messages = RaingullStandardMessage.objects.filter(
            source_service__isnull=False,  # Has been processed by some service
            source_service__plugin__name='imap'  # Specifically by IMAP
        ).exclude(
            source_service=service_instance  # But not by this SMTP service
        )

        if not unprocessed_messages.exists():
            return JsonResponse({
                'success': True,
                'message': 'No unprocessed messages found'
            })

        # Get the outgoing message model
        outgoing_model = service_instance.get_message_model('outgoing')
        if not outgoing_model:
            return JsonResponse({
                'success': False,
                'message': 'Could not get outgoing message model'
            })

        # Process each message
        processed_count = 0
        for message in unprocessed_messages:
            try:
                # Translate the message to SMTP format
                translated_message = plugin_instance.translate_from_raingull(message)
                
                # Create the outgoing message
                outgoing_message = outgoing_model.objects.create(
                    raingull_id=message.raingull_id,
                    to=translated_message['to'],
                    subject=translated_message['subject'],
                    body=translated_message['body'],
                    headers=translated_message['headers'],
                    status='queued',
                    created_at=timezone.now()
                )
                
                # Mark the standard message as processed by this SMTP service
                message.source_service = service_instance
                message.save()
                
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Error processing message {message.raingull_id}: {e}")
                continue

        return JsonResponse({
            'success': True,
            'message': f'Successfully processed {processed_count} messages'
        })

    except ServiceInstance.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Service instance not found'
        })
    except Exception as e:
        logger.error(f"Error in test_smtp_send: {e}")
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        })

@login_required
def test_smtp_translate(request, instance_id):
    """Test translating messages to SMTP format."""
    try:
        service_instance = ServiceInstance.objects.get(id=instance_id)
        if service_instance.plugin.name != 'smtp_plugin':
            return JsonResponse({
                'success': False,
                'message': 'This endpoint is only for SMTP service instances'
            })

        # Get the plugin instance
        plugin_instance = service_instance.get_plugin_instance()
        if not plugin_instance:
            return JsonResponse({
                'success': False,
                'message': 'Could not create plugin instance'
            })

        # Get unprocessed messages from Raingull Standard table
        unprocessed_messages = RaingullStandardMessage.objects.filter(
            processed=False
        )

        if not unprocessed_messages.exists():
            return JsonResponse({
                'success': True,
                'message': 'No unprocessed messages found'
            })

        # Process each message
        translated_count = 0
        for message in unprocessed_messages:
            try:
                # Translate the message to SMTP format
                translated_message = plugin_instance.translate_from_raingull(message)
                translated_count += 1
                
            except Exception as e:
                logger.error(f"Error translating message {message.raingull_id}: {e}")
                continue

        return JsonResponse({
            'success': True,
            'message': f'Successfully translated {translated_count} messages to SMTP format'
        })

    except ServiceInstance.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Service instance not found'
        })
    except Exception as e:
        logger.error(f"Error in test_smtp_translate: {e}")
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        })

@login_required
def get_service_config_fields(request, instance_id):
    """Get configuration fields for a service instance."""
    try:
        service_instance = ServiceInstance.objects.get(id=instance_id)
        manifest = service_instance.plugin.get_manifest()
        config_fields = manifest.get('user_config_fields', [])
        
        return JsonResponse({
            'success': True,
            'fields': config_fields
        })
    except ServiceInstance.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Service instance not found'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        })

@login_required
@csrf_exempt
def activate_service(request):
    """Activate a service instance for a user."""
    if request.method != 'POST':
        return JsonResponse({
            'success': False,
            'message': 'Only POST method is allowed'
        })
    
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        service_instance_id = data.get('service_instance_id')
        config = data.get('config', {})
        
        if not all([user_id, service_instance_id]):
            return JsonResponse({
                'success': False,
                'message': 'Missing required fields'
            })
        
        # Get the service instance
        service_instance = ServiceInstance.objects.get(id=service_instance_id)
        
        # Get or create the activation
        activation, created = UserServiceActivation.objects.get_or_create(
            user_id=user_id,
            service_instance_id=service_instance_id,
            defaults={
                'config': config,
                'is_active': True
            }
        )
        
        if not created:
            activation.config = config
            activation.is_active = True
            activation.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Service {"activated" if created else "updated"} successfully'
        })
        
    except ServiceInstance.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Service instance not found'
        })
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid JSON data'
        })
    except Exception as e:
        logger.error(f"Error activating service: {e}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        })

@login_required
def queue_outgoing_messages(request, instance_id):
    """Queue outgoing messages for all active users of a service instance."""
    try:
        service_instance = ServiceInstance.objects.get(id=instance_id)
        if not service_instance.outgoing_enabled:
            return JsonResponse({
                'success': False,
                'message': 'This service instance does not support outgoing messages'
            })

        # Get the plugin instance
        plugin = service_instance.get_plugin_instance()
        if not plugin:
            return JsonResponse({
                'success': False,
                'message': 'Could not create plugin instance'
            })

        # Get the outgoing message model
        outgoing_model = service_instance.get_message_model('outgoing')
        if not outgoing_model:
            return JsonResponse({
                'success': False,
                'message': 'No outgoing message model found'
            })

        # Get all queued messages for this service
        messages = outgoing_model.objects.filter(status='queued')

        # Get all active users for this service
        active_users = UserServiceActivation.objects.filter(
            service_instance=service_instance,
            is_active=True
        ).select_related('user')

        if not active_users.exists():
            return JsonResponse({
                'success': False,
                'message': 'No active users found for this service'
            })

        queued_count = 0

        for message in messages:
            # For each active user, create a queue entry
            for activation in active_users:
                try:
                    # Find the original Raingull standard message
                    raingull_message = RaingullStandardMessage.objects.get(
                        raingull_id=message.raingull_id
                    )
                    
                    # Create queue entry
                    OutgoingMessageQueue.objects.create(
                        raingull_message=raingull_message,
                        user=activation.user,
                        service_instance=service_instance,
                        raingull_id=raingull_message.raingull_id,  # Use the raingull_id from the standard message
                        status='queued'
                    )
                    queued_count += 1
                except RaingullStandardMessage.DoesNotExist:
                    logger.error(f"Could not find Raingull standard message for {message.raingull_id}")
                    continue
                except Exception as e:
                    logger.error(f"Error creating queue entry: {e}")
                    continue

        return JsonResponse({
            'success': True,
            'message': f'Successfully queued {queued_count} messages for {active_users.count()} users'
        })

    except ServiceInstance.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Service instance not found'
        })
    except Exception as e:
        logger.error(f"Error in queue_outgoing_messages: {e}")
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        })

@login_required
def send_queued_messages(request):
    """Send messages from the OutgoingMessageQueue."""
    try:
        # Get all queued messages
        queued_messages = OutgoingMessageQueue.objects.filter(
            status='queued'
        ).select_related(
            'raingull_message',
            'user',
            'service_instance'
        )
        
        message_count = queued_messages.count()
        if message_count == 0:
            return JsonResponse({
                'success': True,
                'message': 'No queued messages found'
            })
            
        logger.info(f"Found {message_count} queued messages to send")
        
        for message in queued_messages:
            try:
                # Get the plugin instance
                plugin = message.service_instance.get_plugin_instance()
                if not plugin:
                    error_msg = f"Could not get plugin instance for {message.service_instance.name}"
                    logger.error(error_msg)
                    message.status = 'failed'
                    message.error_message = error_msg
                    message.save()
                    continue
                
                # Get the user's service activation to get the correct email address
                try:
                    user_activation = UserServiceActivation.objects.get(
                        user=message.user,
                        service_instance=message.service_instance,
                        is_active=True
                    )
                except UserServiceActivation.DoesNotExist:
                    error_msg = f"User {message.user.username} is not activated for service {message.service_instance.name}"
                    logger.error(error_msg)
                    message.status = 'failed'
                    message.error_message = error_msg
                    message.save()
                    continue
                
                # Get the service-specific message
                outgoing_model = message.service_instance.get_message_model('outgoing')
                service_message = outgoing_model.objects.get(
                    raingull_id=message.raingull_message.raingull_id
                )
                
                # Get the recipient email from the user's service activation
                recipient_email = user_activation.config.get('email_address')
                if not recipient_email:
                    error_msg = f"No email address configured for user {message.user.username}"
                    logger.error(error_msg)
                    message.status = 'failed'
                    message.error_message = error_msg
                    message.save()
                    continue
                
                # Prepare message data for sending
                message_data = {
                    'to': recipient_email,  # Use the email from user's service activation
                    'subject': service_message.subject,
                    'body': service_message.body,
                    'headers': service_message.headers if hasattr(service_message, 'headers') else {}
                }
                
                # Send the message
                success = plugin.send_message(message.service_instance, message_data)
                
                # Update message status based on success
                if success:
                    message.status = 'sent'
                    message.processed_at = timezone.now()
                    message.save()
                    logger.info(f"Successfully sent message to {recipient_email}")
                else:
                    error_msg = "Failed to send message"
                    logger.error(error_msg)
                    message.status = 'failed'
                    message.error_message = error_msg
                    message.save()
                    
            except Exception as e:
                error_msg = f"Error processing message: {e}"
                logger.error(error_msg)
                message.status = 'failed'
                message.error_message = str(e)
                message.save()
                continue
                
        return JsonResponse({
            'success': True,
            'message': f'Processed {message_count} queued messages'
        })
        
    except Exception as e:
        error_msg = f"Error in send_queued_messages: {e}"
        logger.error(error_msg)
        return JsonResponse({
            'success': False,
            'message': error_msg
        })

@login_required
@user_passes_test(lambda u: u.is_superuser)
def audit_log(request):
    """
    View for displaying the audit log with statistics
    """
    # Get 24-hour activity summary
    twenty_four_hours_ago = timezone.now() - timedelta(hours=24)
    
    # Get recent activity by type
    recent_activity = AuditLog.objects.filter(
        timestamp__gte=twenty_four_hours_ago
    ).values('event_type').annotate(count=Count('id')).order_by('-count')
    
    # Get service activity
    service_activity = AuditLog.objects.filter(
        timestamp__gte=twenty_four_hours_ago
    ).values('service_instance__name').annotate(count=Count('id')).order_by('-count')
    
    # Get error count
    error_count = AuditLog.objects.filter(
        timestamp__gte=twenty_four_hours_ago,
        status='error'
    ).count()
    
    # Get all audit logs
    audit_logs = AuditLog.objects.select_related('service_instance').order_by('-timestamp')
    
    return render(request, 'core/audit_log.html', {
        'recent_activity': recent_activity,
        'service_activity': service_activity,
        'error_count': error_count,
        'audit_logs': audit_logs,
    })

@login_required
def user_profile(request, user_id=None):
    # If user_id is provided, get that user's profile
    # Otherwise, use the current user's profile
    if user_id:
        if not request.user.is_superuser:
            messages.error(request, "You don't have permission to view other users' profiles.")
            return redirect('core:my_profile')
        profile_user = get_object_or_404(RaingullUser, id=user_id)
    else:
        profile_user = request.user

    if request.method == 'POST':
        # Only allow updating your own profile
        if profile_user != request.user:
            messages.error(request, "You can only update your own profile.")
            return redirect('core:user_profile', user_id=user_id)

        # Handle form submission
        full_name = request.POST.get('full_name')
        timezone = request.POST.get('timezone')
        email = request.POST.get('email')
        current_password = request.POST.get('current_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        mfa_enabled = request.POST.get('mfa_enabled') == 'on'

        # Update basic info
        profile_user.full_name = full_name
        profile_user.timezone = timezone
        profile_user.email = email

        # Handle password change if provided
        if current_password and new_password and confirm_password:
            if profile_user.check_password(current_password):
                if new_password == confirm_password:
                    profile_user.set_password(new_password)
                else:
                    messages.error(request, "New passwords do not match")
            else:
                messages.error(request, "Current password is incorrect")

        # Handle MFA
        if mfa_enabled and not profile_user.mfa_enabled:
            # Generate new MFA secret
            profile_user.mfa_secret = generate_mfa_secret()
        elif not mfa_enabled and profile_user.mfa_enabled:
            profile_user.mfa_secret = ''

        profile_user.mfa_enabled = mfa_enabled
        profile_user.save()

        messages.success(request, "Profile updated successfully")
        return redirect('core:user_profile', user_id=user_id)

    # Get all available timezones
    timezones = pytz.common_timezones

    return render(request, 'core/user_profile.html', {
        'profile_user': profile_user,
        'timezones': timezones,
        'is_own_profile': profile_user == request.user
    })

@login_required
@user_passes_test(lambda u: u.is_superuser)
def plugin_manager(request):
    plugins_dir = os.path.join(settings.BASE_DIR, 'plugins')
    installed_plugins = {p.name: p for p in Plugin.objects.all()}
    available_plugins = []

    # Scan plugins directory
    if os.path.exists(plugins_dir):
        for plugin_name in os.listdir(plugins_dir):
            plugin_path = os.path.join(plugins_dir, plugin_name)
            manifest_path = os.path.join(plugin_path, 'manifest.json')
            
            if os.path.isdir(plugin_path) and os.path.exists(manifest_path):
                try:
                    with open(manifest_path, 'r') as f:
                        manifest = json.load(f)
                        
                    plugin_info = {
                        'name': plugin_name,
                        'friendly_name': manifest.get('friendly_name', plugin_name),
                        'description': manifest.get('description', 'No description available'),
                        'version': manifest.get('version', '1.0.0'),
                        'incoming': manifest.get('incoming', False),
                        'outgoing': manifest.get('outgoing', False),
                        'enabled': plugin_name in installed_plugins,
                        'plugin': installed_plugins.get(plugin_name)
                    }
                    available_plugins.append(plugin_info)
                except json.JSONDecodeError:
                    continue

    # Handle POST request to enable/disable plugins
    if request.method == 'POST':
        plugin_name = request.POST.get('plugin_name')
        action = request.POST.get('action')
        
        if plugin_name and action:
            if action == 'enable':
                if plugin_name not in installed_plugins:
                    # Find the plugin info for this plugin
                    plugin_info = next((p for p in available_plugins if p['name'] == plugin_name), None)
                    if plugin_info:
                        Plugin.objects.create(
                            name=plugin_name,
                            friendly_name=plugin_info['friendly_name'],
                            version=plugin_info['version'],
                            enabled=True
                        )
                        messages.success(request, f'Plugin {plugin_name} enabled successfully.')
                else:
                    plugin = installed_plugins[plugin_name]
                    plugin.enabled = True
                    plugin.save()
                    messages.success(request, f'Plugin {plugin_name} enabled successfully.')
            elif action == 'disable':
                if plugin_name in installed_plugins:
                    plugin = installed_plugins[plugin_name]
                    plugin.enabled = False
                    plugin.save()
                    messages.success(request, f'Plugin {plugin_name} disabled successfully.')
            
            return redirect('core:plugin_manager')

    return render(request, 'core/plugin_manager.html', {
        'plugins': available_plugins
    })

@login_required
@user_passes_test(lambda u: u.is_superuser)
def user_list(request):
    """List all users in the system. Requires superuser permissions."""
    users = RaingullUser.objects.all().order_by('username')
    return render(request, 'core/user_list.html', {
        'users': users
    })

@login_required
@user_passes_test(lambda u: u.is_superuser)
def invite_user(request):
    """View for inviting new users."""
    # Get all outgoing-enabled service instances
    service_instances = ServiceInstance.objects.filter(
        outgoing_enabled=True,
        plugin__enabled=True
    ).select_related('plugin')

    if request.method == 'POST':
        # Get form data
        service_instance_id = request.POST.get('service_instance')
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        is_superuser = request.POST.get('is_superuser') == 'on'
        is_staff = request.POST.get('is_staff') == 'on'

        try:
            service_instance = ServiceInstance.objects.get(id=service_instance_id)
            
            # Get the plugin's user config fields
            manifest = service_instance.plugin.get_manifest()
            user_config_fields = manifest.get('user_config_fields', [])
            
            # Build config from form data
            config = {}
            for field in user_config_fields:
                field_name = field['name']
                config[field_name] = request.POST.get(f'config_{field_name}')
            
            # Generate a unique username based on the service-specific identifier
            username = config.get('email_address', f"{first_name.lower()}.{last_name.lower()}")
            
            # Create inactive user
            user = RaingullUser.objects.create(
                username=username,
                first_name=first_name,
                last_name=last_name,
                is_superuser=is_superuser,
                is_staff=is_staff,
                is_active=False
            )

            # Generate activation token
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            activation_token = f"{uid}-{token}"  # Combine uid and token

            # Create service activation with config
            UserServiceActivation.objects.create(
                user=user,
                service_instance=service_instance,
                config=config,
                is_active=True
            )

            # Get or create invitation message
            try:
                invitation_message = ServiceMessageTemplate.objects.get(service_instance=service_instance)
            except ServiceMessageTemplate.DoesNotExist:
                # Create default message if none exists
                invitation_message = ServiceMessageTemplate.objects.create(
                    service_instance=service_instance,
                    subject="Welcome to Raingull",
                    message="""Hello {first_name},

You have been invited to join Raingull. To activate your account, please click the link below:

{activation_url}

Once activated, you will be able to receive messages through this service.

Best regards,
The Raingull Team""",
                    activation_url=f"{request.scheme}://{request.get_host()}/users/activate/{{token}}/"
                )

            # Format the message with user's information
            formatted_message = invitation_message.message.format(
                first_name=first_name,
                activation_url=invitation_message.activation_url.format(token=activation_token)
            )

            # Generate a UUID for the message
            message_id = str(uuid.uuid4())

            # Create a minimal RaingullStandardMessage for the invitation
            raingull_message = RaingullStandardMessage.objects.create(
                raingull_id=message_id,
                source_service=service_instance,
                source_message_id=message_id,
                subject=invitation_message.subject,
                body=formatted_message,  # Use the formatted message
                sender=service_instance.config.get('from_email', 'noreply@raingull.com'),
                recipients=[config['email_address']],
                date=timezone.now(),
                headers={
                    'is_invitation': 'true',
                    'recipient_email': config['email_address']
                }
            )

            # Get the outgoing message model
            outgoing_model = service_instance.get_message_model('outgoing')
            if outgoing_model:
                # Create the service-specific outgoing message
                outgoing_message = outgoing_model.objects.create(
                    raingull_id=message_id,
                    to=config['email_address'],
                    subject=invitation_message.subject,
                    body=formatted_message,  # Use the formatted message
                    headers={},
                    status='queued',
                    created_at=timezone.now()
                )

                # Queue the message for sending
                OutgoingMessageQueue.objects.create(
                    raingull_message=raingull_message,
                    user=user,
                    service_instance=service_instance,
                    raingull_id=message_id,
                    status='queued'
                )

            messages.success(request, f"Invitation queued for {first_name} {last_name}")
            return redirect('core:user_list')

        except Exception as e:
            messages.error(request, f"Error sending invitation: {str(e)}")
            return redirect('core:invite_user')

    return render(request, 'core/invite_user.html', {
        'service_instances': service_instances
    })

def activate_user(request, token):
    """View for activating a user account."""
    try:
        # Split the token into uid and token parts
        uid, token = token.split('-', 1)
        
        # Decode the user ID
        user_id = force_str(urlsafe_base64_decode(uid))
        user = RaingullUser.objects.get(pk=user_id)
        
        if default_token_generator.check_token(user, token):
            user.is_active = True
            user.save()
            messages.success(request, "Your account has been activated. You can now log in.")
            return redirect('login')
        else:
            messages.error(request, "Invalid activation link.")
            return redirect('login')
    except (TypeError, ValueError, OverflowError, RaingullUser.DoesNotExist):
        messages.error(request, "Invalid activation link.")
        return redirect('login')
