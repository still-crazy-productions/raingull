from celery import shared_task
from django.utils import timezone
from .models import ServiceInstance, RaingullStandardMessage, AuditLog, OutgoingMessageQueue, Message, UserServiceActivation
from django.core.mail import send_mail
from django.conf import settings
from core.utils import get_imap_connection, get_smtp_connection
import logging
import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time
from datetime import datetime, timedelta
import pytz
import json
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)

def log_audit(event_type, details, service_instance=None):
    """Helper function to create audit log entries"""
    AuditLog.objects.create(
        event_type=event_type,
        service_instance=service_instance,
        details=details
    )

@shared_task
def poll_imap_services():
    """Poll all active IMAP services for new messages."""
    try:
        # Get all active IMAP service instances
        imap_services = ServiceInstance.objects.filter(
            plugin__name='imap_plugin',
            incoming_enabled=True
        )
        
        for service in imap_services:
            try:
                # Log start of polling
                log_audit(
                    'imap_poll',
                    f"Step 1: Starting IMAP poll for {service.name}",
                    service
                )
                
                # Get the plugin instance
                plugin = service.get_plugin_instance()
                if not plugin:
                    error_msg = f"Step 1: Could not get plugin instance for {service.name}"
                    logger.error(error_msg)
                    log_audit('error', error_msg, service)
                    continue
                
                # Poll for new messages
                result = plugin.retrieve_messages()
                if not result.get('success'):
                    error_msg = f"Step 1: Error retrieving messages: {result.get('message')}"
                    logger.error(error_msg)
                    log_audit('error', error_msg, service)
                    continue
                
                # Log polling results
                log_audit(
                    'imap_poll',
                    f"Step 1: {result.get('message', 'Messages retrieved successfully')}",
                    service
                )
                
            except Exception as e:
                error_msg = f"Step 1: Error polling IMAP service {service.name}: {e}"
                logger.error(error_msg)
                log_audit('error', error_msg, service)
                continue
                
    except Exception as e:
        error_msg = f"Step 1: Error in poll_imap_services task: {e}"
        logger.error(error_msg)
        log_audit('error', error_msg)

@shared_task
def process_outgoing_messages():
    """Process outgoing messages from the queue."""
    try:
        # Get all queued messages
        queued_messages = OutgoingMessageQueue.objects.filter(
            status='queued'
        ).select_related(
            'raingull_message',
            'user',
            'service_instance'
        )
        
        message_count = queued_messages.count()
        log_audit(
            'outgoing_send',
            f"Step 5: Starting processing of {message_count} outgoing messages"
        )
        
        for message in queued_messages:
            try:
                # Get the plugin instance
                plugin = message.service_instance.get_plugin_instance()
                if not plugin:
                    error_msg = f"Step 5: Could not get plugin instance for {message.service_instance.name}"
                    logger.error(error_msg)
                    log_audit('error', error_msg, message.service_instance)
                    continue
                
                # Get the user's service activation
                try:
                    user_activation = UserServiceActivation.objects.get(
                        user=message.user,
                        service_instance=message.service_instance,
                        is_active=True
                    )
                except UserServiceActivation.DoesNotExist:
                    error_msg = f"Step 5: User {message.user.username} is not activated for service {message.service_instance.name}"
                    logger.error(error_msg)
                    message.status = 'failed'
                    message.error_message = error_msg
                    message.save()
                    log_audit('error', error_msg, message.service_instance)
                    continue
                
                # Get the service-specific message
                outgoing_model = message.service_instance.get_message_model('outgoing')
                service_message = outgoing_model.objects.get(
                    raingull_id=message.raingull_message.raingull_id
                )
                
                # Prepare message data for sending
                message_data = {
                    'to': service_message.to,
                    'subject': service_message.subject,
                    'body': service_message.body,
                    'headers': service_message.headers if hasattr(service_message, 'headers') else {}
                }
                
                # Send the message
                success = plugin.send_message(message.service_instance, message_data)
                
                # Update message status based on success
                if success:
                    message.status = 'sent'
                    message.processed_at = timezone.now()
                    message.save()
                    
                    # Log successful send
                    log_audit(
                        'outgoing_send',
                        f"Step 5: Successfully sent message to {message.user.username}",
                        message.service_instance
                    )
                else:
                    error_msg = "Step 5: Failed to send message"
                    logger.error(error_msg)
                    message.status = 'failed'
                    message.error_message = error_msg
                    message.save()
                    log_audit('error', error_msg, message.service_instance)
                
            except Exception as e:
                error_msg = f"Step 5: Error sending message: {e}"
                logger.error(error_msg)
                message.status = 'failed'
                message.error_message = str(e)
                message.save()
                log_audit('error', error_msg, message.service_instance)
                continue
                
    except Exception as e:
        error_msg = f"Step 5: Error in process_outgoing_messages task: {e}"
        logger.error(error_msg)
        log_audit('error', error_msg)

@shared_task
def process_incoming_messages():
    """
    Process and translate incoming messages from all service instances.
    This task:
    1. Checks all incoming service instance tables for new messages
    2. Translates them based on the plugin manifest
    3. Stores them in the standard Message table
    """
    try:
        # Get all service instances with incoming enabled
        service_instances = ServiceInstance.objects.filter(
            incoming_enabled=True
        )
        
        total_processed = 0
        for instance in service_instances:
            try:
                # Get the plugin instance
                plugin = instance.get_plugin_instance()
                if not plugin:
                    logger.error(f"Step 2: Could not get plugin instance for {instance.name}")
                    log_audit('error', f"Step 2: Could not get plugin instance for {instance.name}", instance)
                    continue
                
                # Get the plugin's manifest
                manifest = instance.plugin.get_manifest()
                if not manifest:
                    logger.error(f"Step 2: Could not get manifest for {instance.name}")
                    log_audit('error', f"Step 2: Could not get manifest for {instance.name}", instance)
                    continue
                
                # Get new messages from the service instance's model
                message_model = instance.get_message_model('incoming')
                if not message_model:
                    logger.error(f"Step 2: Could not get message model for {instance.name}")
                    log_audit('error', f"Step 2: Could not get message model for {instance.name}", instance)
                    continue
                
                # Get new messages - no need to filter by service_instance since the table is already specific to this instance
                new_messages = message_model.objects.filter(
                    status='new'
                )
                
                messages_processed = 0
                for message in new_messages:
                    try:
                        # Create a new Raingull standard message
                        RaingullStandardMessage.create_standard_message(
                            raingull_id=message.raingull_id,
                            source_service=instance,
                            source_message_id=message.imap_message_id,
                            subject=message.subject,
                            body=message.body,
                            sender=message.email_from,
                            recipients=message.to,
                            date=parsedate_to_datetime(message.date),
                            headers=message.headers if hasattr(message, 'headers') else {}
                        )
                        
                        # Mark the original message as processed
                        message.status = 'processed'
                        message.processed_at = timezone.now()
                        message.save()
                        
                        messages_processed += 1
                        total_processed += 1
                        
                    except Exception as e:
                        error_msg = f"Step 2: Error processing message from {instance.name}: {str(e)}"
                        logger.error(error_msg)
                        log_audit('error', error_msg, instance)
                        continue
                
                if messages_processed > 0:
                    log_audit('message_processed', f"Step 2: Processed {messages_processed} messages from {instance.name}", instance)
                
            except Exception as e:
                error_msg = f"Step 2: Error processing messages from {instance.name}: {str(e)}"
                logger.error(error_msg)
                log_audit('error', error_msg, instance)
                continue
        
        if total_processed > 0:
            log_audit('message_processed', f"Step 2: Processed {total_processed} incoming messages across all services")
        
        logger.info(f"Step 2: Processed {total_processed} incoming messages")
        return f"Successfully processed {total_processed} messages"
        
    except Exception as e:
        error_msg = f"Step 2: Error in process_incoming_messages task: {str(e)}"
        logger.error(error_msg)
        log_audit('error', error_msg)
        raise

@shared_task
def distribute_outgoing_messages():
    """
    Distribute outgoing messages to appropriate service instances.
    This task:
    1. Checks RaingullStandardMessage table for new messages
    2. For each active outgoing service instance:
       - Translates the message based on the plugin's manifest
       - Creates a new message in the service instance's table
       - Creates an entry in the OutgoingMessageQueue
    """
    try:
        # Get all new standard messages that haven't been distributed yet
        new_messages = RaingullStandardMessage.objects.filter(
            outgoingmessagequeue__isnull=True  # Messages not yet in the queue
        )
        
        message_count = new_messages.count()
        logger.info(f"Step 3: Found {message_count} new messages to distribute")
        
        # Get all active outgoing service instances
        outgoing_services = ServiceInstance.objects.filter(
            outgoing_enabled=True
        )
        
        for message in new_messages:
            for service in outgoing_services:
                try:
                    # Get the plugin instance
                    plugin = service.get_plugin_instance()
                    if not plugin:
                        logger.error(f"Step 3: Could not get plugin instance for {service.name}")
                        log_audit('error', f"Step 3: Could not get plugin instance for {service.name}", service)
                        continue
                    
                    # Get the plugin's manifest
                    manifest = service.plugin.get_manifest()
                    if not manifest:
                        logger.error(f"Step 3: Could not get manifest for {service.name}")
                        log_audit('error', f"Step 3: Could not get manifest for {service.name}", service)
                        continue
                    
                    # Get the outgoing message model
                    message_model = service.get_message_model('outgoing')
                    if not message_model:
                        logger.error(f"Step 3: Could not get message model for {service.name}")
                        log_audit('error', f"Step 3: Could not get message model for {service.name}", service)
                        continue
                    
                    # Get translation rules from manifest
                    translation_rules = manifest.get('translation_rules', {}).get('from_raingull', {})
                    if not translation_rules:
                        logger.error(f"Step 3: No translation rules found for {service.name}")
                        log_audit('error', f"Step 3: No translation rules found for {service.name}", service)
                        continue
                    
                    # Create translated message data
                    translated_data = {}
                    for target_field, source_field in translation_rules.items():
                        # Handle nested fields (e.g., "recipients[0]")
                        if '[' in source_field:
                            field_name, index = source_field.split('[')
                            index = int(index.rstrip(']'))
                            value = getattr(message, field_name)[index]
                        else:
                            value = getattr(message, source_field)
                        translated_data[target_field] = value
                    
                    # Add required fields
                    translated_data['raingull_id'] = message.raingull_id
                    translated_data['status'] = 'queued'
                    
                    # Create the service-specific message
                    service_message = message_model.objects.create(**translated_data)
                    
                    # Get active users for this service
                    active_users = UserServiceActivation.objects.filter(
                        service_instance=service,
                        is_active=True
                    ).select_related('user')

                    # Create queue entries for each active user
                    for activation in active_users:
                        OutgoingMessageQueue.objects.create(
                            raingull_message=message,
                            service_instance=service,
                            user=activation.user,
                            status='queued',
                            created_at=timezone.now()
                        )
                    
                    logger.info(f"Step 3: Created outgoing message for {service.name}")
                    log_audit(
                        'outgoing_distribute',
                        f"Step 3: Created outgoing message for {service.name}",
                        service
                    )
                    
                except Exception as e:
                    error_msg = f"Step 3: Error distributing message to {service.name}: {e}"
                    logger.error(error_msg)
                    log_audit('error', error_msg, service)
                    continue
                    
    except Exception as e:
        error_msg = f"Step 3: Error in distribute_outgoing_messages task: {e}"
        logger.error(error_msg)
        log_audit('error', error_msg) 