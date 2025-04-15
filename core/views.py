# core/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from core.models import ServiceInstance, Plugin
from core.forms import DynamicServiceInstanceForm
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.module_loading import import_string
import json

@login_required
@user_passes_test(lambda u: u.is_superuser)
def service_instance_list(request):
    instances = ServiceInstance.objects.select_related('plugin').all()
    return render(request, 'core/service_instance_list.html', {'instances': instances})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_service_instance(request, instance_id=None):
    instance = get_object_or_404(ServiceInstance, pk=instance_id) if instance_id else None
    plugin_name = request.GET.get('plugin') if not instance else instance.plugin.name
    template_name = f'{plugin_name}/manage_service_instance.html'

    form = DynamicServiceInstanceForm(request.POST or None, instance=instance)

    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Service instance saved successfully.')
        return redirect('core:service_instance_list')

    return render(request, template_name, {
        'form': form,
        'instance': instance,
    })

@login_required
@user_passes_test(lambda u: u.is_superuser)
@csrf_exempt
def test_plugin_connection(request, plugin_name):
    plugin = get_object_or_404(Plugin, name=plugin_name, enabled=True)

    try:
        plugin_test_function = import_string(f'plugins.{plugin.name}.views.test_connection')
    except ImportError:
        return JsonResponse({'success': False, 'message': 'Plugin test connection function not found.'})

    if request.method == 'POST':
        data = json.loads(request.body)
        return plugin_test_function(request, data)
    
    return JsonResponse({'success': False, 'message': 'Invalid request method.'})
