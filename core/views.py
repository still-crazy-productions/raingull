import json
import imaplib
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from core.models import ServiceInstance
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

@login_required
@user_passes_test(lambda u: u.is_superuser)
def test_imap_connection(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)

            required_fields = ['imap_server', 'imap_port', 'username', 'password', 'encryption']
            missing_fields = [f for f in required_fields if not data.get(f)]
            if missing_fields:
                return JsonResponse({
                    "success": False,
                    "message": f"Missing fields: {', '.join(missing_fields)}"
                })

            server = data['imap_server']
            try:
                port = int(data['imap_port'])
            except ValueError:
                return JsonResponse({
                    "success": False,
                    "message": "Invalid port number."
                })

            user = data['username']
            password = data['password']
            encryption = data['encryption']

            if encryption == "SSL/TLS":
                mail = imaplib.IMAP4_SSL(server, port)
            else:
                mail = imaplib.IMAP4(server, port)
                if encryption == "STARTTLS":
                    mail.starttls()

            mail.login(user, password)
            mail.logout()

            return JsonResponse({"success": True, "message": "Connection successful."})

        except imaplib.IMAP4.error as e:
            return JsonResponse({"success": False, "message": f"IMAP error: {e}"})
        except Exception as e:
            return JsonResponse({"success": False, "message": str(e)})

    return JsonResponse({"success": False, "message": "Invalid request method."})
