# core/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from core.models import ServiceInstance, Plugin, RaingullStandardMessage, UserServiceActivation, RaingullUser, OutgoingMessageQueue, AuditLog
from core.forms import DynamicServiceInstanceForm, ServiceInstanceForm
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

logger = logging.getLogger(__name__)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def service_instance_list(request):
    instances = ServiceInstance.objects.select_related('plugin').all()
    plugins = Plugin.objects.filter(enabled=True)
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
        # Import the plugin's manifest
        manifest = import_string(f'plugins.{plugin.name}.manifest')
        fields = manifest.get('config_fields', [])
        
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
    except ImportError:
        return JsonResponse({'error': 'Plugin manifest not found'}, status=404)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def create_service_instance(request):
    if request.method == 'POST':
        plugin_name = request.POST.get('plugin')
        if not plugin_name:
            return JsonResponse({'error': 'Plugin name is required'}, status=400)
        
        plugin = get_object_or_404(Plugin, name=plugin_name, enabled=True)
        
        # Create a new service instance
        instance = ServiceInstance(plugin=plugin, name=request.POST.get('name'))
        
        # Get the config fields from the manifest
        try:
            manifest_path = os.path.join('plugins', plugin.name, 'manifest.json')
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
            config_fields = manifest.get('config_fields', [])
            
            # Build the config dictionary
            config = {}
            for field in config_fields:
                field_name = field['name']
                config[field_name] = request.POST.get(f'config_{field_name}')
            
            instance.config = config
            instance.save()
            
            messages.success(request, 'Service instance created successfully.')
            return redirect('core:service_instance_list')
        except (FileNotFoundError, json.JSONDecodeError) as e:
            messages.error(request, f'Error loading plugin manifest: {str(e)}')
            return redirect('core:service_instance_list')
    
    # GET request - show the form
    plugin_name = request.GET.get('plugin')
    if not plugin_name:
        return redirect('core:service_instance_list')
    
    plugin = get_object_or_404(Plugin, name=plugin_name, enabled=True)
    
    try:
        manifest_path = os.path.join('plugins', plugin.name, 'manifest.json')
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
        fields = manifest.get('config_fields', [])
        
        # Check if the plugin has a test connection function
        views_path = os.path.join('plugins', plugin.name, 'views.py')
        has_test_connection = os.path.exists(views_path) and 'test_connection' in open(views_path).read()
    except (FileNotFoundError, json.JSONDecodeError) as e:
        messages.error(request, f'Error loading plugin manifest: {str(e)}')
        return redirect('core:service_instance_list')
    
    return render(request, 'core/create_service_instance.html', {
        'plugin': plugin,
        'fields': fields,
        'has_test_connection': has_test_connection
    })

@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_service_instance(request, instance_id=None):
    instance = get_object_or_404(ServiceInstance, pk=instance_id) if instance_id else None
    
    # Get the plugin manifest to check capabilities
    manifest = instance.plugin.get_manifest() if instance else None
    
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
    
    # Create the form with the instance data
    form = DynamicServiceInstanceForm(request.POST or None, instance=instance)
    
    # If plugin doesn't support outgoing, remove the outgoing_enabled field
    if manifest and not manifest.get('outgoing', False):
        form.fields.pop('outgoing_enabled', None)
    
    if request.method == 'POST':
        print("Form data:", request.POST)
        if form.is_valid():
            print("Form is valid")
            print("Cleaned data:", form.cleaned_data)
            instance = form.save()
            print("Instance saved")
            print("New config:", instance.config)
            messages.success(request, 'Service instance saved successfully.')
            return redirect('core:service_instance_list')
        else:
            print("Form errors:", form.errors)
            messages.error(request, 'Please correct the errors below.')
    
    return render(request, 'core/manage_service_instance.html', {
        'form': form,
        'instance': instance,
        'manifest': manifest,
        'has_test_connection': has_test_connection,
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
        data = json.loads(request.body)
        print("Parsed data:", data)
        
        # Call the plugin's test_connection function
        print("Calling test_connection function")
        response = test_connection(request, data)
        print("Test connection response:", response)
        return response
    except (ImportError, AttributeError) as e:
        print(f"Error loading test connection function: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Error loading test connection function: {str(e)}'})
    except json.JSONDecodeError as e:
        print(f"Invalid JSON data: {str(e)}")
        return JsonResponse({'success': False, 'message': 'Invalid JSON data'})
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return JsonResponse({'success': False, 'message': str(e)})

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
            source_service__plugin__name='imap_plugin'  # Specifically by IMAP
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
                'message': 'Service instance does not have outgoing enabled'
            })

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

        # Get the outgoing message model
        outgoing_model = service_instance.get_message_model('outgoing')
        if not outgoing_model:
            return JsonResponse({
                'success': False,
                'message': 'Could not get outgoing message model'
            })

        # Get all queued messages that haven't been processed
        messages = outgoing_model.objects.filter(status='queued')
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
                        service_message_id=str(message.id),
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
def send_queued_messages(request, instance_id):
    """Send queued messages through their service instances."""
    try:
        service_instance = ServiceInstance.objects.get(id=instance_id)
        if not service_instance.outgoing_enabled:
            return JsonResponse({
                'success': False,
                'message': 'Service instance does not have outgoing enabled'
            })

        # Get the plugin instance
        plugin_instance = service_instance.get_plugin_instance()
        if not plugin_instance:
            return JsonResponse({
                'success': False,
                'message': 'Could not create plugin instance'
            })

        # Get all queued messages for this service instance
        queued_messages = OutgoingMessageQueue.objects.filter(
            service_instance=service_instance,
            status='queued'
        ).select_related('raingull_message', 'user')

        if not queued_messages.exists():
            return JsonResponse({
                'success': True,
                'message': 'No queued messages found'
            })

        sent_count = 0
        for queue_entry in queued_messages:
            try:
                # Update status to processing
                queue_entry.status = 'processing'
                queue_entry.save()

                # Get the service-specific message
                outgoing_model = service_instance.get_message_model('outgoing')
                service_message = outgoing_model.objects.get(
                    raingull_id=queue_entry.raingull_message.raingull_id
                )

                # Prepare message data for sending
                message_data = {
                    'to': service_message.to,
                    'subject': service_message.subject,
                    'body': service_message.body,
                    'headers': service_message.headers
                }

                # Send the message
                result = plugin_instance.send_message(service_instance, message_data)
                
                if result:
                    # Update queue entry status
                    queue_entry.status = 'sent'
                    queue_entry.processed_at = timezone.now()
                    queue_entry.save()
                    sent_count += 1
                else:
                    # Update queue entry with error
                    queue_entry.status = 'failed'
                    queue_entry.error_message = 'Failed to send message'
                    queue_entry.save()
                    logger.error(f"Failed to send message {queue_entry.id}")

            except Exception as e:
                logger.error(f"Error processing queue entry {queue_entry.id}: {e}")
                queue_entry.status = 'failed'
                queue_entry.error_message = str(e)
                queue_entry.save()
                continue

        return JsonResponse({
            'success': True,
            'message': f'Successfully sent {sent_count} messages'
        })

    except ServiceInstance.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Service instance not found'
        })
    except Exception as e:
        logger.error(f"Error in send_queued_messages: {e}")
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
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
