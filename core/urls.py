from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('services/', views.service_instance_list, name='service_instance_list'),
    path('services/manage/', views.manage_service_instance, name='service_instance_add'),
    path('services/manage/<int:instance_id>/', views.manage_service_instance, name='service_instance_edit'),
]
