from celery import shared_task
from django.utils import timezone
from .models import ServiceInstance, RaingullStandardMessage, AuditLog, OutgoingMessageQueue, UserServiceActivation
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
from redis import Redis
from redis.lock import Lock

logger = logging.getLogger(__name__)
redis_client = Redis(host='localhost', port=6379, db=0)

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
            plugin__name='imap',
            incoming_enabled=True
        )
        
        for service in imap_services:
            try:
                # Create a unique lock key for this service
                lock_key = f"poll_imap:{service.id}"
                
                # Try to acquire a lock for this service
                lock = Lock(redis_client, lock_key, timeout=60, blocking_timeout=1)
                if lock.acquire():
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
                    finally:
                        lock.release()
                else:
                    logger.warning(f"Could not acquire lock for IMAP service {service.name}, skipping")
                    continue
                
            except Exception as e:
                error_msg = f"Step 1: Error processing IMAP service {service.name}: {str(e)}"
                logger.error(error_msg)
                log_audit('error', error_msg, service)
                continue
                
    except Exception as e:
        error_msg = f"Step 1: Error in poll_imap_services task: {str(e)}"
        logger.error(error_msg)
        log_audit('error', error_msg)
        raise

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
            f"Step 4: Starting processing of {message_count} outgoing messages"
        )
        
        for message in queued_messages:
            try:
                # Create a unique lock key for this message
                lock_key = f"send_message:{message.raingull_id}"
                
                # Try to acquire a lock for this message
                lock = Lock(redis_client, lock_key, timeout=60, blocking_timeout=1)
                if not lock.acquire():
                    logger.warning(f"Could not acquire lock for message {message.raingull_id}, skipping")
                    continue
                
                try:
                    # Get the plugin instance
                    plugin = message.service_instance.get_plugin_instance()
                    if not plugin:
                        error_msg = f"Step 4: Could not get plugin instance for {message.service_instance.name}"
                        logger.error(error_msg)
                        log_audit('error', error_msg, message.service_instance)
                        continue
                    
                    # Check if this is an invitation message
                    is_invitation = message.raingull_message.headers and message.raingull_message.headers.get('is_invitation') == 'true'
                    
                    # Get the user's service activation
                    try:
                        user_activation = UserServiceActivation.objects.get(
                            user=message.user,
                            service_instance=message.service_instance,
                            is_active=True
                        )
                    except UserServiceActivation.DoesNotExist:
                        # If this is an invitation message, we can proceed without an active activation
                        if is_invitation:
                            # Try to get the existing activation (even if disabled)
                            try:
                                user_activation = UserServiceActivation.objects.get(
                                    user=message.user,
                                    service_instance=message.service_instance
                                )
                                # Temporarily enable it and update the config if needed
                                user_activation.is_active = True
                                if not user_activation.config.get('email_address'):
                                    user_activation.config['email_address'] = message.raingull_message.headers.get('recipient_email')
                                user_activation.save()
                            except UserServiceActivation.DoesNotExist:
                                # Create a new activation if none exists
                                user_activation = UserServiceActivation.objects.create(
                                    user=message.user,
                                    service_instance=message.service_instance,
                                    is_active=True,
                                    config={'email_address': message.raingull_message.headers.get('recipient_email')}
                                )
                        else:
                            error_msg = f"Step 4: User {message.user.username} is not activated for service {message.service_instance.name}"
                            logger.error(error_msg)
                            message.status = 'failed'
                            message.error_message = error_msg
                            message.save()
                            log_audit('error', error_msg, message.service_instance)
                            continue
                    
                    # Get the recipient email from the user's service activation
                    recipient_email = user_activation.config.get('email_address')
                    if not recipient_email:
                        error_msg = f"Step 4: No email address configured for user {message.user.username} in service {message.service_instance.name}"
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
                        'to': recipient_email,  # Use the email from user's service activation
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
                        logger.info(f"Step 4: Successfully sent message to {recipient_email} via {message.service_instance.name}")
                        log_audit(
                            'outgoing_send',
                            f"Step 4: Successfully sent message to {recipient_email} via {message.service_instance.name}",
                            message.service_instance
                        )
                        
                        # If this was a temporary activation for an invitation, disable it again
                        if is_invitation:
                            user_activation.is_active = False
                            user_activation.save()
                    else:
                        error_msg = "Step 4: Failed to send message"
                        logger.error(error_msg)
                        message.status = 'failed'
                        message.error_message = error_msg
                        message.save()
                        log_audit('error', error_msg, message.service_instance)
                        
                        # If this was a temporary activation for an invitation, disable it again
                        if is_invitation:
                            user_activation.is_active = False
                            user_activation.save()
                    
                finally:
                    lock.release()
                    
            except Exception as e:
                error_msg = f"Step 4: Error processing message: {e}"
                logger.error(error_msg)
                message.status = 'failed'
                message.error_message = str(e)
                message.save()
                log_audit('error', error_msg, message.service_instance)
                continue
                
    except Exception as e:
        error_msg = f"Step 4: Error in process_outgoing_messages task: {e}"
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
                    # Create a unique lock key for this message
                    lock_key = f"process_message:{instance.id}:{message.raingull_id}"
                    
                    # Try to acquire a lock for this message
                    lock = Lock(redis_client, lock_key, timeout=60, blocking_timeout=1)
                    try:
                        if lock.acquire():
                            # Check if message was already processed
                            if RaingullStandardMessage.objects.filter(raingull_id=message.raingull_id).exists():
                                # Mark the original message as processed
                                message.status = 'processed'
                                message.processed_at = timezone.now()
                                message.save()
                                continue
                            
                            # Create a new Raingull standard message
                            standard_message = RaingullStandardMessage.create_standard_message(
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
                        else:
                            logger.warning(f"Could not acquire lock for message {message.raingull_id}, skipping")
                            continue
                            
                    except Exception as e:
                        error_msg = f"Step 2: Error processing message from {instance.name}: {str(e)}"
                        logger.error(error_msg)
                        log_audit('error', error_msg, instance)
                        continue
                    finally:
                        if lock.locked():
                            lock.release()
                
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
    """Distribute outgoing messages to active users."""
    try:
        # Get all active users with active service activations
        active_users = UserServiceActivation.objects.filter(
            is_active=True,
            user__is_active=True  # Only distribute to active users
        ).select_related('user', 'service_instance')
        
        # Group by service instance
        service_groups = {}
        for activation in active_users:
            if activation.service_instance not in service_groups:
                service_groups[activation.service_instance] = []
            service_groups[activation.service_instance].append(activation)
        
        # Process each service instance
        for service_instance, activations in service_groups.items():
            try:
                # Get unprocessed messages for this service
                messages = RaingullStandardMessage.objects.filter(
                    source_service=service_instance,
                    processed=False
                )
                
                for message in messages:
                    # Skip invitation messages
                    if message.headers and message.headers.get('is_invitation') == 'true':
                        continue
                        
                    # Queue message for each active user
                    for activation in activations:
                        OutgoingMessageQueue.objects.create(
                            raingull_message=message,
                            user=activation.user,
                            service_instance=service_instance,
                            raingull_id=message.raingull_id,
                            status='queued'
                        )
                    
                    # Mark message as processed
                    message.processed = True
                    message.save()
                    
            except Exception as e:
                logger.error(f"Error processing messages for service {service_instance.name}: {e}")
                continue
                
    except Exception as e:
        logger.error(f"Error in distribute_outgoing_messages: {e}")
        log_audit('error', f"Error in distribute_outgoing_messages: {e}")

@shared_task
def process_service_messages():
    """Process service-specific messages (invitations, password resets, etc.)"""
    try:
        # This task is no longer needed as we're using ServiceMessageTemplate and OutgoingMessageQueue
        # for all message handling now
        pass
                
    except Exception as e:
        logger.error(f"Error in process_service_messages: {e}")
        log_audit('error', f"Error in process_service_messages: {e}") 