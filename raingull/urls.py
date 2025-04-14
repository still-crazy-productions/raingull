from django.contrib import admin
from django.urls import path, include  # <-- Add include import here!

urlpatterns = [
    path('admin/', admin.site.urls),
    path('core/', include('core.urls')),  # <-- Move inside urlpatterns
]
