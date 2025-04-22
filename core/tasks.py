from celery import shared_task
from django.utils import timezone
from .models import Service, Message, AuditLog, MessageQueue, UserService, MessageDistribution
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.conf import settings
from core.utils import get_imap_connection, get_smtp_connection
from core.plugin_models import PluginModelLoader
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
import uuid
from django.db.models import Q
from django.db import models

logger = logging.getLogger(__name__)
redis_client = Redis(host='localhost', port=6379, db=0)

def get_plugin_model(model_name):
    """Get a plugin model by name using the PluginModelLoader"""
    return PluginModelLoader.get_model(model_name)

def log_audit(event_type, details, service_instance=None):
    """Helper function to create audit log entries"""
    try:
        AuditLog.objects.create(
            event_type=event_type,
            details=details,
            status='success'  # Default status
        )
    except Exception as e:
        logger.error(f"Error creating audit log entry: {str(e)}")

@shared_task
def poll_incoming_services():
    """Poll all active incoming services for new messages."""
    try:
        # Get all active service instances with incoming enabled
        incoming_services = Service.objects.filter(
            incoming_enabled=True
        )
        
        total_services = incoming_services.count()
        if total_services == 0:
            log_audit(
                'incoming_poll',
                "Step 1: No active incoming services configured",
                None
            )
            return None
            
        # Log start of polling cycle
        log_audit(
            'incoming_poll',
            f"Step 1: Starting polling cycle for {total_services} incoming service{'s' if total_services > 1 else ''}",
            None
        )
        
        for service in incoming_services:
            lock = None
            try:
                # Create a unique lock key for this service
                lock_key = f"poll_incoming:{service.id}"
                
                # Check for stale lock
                lock_exists = redis_client.exists(lock_key)
                if lock_exists:
                    lock_owner = redis_client.get(f"{lock_key}:owner")
                    if not lock_owner:
                        logger.warning(f"Step 1: Found stale lock for {service.name}, cleaning up")
                        try:
                            redis_client.delete(lock_key)
                            redis_client.delete(f"{lock_key}:owner")
                        except Exception as e:
                            logger.error(f"Step 1: Error cleaning up stale lock for {service.name}: {e}")
                            log_audit('error', f"Step 1: Error cleaning up stale lock for {service.name}: {e}", service)
                
                # Try to acquire a lock for this service
                lock = Lock(redis_client, lock_key, timeout=60, blocking_timeout=5)  # Reduced timeout to 60 seconds
                if not lock.acquire():
                    # Check if the lock is actually held by another process
                    lock_owner = redis_client.get(f"{lock_key}:owner")
                    if lock_owner:
                        logger.warning(f"Step 1: Lock for service {service.name} is held by process {lock_owner.decode()}")
                        log_audit('warning', f"Step 1: Lock for service {service.name} is held by process {lock_owner.decode()}", service)
                    else:
                        logger.warning(f"Step 1: Could not acquire lock for service {service.name}, but no owner found")
                        log_audit('warning', f"Step 1: Could not acquire lock for service {service.name}, but no owner found", service)
                    continue
                
                # Log start of polling
                log_audit(
                    'incoming_poll',
                    f"Step 1: Checking {service.name} for new messages",
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
                result = plugin.retrieve_messages(service)
                if result is None:
                    error_msg = f"Step 1: Error retrieving messages from {service.name}: Plugin returned None"
                    logger.error(error_msg)
                    log_audit('error', error_msg, service)
                    continue
                
                # Log polling results
                stored = result.get('stored', 0)
                processed = result.get('processed', 0)
                
                if stored == 0 and processed == 0:
                    log_audit(
                        'incoming_poll',
                        f"Step 1: No new messages found in {service.name}",
                        service
                    )
                else:
                    log_audit(
                        'incoming_poll',
                        f"Step 1: Found {stored} new message{'s' if stored != 1 else ''} in {service.name}",
                        service
                    )
                
            except Exception as e:
                error_msg = f"Step 1: Error polling service {service.name}: {str(e)}"
                logger.error(error_msg)
                log_audit('error', error_msg, service)
            finally:
                if lock and lock.locked():
                    try:
                        lock.release()
                    except Exception as e:
                        logger.error(f"Step 1: Error releasing lock for {service.name}: {e}")
                        log_audit('error', f"Step 1: Error releasing lock for {service.name}: {e}", service)
        
        return None
        
    except Exception as e:
        error_msg = f"Step 1: Error in poll_incoming_services task: {str(e)}"
        logger.error(error_msg)
        log_audit('error', error_msg)
        return None

@shared_task
def process_outgoing_messages(service_id):
    """
    Step 4: Queue outgoing messages for delivery.
    This task:
    1. Gets all queued messages from service-specific outgoing tables
    2. For each message:
       - Gets all active users for that service
       - Creates queue entries in core_message_queue
       - Updates service-specific message status
    3. Handles special cases (invitations)
    4. Skips queueing messages for the original sender
    """
    try:
        service = Service.objects.get(id=service_id)
        plugin = service.plugin
        
        # Get the outgoing model
        model_name = f"{plugin.name}OutgoingMessage_{service_id}"
        outgoing_model = get_plugin_model(model_name)
        if not outgoing_model:
            logger.error(f"Could not get outgoing model for service {service_id}")
            return
            
        # Get all queued messages
        queued_messages = outgoing_model.objects.filter(status='queued')
        total_messages = queued_messages.count()
        
        if total_messages == 0:
            log_audit(
                'outgoing_queue',
                f"Step 4: No queued messages to process for service {service.name}",
                service
            )
            return None
            
        # Log start of processing
        log_audit(
            'outgoing_queue',
            f"Step 4: Processing {total_messages} queued message{'s' if total_messages > 1 else ''} for service {service.name}",
            service
        )
        
        processed_count = 0
        for message in queued_messages:
            try:
                # Get all active users for this service
                active_users = UserService.objects.filter(
                    service=service,
                    is_active=True
                ).select_related('user')
                
                # Skip if no active users
                if not active_users.exists():
                    logger.warning(f"Step 4: No active users found for service {service.name}")
                    continue
                    
                # Create queue entries for each user
                for user_service in active_users:
                    # Skip the original sender
                    if message.sender == user_service.user.email:
                        continue
                        
                    # Create a queue entry
                    MessageQueue.objects.create(
                        message=message,
                        user=user_service.user,
                        service_instance=service,
                        status='queued',
                        scheduled_delivery_time=message.scheduled_delivery_time,
                        is_urgent=message.is_urgent
                    )
                    
                # Update message status
                message.status = 'queued'
                message.save()
                
                processed_count += 1
                
            except Exception as e:
                error_msg = f"Step 4: Error processing message {message.id} for service {service.name}: {str(e)}"
                logger.error(error_msg)
                log_audit('error', error_msg, service)
                continue
                
        # Log processing results
        log_audit(
            'outgoing_queue',
            f"Step 4: Processed {processed_count} of {total_messages} messages for service {service.name}",
            service
        )
        
        return processed_count
        
    except Service.DoesNotExist:
        error_msg = f"Step 4: Service {service_id} not found"
        logger.error(error_msg)
        log_audit('error', error_msg)
        return None
    except Exception as e:
        error_msg = f"Step 4: Error in process_outgoing_messages task: {str(e)}"
        logger.error(error_msg)
        log_audit('error', error_msg)
        return None

@shared_task
def send_queued_messages():
    """
    Step 5: Send queued messages through their respective services.
    This task:
    1. Gets all queued messages from core_message_queue
    2. For each message:
       - Gets the appropriate plugin instance
       - Sends the message through the service
       - Updates message status
    3. Handles retries with exponential backoff
    4. Tracks delivery status for each user
    5. Marks original messages as fully processed when all copies are sent
    
    Lock Key Format: send_message:{message.raingull_message.raingull_id}
    """
    try:
        # Get all queued and failed messages that haven't exceeded retry limit
        queued_messages = MessageQueue.objects.filter(
            Q(status='queued') | 
            Q(status='failed', retry_count__lt=settings.MAX_MESSAGE_RETRIES)
        ).select_related(
            'raingull_message',
            'user',
            'service_instance'
        ).order_by('created_at')  # Process oldest messages first
        
        message_count = queued_messages.count()
        if message_count == 0:
            log_audit(
                'outgoing_send',
                "Step 5: No messages to send in queue",
                None
            )
            return None
            
        # Log start of sending cycle
        log_audit(
            'outgoing_send',
            f"Step 5: Starting sending cycle for {message_count} message{'s' if message_count > 1 else ''}",
            None
        )
        
        total_sent = 0
        total_failed = 0
        total_retrying = 0
        
        # Group messages by service to optimize plugin initialization
        messages_by_service = {}
        for message in queued_messages:
            service_id = message.service_instance.id
            if service_id not in messages_by_service:
                messages_by_service[service_id] = []
            messages_by_service[service_id].append(message)
        
        for service_id, service_messages in messages_by_service.items():
            try:
                # Get plugin instance once per service
                plugin = service_messages[0].service_instance.get_plugin_instance()
                if not plugin:
                    error_msg = f"Step 5: Could not get plugin instance for {service_messages[0].service_instance.name}"
                    logger.error(error_msg)
                    log_audit('error', error_msg, service_messages[0].service_instance)
                    continue
                
                for message in service_messages:
                    try:
                        # Check if this is a retry and if we need to wait
                        if message.status == 'failed':
                            # Calculate next retry time with exponential backoff
                            retry_delay = min(
                                settings.MAX_RETRY_DELAY,
                                settings.MIN_RETRY_DELAY * (2 ** message.retry_count)
                            )
                            next_retry = message.last_retry_at + timedelta(minutes=retry_delay)
                            if timezone.now() < next_retry:
                                retry_info = (
                                    f"Step 5: Message {message.raingull_message.raingull_id} not ready for retry yet "
                                    f"(attempt {message.retry_count + 1}/{settings.MAX_MESSAGE_RETRIES}, "
                                    f"next attempt at {next_retry}, "
                                    f"user: {message.user.username}, "
                                    f"service: {message.service_instance.name})"
                                )
                                logger.info(retry_info)
                                log_audit(
                                    'outgoing_send',
                                    retry_info,
                                    message.service_instance
                                )
                                total_retrying += 1
                                continue
                        
                        # Create a unique lock key for this message
                        lock_key = f"send_message:{message.raingull_message.raingull_id}"
                        
                        # Check for stale lock
                        lock_exists = redis_client.exists(lock_key)
                        if lock_exists:
                            lock_owner = redis_client.get(f"{lock_key}:owner")
                            if not lock_owner:
                                logger.warning(f"Step 5: Found stale lock for message {message.raingull_message.raingull_id}, cleaning up")
                                try:
                                    redis_client.delete(lock_key)
                                    redis_client.delete(f"{lock_key}:owner")
                                except Exception as e:
                                    logger.error(f"Step 5: Error cleaning up stale lock for message {message.raingull_message.raingull_id}: {e}")
                                    log_audit('error', f"Step 5: Error cleaning up stale lock for message {message.raingull_message.raingull_id}: {e}")
                        
                        # Try to acquire a lock for this message
                        lock = Lock(redis_client, lock_key, timeout=settings.MESSAGE_LOCK_TIMEOUT, blocking_timeout=settings.MESSAGE_LOCK_BLOCKING_TIMEOUT)
                        if not lock.acquire():
                            # Check if the lock is actually held by another process
                            lock_owner = redis_client.get(f"{lock_key}:owner")
                            if lock_owner:
                                logger.warning(f"Step 5: Lock for message {message.raingull_message.raingull_id} is held by process {lock_owner.decode()}")
                                log_audit('warning', f"Step 5: Lock for message {message.raingull_message.raingull_id} is held by process {lock_owner.decode()}")
                            else:
                                logger.warning(f"Step 5: Could not acquire lock for message {message.raingull_message.raingull_id}, but no owner found")
                                log_audit('warning', f"Step 5: Could not acquire lock for message {message.raingull_message.raingull_id}, but no owner found")
                            continue
                        
                        try:
                            # Check if this is an invitation message
                            is_invitation = message.raingull_message.headers and message.raingull_message.headers.get('is_invitation') == 'true'
                            
                            # Get the user's service activation
                            try:
                                user_activation = UserService.objects.get(
                                    user=message.user,
                                    service_instance=message.service_instance,
                                    is_active=True
                                )
                            except UserService.DoesNotExist:
                                # If this is an invitation message, we can proceed without an active activation
                                if is_invitation:
                                    # Try to get the existing activation (even if disabled)
                                    try:
                                        user_activation = UserService.objects.get(
                                            user=message.user,
                                            service_instance=message.service_instance
                                        )
                                        # Temporarily enable it and update the config if needed
                                        user_activation.is_active = True
                                        if not user_activation.config.get('email_address'):
                                            user_activation.config['email_address'] = message.raingull_message.headers.get('recipient_email')
                                        user_activation.save()
                                    except UserService.DoesNotExist:
                                        # Create a new activation if none exists
                                        user_activation = UserService.objects.create(
                                            user=message.user,
                                            service_instance=message.service_instance,
                                            is_active=True,
                                            config={'email_address': message.raingull_message.headers.get('recipient_email')}
                                        )
                                else:
                                    error_msg = f"Step 5: User {message.user.username} is not activated for service {message.service_instance.name}"
                                    logger.error(error_msg)
                                    message.status = 'failed'
                                    message.error_message = error_msg
                                    message.retry_count += 1
                                    message.last_retry_at = timezone.now()
                                    message.save()
                                    total_failed += 1
                                    log_audit('error', error_msg, message.service_instance)
                                    continue
                            
                            # Get the recipient email from the user's service activation
                            recipient_email = user_activation.config.get('email_address')
                            if not recipient_email:
                                error_msg = f"Step 5: No email address configured for user {message.user.username} in service {message.service_instance.name}"
                                logger.error(error_msg)
                                message.status = 'failed'
                                message.error_message = error_msg
                                message.retry_count += 1
                                message.last_retry_at = timezone.now()
                                message.save()
                                total_failed += 1
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
                                success_msg = (
                                    f"Step 5: Successfully sent message {message.raingull_message.raingull_id} "
                                    f"to {recipient_email} via {message.service_instance.name} "
                                    f"for user {message.user.username}"
                                )
                                logger.info(success_msg)
                                log_audit(
                                    'outgoing_send',
                                    success_msg,
                                    message.service_instance
                                )
                                total_sent += 1
                                
                                # If this was a temporary activation for an invitation, disable it again
                                if is_invitation:
                                    user_activation.is_active = False
                                    user_activation.save()
                                    
                                # Check if all copies of this message have been sent
                                unsent_copies = MessageQueue.objects.filter(
                                    raingull_message=message.raingull_message,
                                    status__in=['queued', 'failed']
                                ).count()
                                
                                if unsent_copies == 0:
                                    # All copies sent, mark the original message as fully processed
                                    message.raingull_message.status = 'processed'
                                    message.raingull_message.processed_at = timezone.now()
                                    message.raingull_message.save()
                                    log_audit(
                                        'outgoing_send',
                                        f"Step 5: All copies of message {message.raingull_message.raingull_id} have been sent",
                                        None
                                    )
                            else:
                                error_msg = "Step 5: Failed to send message"
                                logger.error(error_msg)
                                message.status = 'failed'
                                message.error_message = error_msg
                                message.retry_count += 1
                                message.last_retry_at = timezone.now()
                                message.save()
                                total_failed += 1
                                log_audit('error', error_msg, message.service_instance)
                                
                                # If this was a temporary activation for an invitation, disable it again
                                if is_invitation:
                                    user_activation.is_active = False
                                    user_activation.save()
                            
                        finally:
                            if lock.locked():
                                try:
                                    lock.release()
                                except Exception as e:
                                    logger.error(f"Step 5: Error releasing lock for message {message.raingull_message.raingull_id}: {e}")
                                    log_audit('error', f"Step 5: Error releasing lock for message {message.raingull_message.raingull_id}: {e}")
                        
                    except Exception as e:
                        error_msg = f"Step 5: Error processing message: {str(e)}"
                        logger.error(error_msg)
                        message.status = 'failed'
                        message.error_message = str(e)
                        message.retry_count += 1
                        message.last_retry_at = timezone.now()
                        message.save()
                        total_failed += 1
                        log_audit('error', error_msg, message.service_instance)
                        continue
                        
            except Exception as e:
                error_msg = f"Step 5: Error processing messages for service {service_id}: {str(e)}"
                logger.error(error_msg)
                log_audit('error', error_msg)
                continue
                
        # Log final sending summary
        summary_msg = (
            f"Step 5: Sending complete - "
            f"Sent: {total_sent}, "
            f"Failed: {total_failed}, "
            f"Retrying: {total_retrying}, "
            f"Total: {message_count}"
        )
        logger.info(summary_msg)
        log_audit(
            'outgoing_send',
            summary_msg,
            None
        )
        
    except Exception as e:
        error_msg = f"Step 5: Error in send_queued_messages task: {str(e)}"
        logger.error(error_msg)
        log_audit('error', error_msg)
        return None

@shared_task
def process_incoming_messages(service_id):
    """
    Step 2: Process incoming messages from service-specific tables.
    This task:
    1. Gets all new messages from the service's incoming table
    2. Creates Message objects for each
    3. Updates service-specific message status
    """
    try:
        service = Service.objects.get(id=service_id)
        plugin = service.plugin
        
        # Get the incoming model
        model_name = f"{plugin.name}IncomingMessage_{service_id}"
        incoming_model = get_plugin_model(model_name)
        if not incoming_model:
            logger.error(f"Could not get incoming model for service {service_id}")
            return
            
        # Get all new messages
        new_messages = incoming_model.objects.filter(status='new')
        total_messages = new_messages.count()
        
        if total_messages == 0:
            log_audit(
                'incoming_process',
                f"Step 2: No new messages to process for service {service.name}",
                service
            )
            return None
            
        # Log start of processing
        log_audit(
            'incoming_process',
            f"Step 2: Processing {total_messages} new message{'s' if total_messages > 1 else ''} for service {service.name}",
            service
        )
        
        processed_count = 0
        for message in new_messages:
            try:
                # Create a Message object
                message_obj = Message.objects.create(
                    service=service,
                    direction='in',
                    status='received',
                    content=message.content,
                    metadata=message.metadata,
                    received_at=message.received_at
                )
                
                # Update service-specific message status
                message.status = 'processed'
                message.save()
                
                processed_count += 1
                
            except Exception as e:
                error_msg = f"Step 2: Error processing message {message.id} for service {service.name}: {str(e)}"
                logger.error(error_msg)
                log_audit('error', error_msg, service)
                continue
                
        # Log processing results
        log_audit(
            'incoming_process',
            f"Step 2: Processed {processed_count} of {total_messages} messages for service {service.name}",
            service
        )
        
        return processed_count
        
    except Service.DoesNotExist:
        error_msg = f"Step 2: Service {service_id} not found"
        logger.error(error_msg)
        log_audit('error', error_msg)
        return None
    except Exception as e:
        error_msg = f"Step 2: Error in process_incoming_messages task: {str(e)}"
        logger.error(error_msg)
        log_audit('error', error_msg)
        return None

@shared_task
def distribute_outgoing_messages():
    """
    Step 3: Distribute messages from the core to service-specific outgoing tables.
    This task:
    1. Finds new messages that haven't been distributed yet
    2. For each active outgoing service:
       - Translates the message to the service format
       - Creates an entry in the service's outgoing table
    3. Creates MessageDistribution records to track the distribution
    """
    try:
        # Get all service instances with outgoing enabled
        service_instances = Service.objects.filter(
            outgoing_enabled=True
        )
        
        total_services = service_instances.count()
        if total_services == 0:
            log_audit(
                'outgoing_process',
                "Step 3: No active outgoing services configured",
                None
            )
            return None
            
        # Log start of processing cycle
        log_audit(
            'outgoing_process',
            f"Step 3: Starting distribution cycle for {total_services} outgoing service{'s' if total_services > 1 else ''}",
            None
        )
        
        # Get new messages that haven't been distributed yet
        # These are messages that:
        # 1. Have no MessageDistribution records (new from Step 2)
        # 2. Have at least one pending distribution (retry failed distributions)
        new_messages = Message.objects.filter(
            Q(messagedistribution__isnull=True) |  # New messages from Step 2
            Q(messagedistribution__status='failed')  # Failed distributions to retry
        ).distinct().select_related('source_service')
        
        message_count = new_messages.count()
        if message_count == 0:
            log_audit(
                'outgoing_process',
                "Step 3: No new messages to distribute",
                None
            )
            return None
            
        log_audit(
            'outgoing_process',
            f"Step 3: Found {message_count} new message{'s' if message_count > 1 else ''} to distribute",
            None
        )
        
        total_distributed = 0
        for message in new_messages:
            try:
                # Create a unique lock key for this message
                lock_key = f"distribute_message:{message.raingull_id}"
                
                # Check for stale lock
                lock_exists = redis_client.exists(lock_key)
                if lock_exists:
                    lock_owner = redis_client.get(f"{lock_key}:owner")
                    if not lock_owner:
                        logger.warning(f"Step 3: Found stale lock for message {message.raingull_id}, cleaning up")
                        try:
                            redis_client.delete(lock_key)
                            redis_client.delete(f"{lock_key}:owner")
                        except Exception as e:
                            logger.error(f"Step 3: Error cleaning up stale lock for message {message.raingull_id}: {e}")
                            log_audit('error', f"Step 3: Error cleaning up stale lock for message {message.raingull_id}: {e}")
                
                # Try to acquire a lock for this message
                lock = Lock(redis_client, lock_key, timeout=60, blocking_timeout=5)
                if not lock.acquire():
                    # Check if the lock is actually held by another process
                    lock_owner = redis_client.get(f"{lock_key}:owner")
                    if lock_owner:
                        logger.warning(f"Step 3: Lock for message {message.raingull_id} is held by process {lock_owner.decode()}")
                        log_audit('warning', f"Step 3: Lock for message {message.raingull_id} is held by process {lock_owner.decode()}")
                    else:
                        logger.warning(f"Step 3: Could not acquire lock for message {message.raingull_id}, but no owner found")
                        log_audit('warning', f"Step 3: Could not acquire lock for message {message.raingull_id}, but no owner found")
                    continue
                
                try:
                    # Process for each service
                    for service_instance in service_instances:
                        try:
                            # Skip if this service already has a successful distribution
                            if MessageDistribution.objects.filter(
                                message=message,
                                service_instance=service_instance,
                                status='formatted'
                            ).exists():
                                continue
                            
                            # Get the plugin instance
                            plugin = service_instance.get_plugin_instance()
                            if not plugin:
                                error_msg = f"Step 3: Could not get plugin instance for {service_instance.name}"
                                logger.error(error_msg)
                                log_audit('error', error_msg, service_instance)
                                continue
                            
                            # Get the outgoing message model
                            outgoing_model = service_instance.get_message_model('outgoing')
                            if not outgoing_model:
                                error_msg = f"Step 3: Could not get outgoing message model for {service_instance.name}"
                                logger.error(error_msg)
                                log_audit('error', error_msg, service_instance)
                                continue
                            
                            # Translate the message to the service format
                            try:
                                translated_message = plugin.translate_from_raingull(message)
                            except Exception as e:
                                error_msg = f"Step 3: Error translating message for {service_instance.name}: {str(e)}"
                                logger.error(error_msg)
                                log_audit('error', error_msg, service_instance)
                                continue
                            
                            # Create the outgoing message
                            try:
                                outgoing_message = outgoing_model.objects.create(
                                    raingull_id=message.raingull_id,
                                    to=translated_message['to'],
                                    subject=translated_message['subject'],
                                    body=translated_message['body'],
                                    headers=translated_message['headers'],
                                    status='queued',
                                    created_at=timezone.now()
                                )
                            except Exception as e:
                                error_msg = f"Step 3: Error creating outgoing message for {service_instance.name}: {str(e)}"
                                logger.error(error_msg)
                                log_audit('error', error_msg, service_instance)
                                continue
                            
                            # Create or update distribution record
                            try:
                                distribution, created = MessageDistribution.objects.get_or_create(
                                    message=message,
                                    service_instance=service_instance,
                                    defaults={'status': 'formatted'}
                                )
                                if not created:
                                    distribution.status = 'formatted'
                                    distribution.error_message = None
                                    distribution.save()
                            except Exception as e:
                                error_msg = f"Step 3: Error creating distribution record for {service_instance.name}: {str(e)}"
                                logger.error(error_msg)
                                log_audit('error', error_msg, service_instance)
                                continue
                            
                            total_distributed += 1
                            logger.info(f"Step 3: Successfully distributed message {message.raingull_id} to {service_instance.name}")
                            
                        except Exception as e:
                            error_msg = f"Step 3: Error processing message for {service_instance.name}: {str(e)}"
                            logger.error(error_msg)
                            log_audit('error', error_msg, service_instance)
                            continue
                            
                finally:
                    if lock.locked():
                        try:
                            lock.release()
                        except Exception as e:
                            logger.error(f"Step 3: Error releasing lock for message {message.raingull_id}: {e}")
                            log_audit('error', f"Step 3: Error releasing lock for message {message.raingull_id}: {e}")
                    
            except Exception as e:
                error_msg = f"Step 3: Error processing message: {str(e)}"
                logger.error(error_msg)
                log_audit('error', error_msg)
                continue
                
        if total_distributed > 0:
            log_audit(
                'outgoing_process',
                f"Step 3: Successfully distributed {total_distributed} message{'s' if total_distributed > 1 else ''} across all services",
                None
            )
        else:
            log_audit(
                'outgoing_process',
                "Step 3: No messages were distributed across all services",
                None
            )
        
    except Exception as e:
        error_msg = f"Step 3: Error in distribute_outgoing_messages task: {str(e)}"
        logger.error(error_msg)
        log_audit('error', error_msg)
        return None

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

@shared_task
def format_outgoing_messages():
    """
    Step 3: Format messages for each outgoing service.
    This task:
    1. Gets all unprocessed messages from core_messages
    2. For each active outgoing service:
       - Creates a distribution record if one doesn't exist
       - Translates the message using the service's manifest
       - Stores the formatted message in the service's outgoing table
    3. Marks the original message as processed when all services have their copies
    """
    try:
        # Get all active outgoing services
        outgoing_services = Service.objects.filter(
            outgoing_enabled=True
        )
        
        service_count = outgoing_services.count()
        if service_count == 0:
            log_audit(
                'outgoing_format',
                "Step 3: No active outgoing services configured",
                None
            )
            return None
            
        log_audit(
            'outgoing_format',
            f"Step 3: Starting formatting cycle for {service_count} outgoing service(s)",
            None
        )
        
        # Get unprocessed messages
        unprocessed_messages = Message.objects.filter(
            processed=False
        )
        
        message_count = unprocessed_messages.count()
        if message_count == 0:
            log_audit(
                'outgoing_format',
                "Step 3: No new messages to format",
                None
            )
            return None
            
        log_audit(
            'outgoing_format',
            f"Step 3: Processing {message_count} message{'s' if message_count > 1 else ''} for formatting",
            None
        )
        
        total_formatted = 0
        for message in unprocessed_messages:
            # Create distribution records for all active services if they don't exist
            for service in outgoing_services:
                MessageDistribution.objects.get_or_create(
                    message=message,
                    service=service,
                    defaults={'status': 'pending'}
                )
            
            # Get all pending distributions for this message
            distributions = MessageDistribution.objects.filter(
                message=message,
                status='pending'
            ).select_related('service')
            
            for distribution in distributions:
                service = distribution.service
                try:
                    # Get the plugin instance
                    plugin = service.get_plugin_instance()
                    if not plugin:
                        error_msg = f"Step 3: Could not get plugin instance for {service.name}"
                        logger.error(error_msg)
                        log_audit('error', error_msg, service)
                        distribution.status = 'failed'
                        distribution.error_message = "Could not get plugin instance"
                        distribution.save()
                        continue
                    
                    # Get the outgoing message model
                    outgoing_model = service.get_message_model('outgoing')
                    if not outgoing_model:
                        error_msg = f"Step 3: Could not get outgoing message model for {service.name}"
                        logger.error(error_msg)
                        log_audit('error', error_msg, service)
                        distribution.status = 'failed'
                        distribution.error_message = "Could not get outgoing message model"
                        distribution.save()
                        continue
                    
                    # Create a unique lock key for this message and service
                    lock_key = f"format_message:{service.id}:{message.raingull_id}"
                    
                    # Try to acquire a lock for this message and service
                    lock = Lock(redis_client, lock_key, timeout=60, blocking_timeout=5)
                    try:
                        if lock.acquire():
                            # Check if message was already formatted for this service
                            if outgoing_model.objects.filter(raingull_id=message.raingull_id).exists():
                                distribution.status = 'formatted'
                                distribution.save()
                                continue
                            
                            # Format the message according to the service's schema
                            formatted_message = outgoing_model(
                                raingull_id=message.raingull_id,
                                message_id=str(uuid.uuid4()),  # Generate a new message ID for this service
                                to=message.recipients.get('to', ''),
                                subject=message.subject,
                                body=message.body,
                                headers=message.headers,
                                status='formatted'
                            )
                            formatted_message.save()
                            
                            distribution.status = 'formatted'
                            distribution.save()
                            
                            total_formatted += 1
                            log_audit(
                                'outgoing_format',
                                f"Step 3: Successfully formatted message for {service.name}",
                                service
                            )
                        else:
                            logger.warning(f"Step 3: Could not acquire lock for message {message.raingull_id} in {service.name}, skipping")
                            continue
                            
                    except Exception as e:
                        error_msg = f"Step 3: Error formatting message for {service.name}: {str(e)}"
                        logger.error(error_msg)
                        log_audit('error', error_msg, service)
                        distribution.status = 'failed'
                        distribution.error_message = str(e)
                        distribution.save()
                        continue
                    finally:
                        if lock.locked():
                            lock.release()
                            
                except Exception as e:
                    error_msg = f"Step 3: Error processing distribution for {service.name}: {str(e)}"
                    logger.error(error_msg)
                    log_audit('error', error_msg, service)
                    continue
        
        if total_formatted > 0:
            log_audit(
                'outgoing_format',
                f"Step 3: Successfully formatted {total_formatted} message{'s' if total_formatted > 1 else ''} across all services",
                None
            )
        else:
            log_audit(
                'outgoing_format',
                "Step 3: No messages required formatting",
                None
            )
        
        return None
        
    except Exception as e:
        error_msg = f"Step 3: Error in format_outgoing_messages task: {str(e)}"
        logger.error(error_msg)
        log_audit('error', error_msg)
        return None

@shared_task
def distribute_messages():
    """
    Step 4: Distribute formatted messages to their respective services.
    """
    logger.info("Starting message distribution")
    
    # Get all active outgoing services
    services = Service.objects.filter(
        is_active=True,
        direction='outgoing'
    ).select_related('plugin')
    
    # Get all formatted messages
    messages = Message.objects.filter(
        status='formatted',
        service__in=services
    ).select_related('service')
    
    total_messages = messages.count()
    logger.info(f"Found {total_messages} messages to distribute")
    
    for message in messages:
        try:
            # Get plugin instance
            plugin = message.service.plugin.get_plugin_instance()
            if not plugin:
                logger.error(f"Could not get plugin instance for service {message.service.id}")
                continue
                
            # Try to acquire lock
            lock_id = f"distribute_message_{message.id}"
            if not acquire_lock(lock_id):
                logger.warning(f"Could not acquire lock for message {message.id}")
                continue
                
            try:
                # Send message
                plugin.send_message(message)
                logger.info(f"Successfully distributed message {message.id}")
                
            finally:
                release_lock(lock_id)
                
        except Exception as e:
            logger.error(f"Error distributing message {message.id}: {e}")
            message.status = 'failed'
            message.error_message = str(e)
            message.save()
            
    logger.info(f"Completed distribution of {total_messages} messages")
    return f"Distributed {total_messages} messages"

class UserDeliveryWindow(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    start_time = models.TimeField()
    end_time = models.TimeField()
    days_of_week = models.CharField(max_length=7)  # e.g., "MTWTFSS"
    timezone = models.CharField(max_length=50)
    is_global = models.BooleanField(default=True)

class ServiceDeliveryWindow(models.Model):
    user_service = models.ForeignKey(UserService, on_delete=models.CASCADE)
    start_time = models.TimeField()
    end_time = models.TimeField()
    days_of_week = models.CharField(max_length=7)
    timezone = models.CharField(max_length=50)
    override_global = models.BooleanField(default=False) 