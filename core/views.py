# core/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from core.models import ServiceInstance, Plugin
from core.forms import DynamicServiceInstanceForm, ServiceInstanceForm
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.module_loading import import_string
import json
import os

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
