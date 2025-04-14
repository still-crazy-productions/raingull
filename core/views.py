from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from core.models import ServiceInstance, Plugin
from core.forms import DynamicServiceInstanceForm

@login_required
@user_passes_test(lambda u: u.is_superuser)
def manage_service_instance(request, instance_id=None):
    instance = get_object_or_404(ServiceInstance, pk=instance_id) if instance_id else None
    form = DynamicServiceInstanceForm(request.POST or None, instance=instance)

    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Service instance saved successfully.')
        return redirect('core:service_instance_list')

    return render(request, 'core/manage_service_instance.html', {
        'form': form,
        'instance': instance,
    })

@login_required
@user_passes_test(lambda u: u.is_superuser)
def service_instance_list(request):
    instances = ServiceInstance.objects.select_related('plugin').all()
    return render(request, 'core/service_instance_list.html', {'instances': instances})
