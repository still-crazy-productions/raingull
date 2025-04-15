# core/urls.py
from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('services/', views.service_instance_list, name='service_instance_list'),
    path('services/get_plugin_fields/', views.get_plugin_fields, name='get_plugin_fields'),
    path('services/create/', views.create_service_instance, name='create_service_instance'),
    path('services/manage/<int:instance_id>/', views.manage_service_instance, name='manage_service_instance'),
    path('services/test/<str:plugin_name>/', views.test_plugin_connection, name='test_plugin_connection'),
]
