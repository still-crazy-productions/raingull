from django.shortcuts import render, get_object_or_404
from .models import ServerInfo

def about(request):
    server_info = get_object_or_404(ServerInfo, pk=1)  # assumes only one record
    return render(request, 'core/about.html', {'server_info': server_info})