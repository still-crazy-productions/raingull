# core/urls.py
from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('services/', views.service_instance_list, name='service_instance_list'),
    path('services/get_plugin_fields/', views.get_plugin_fields, name='get_plugin_fields'),
    path('services/create/', views.create_service_instance, name='create_service_instance'),
    path('services/manage/<int:instance_id>/', views.manage_service_instance, name='manage_service_instance'),
    path('services/delete/<int:instance_id>/', views.delete_service_instance, name='delete_service_instance'),
    path('services/test/<str:plugin_name>/', views.test_plugin_connection, name='test_plugin_connection'),
    path('test/', views.test_services, name='test_services'),
    path('test/imap/retrieve/<int:instance_id>/', views.test_imap_retrieve, name='test_imap_retrieve'),
    path('test/translate/<int:instance_id>/', views.test_translate_messages, name='test_translate_messages'),
]
