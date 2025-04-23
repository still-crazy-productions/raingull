from celery import shared_task
from django.utils import timezone
from .models import Service, Message, AuditLog, MessageQueue, UserService
from django.contrib.auth.models import User
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
import uuid
from django.db.models import Q
from django.db import models

logger = logging.getLogger(__name__)
redis_client = Redis(host='localhost', port=6379, db=0)

def get_plugin_model(model_name):
    """Get a plugin model by name"""
    # Since we're using a unified Message model, we can just return Message
    return Message

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
    """Step 1: Poll all active incoming services for new messages."""
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
                # Use service-specific timeout if configured, otherwise default to 300 seconds
                lock_timeout = service.config.get('poll_timeout', 300)
                lock = Lock(redis_client, lock_key, timeout=lock_timeout, blocking_timeout=5)
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
                try:
                    messages = plugin.fetch_messages()
                    if not messages:
                        log_audit(
                            'incoming_poll',
                            f"Step 1: No new messages found in {service.name}",
                            service
                        )
                        continue
                        
                    # Store messages in core_messages
                    stored_count = 0
                    duplicate_count = 0
                    error_count = 0
                    
                    for msg_data in messages:
                        try:
                            # Check for duplicate message - either already ingested or being standardized
                            if Message.objects.filter(
                                Q(service=service, service_message_id=msg_data['service_message_id']) |
                                Q(source_service=service, service_message_id=msg_data['service_message_id'])
                            ).exists():
                                logger.info(f"Step 1: Skipping duplicate message {msg_data['service_message_id']} from {service.name}")
                                duplicate_count += 1
                                continue
                            
                            # Create message in core_messages
                            message = Message.objects.create(
                                service=service,
                                direction='incoming',
                                status='new',
                                processing_step='ingested',
                                step_processing_time={
                                    'ingested': {
                                        'start': timezone.now().isoformat(),
                                        'end': None
                                    }
                                },
                                service_message_id=msg_data['service_message_id'],
                                subject=msg_data['subject'],
                                sender=msg_data['sender'],
                                recipient=msg_data['recipient'],
                                timestamp=msg_data['timestamp'],
                                payload=msg_data['payload'],
                                created_at=timezone.now()
                            )
                            stored_count += 1
                            
                            # Only mark as read/deleted in IMAP after successful storage
                            if hasattr(plugin, 'mark_message_processed'):
                                plugin.mark_message_processed(msg_data['service_message_id'])
                            
                        except Exception as e:
                            error_msg = f"Step 1: Error storing message {msg_data.get('service_message_id', 'unknown')} from {service.name}: {str(e)}"
                            logger.error(error_msg)
                            log_audit('error', error_msg, service)
                            error_count += 1
                            continue
                    
                    # Log polling results
                    result_msg = (
                        f"Step 1: Polling {service.name} complete - "
                        f"Stored: {stored_count}, "
                        f"Duplicates: {duplicate_count}, "
                        f"Errors: {error_count}"
                    )
                    log_audit('incoming_poll', result_msg, service)
                    logger.info(result_msg)
                        
                except Exception as e:
                    error_msg = f"Step 1: Error retrieving messages from {service.name}: {str(e)}"
                    logger.error(error_msg)
                    log_audit('error', error_msg, service)
                    continue
                
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
    1. Gets all formatted messages from Step 3
    2. For each message:
       - Gets all active users for that service
       - Creates queue entries in core_message_queue
       - Updates message status to 'queued'
    3. Handles special cases (urgent messages)
    4. Respects delivery windows
    5. Implements retry logic for failed queue entries
    """
    # Check if message delivery is enabled
    if not getattr(settings, 'ENABLE_MESSAGE_DELIVERY', False):
        logger.info("Step 4: Message delivery is disabled, skipping queue processing")
        return None

    try:
        service = Service.objects.get(id=service_id)
        
        # Get batch size from service config or use default
        batch_size = service.config.get('process_batch_size', 100)
        
        # Get formatted messages from Step 3
        formatted_messages = Message.objects.filter(
            service=service,
            direction='outgoing',
            status='formatted',
            processing_step='formatted'
        )[:batch_size]  # Limit batch size
        
        total_messages = formatted_messages.count()
        if total_messages == 0:
            log_audit(
                'outgoing_queue',
                f"Step 4: No formatted messages to queue for service {service.name}",
                service
            )
            return None
            
        # Log start of processing
        log_audit(
            'outgoing_queue',
            f"Step 4: Processing {total_messages} formatted message{'s' if total_messages > 1 else ''} for service {service.name}",
            service
        )
        
        processed_count = 0
        error_count = 0
        duplicate_count = 0
        retry_count = 0
        
        for message in formatted_messages:
            lock = None
            try:
                # Check for duplicate queue entries
                if MessageQueue.objects.filter(
                    message=message,
                    status='queued'
                ).exists():
                    logger.info(f"Step 4: Message {message.id} already has queue entries")
                    duplicate_count += 1
                    continue
                
                # Create a unique lock key for this message
                lock_key = f"queue_message:{message.id}"
                
                # Use standardized lock timeout from settings
                lock_timeout = settings.LOCK_TIMEOUTS['queue']
                
                # Check for stale lock
                lock_exists = redis_client.exists(lock_key)
                if lock_exists:
                    lock_owner = redis_client.get(f"{lock_key}:owner")
                    if not lock_owner:
                        logger.warning(f"Step 4: Found stale lock for message {message.id}, cleaning up")
                        try:
                            redis_client.delete(lock_key)
                            redis_client.delete(f"{lock_key}:owner")
                        except Exception as e:
                            logger.error(f"Step 4: Error cleaning up stale lock for message {message.id}: {e}")
                            log_audit('error', f"Step 4: Error cleaning up stale lock for message {message.id}: {e}", service)
                
                # Try to acquire a lock for this message
                lock = Lock(redis_client, lock_key, timeout=lock_timeout, blocking_timeout=5)
                if not lock.acquire():
                    # Check if the lock is actually held by another process
                    lock_owner = redis_client.get(f"{lock_key}:owner")
                    if lock_owner:
                        logger.warning(f"Step 4: Lock for message {message.id} is held by process {lock_owner.decode()}")
                        log_audit('warning', f"Step 4: Lock for message {message.id} is held by process {lock_owner.decode()}", service)
                    else:
                        logger.warning(f"Step 4: Could not acquire lock for message {message.id}, but no owner found")
                        log_audit('warning', f"Step 4: Could not acquire lock for message {message.id}, but no owner found", service)
                    continue
                
                try:
                    # Update processing time for Step 3
                    processing_time = message.step_processing_time or {}
                    if 'formatted' in processing_time and not processing_time['formatted'].get('end'):
                        processing_time['formatted']['end'] = timezone.now().isoformat()
                    
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
                        try:
                            # Skip the original sender
                            if message.sender == user_service.user.email:
                                continue
                            
                            # Check delivery window
                            if not is_delivery_allowed(user_service.user, service):
                                continue
                            
                            # Check for existing failed queue entries that can be retried
                            existing_queue = MessageQueue.objects.filter(
                                message=message,
                                user=user_service.user,
                                status='failed',
                                retry_count__lt=settings.MAX_MESSAGE_RETRIES
                            ).first()
                            
                            if existing_queue:
                                # Check if enough time has passed since last retry
                                retry_delay = min(
                                    settings.MAX_RETRY_DELAY,
                                    settings.MIN_RETRY_DELAY * (2 ** existing_queue.retry_count)
                                )
                                next_retry = existing_queue.last_retry_at + timedelta(minutes=retry_delay)
                                
                                if timezone.now() < next_retry:
                                    retry_info = (
                                        f"Step 4: Queue entry for message {message.id} not ready for retry yet "
                                        f"(attempt {existing_queue.retry_count + 1}/{settings.MAX_MESSAGE_RETRIES}, "
                                        f"next attempt at {next_retry}, "
                                        f"user: {user_service.user.username})"
                                    )
                                    logger.info(retry_info)
                                    log_audit('outgoing_queue', retry_info, service)
                                    retry_count += 1
                                    continue
                                
                                # Reset the queue entry for retry
                                existing_queue.status = 'queued'
                                existing_queue.increment_retry()
                                existing_queue.save()
                                logger.info(f"Step 4: Reset queue entry {existing_queue.id} for retry")
                            else:
                                # Create new queue entry
                                MessageQueue.objects.create(
                                    message=message,
                                    user=user_service.user,
                                    service=service,
                                    status='queued',
                                    priority=1 if message.is_urgent else 0,
                                    created_at=timezone.now()
                                )
                            
                        except Exception as e:
                            error_msg = f"Step 4: Error creating queue entry for user {user_service.user.username}: {str(e)}"
                            logger.error(error_msg)
                            log_audit('error', error_msg, service)
                            error_count += 1
                            continue
                    
                    # Update message status
                    message.status = 'queued'
                    message.processing_step = 'queued'
                    message.save()
                    
                    processed_count += 1
                    logger.info(f"Step 4: Successfully queued message {message.id} for service {service.name}")
                    
                except Exception as e:
                    error_msg = f"Step 4: Error processing message {message.id}: {str(e)}"
                    logger.error(error_msg)
                    log_audit('error', error_msg, service)
                    error_count += 1
                    
                finally:
                    if lock and lock.locked():
                        try:
                            lock.release()
                        except Exception as e:
                            logger.error(f"Step 4: Error releasing lock for message {message.id}: {e}")
                            log_audit('error', f"Step 4: Error releasing lock for message {message.id}: {e}", service)
                
            except Exception as e:
                error_msg = f"Step 4: Error processing message {message.id}: {str(e)}"
                logger.error(error_msg)
                log_audit('error', error_msg, service)
                error_count += 1
                continue
        
        # Log processing results
        result_msg = (
            f"Step 4: Queue processing complete for {service.name} - "
            f"Processed: {processed_count}, "
            f"Errors: {error_count}, "
            f"Duplicates: {duplicate_count}, "
            f"Retries: {retry_count}, "
            f"Total: {total_messages}"
        )
        logger.info(result_msg)
        log_audit('outgoing_queue', result_msg, service)
        
        return {
            'processed': processed_count,
            'errors': error_count,
            'duplicates': duplicate_count,
            'retries': retry_count,
            'total': total_messages
        }
        
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

def is_delivery_allowed(user, service):
    """
    Check if delivery is allowed based on user and service delivery windows.
    Returns True if delivery is allowed, False otherwise.
    """
    # TODO: Implement delivery window functionality
    # For now, always allow delivery
    return True

@shared_task
def send_queued_messages(service_id):
    """
    Step 5: Send queued messages to their destinations.
    This task:
    1. Gets all queued messages for a service
    2. Sends each message to its recipients
    3. Updates message status and tracking
    4. Tracks delivery status for each user
    5. Marks original messages as fully processed when all copies are sent
    """
    # Check if message delivery is enabled
    if not getattr(settings, 'ENABLE_MESSAGE_DELIVERY', False):
        logger.info("Step 5: Message delivery is disabled, skipping message sending")
        return None

    try:
        service = Service.objects.get(id=service_id)
        
        # Get batch size from settings
        batch_size = settings.MESSAGE_BATCH_SIZE
        
        # Get all queued and failed messages that haven't exceeded retry limit
        queued_messages = MessageQueue.objects.filter(
            Q(status='queued') | 
            Q(status='failed', retry_count__lt=settings.MAX_MESSAGE_RETRIES)
        ).select_related(
            'message',
            'user',
            'service'
        ).order_by('created_at')[:batch_size]  # Limit batch size
        
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
            service_id = message.service.id
            if service_id not in messages_by_service:
                messages_by_service[service_id] = []
            messages_by_service[service_id].append(message)
        
        for service_id, service_messages in messages_by_service.items():
            try:
                # Get plugin instance once per service
                plugin = service_messages[0].service.get_plugin_instance()
                if not plugin:
                    error_msg = f"Step 5: Could not get plugin instance for {service_messages[0].service.name}"
                    logger.error(error_msg)
                    log_audit('error', error_msg, service_messages[0].service)
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
                                    f"Step 5: Message {message.message.id} not ready for retry yet "
                                    f"(attempt {message.retry_count + 1}/{settings.MAX_MESSAGE_RETRIES}, "
                                    f"next attempt at {next_retry}, "
                                    f"user: {message.user.username}, "
                                    f"service: {message.service.name})"
                                )
                                logger.info(retry_info)
                                log_audit(
                                    'outgoing_send',
                                    retry_info,
                                    message.service
                                )
                                total_retrying += 1
                                continue
                        
                        # Create a unique lock key for this message
                        lock_key = f"send_message:{message.message.id}"
                        
                        # Check for stale lock
                        lock_exists = redis_client.exists(lock_key)
                        if lock_exists:
                            lock_owner = redis_client.get(f"{lock_key}:owner")
                            if not lock_owner:
                                logger.warning(f"Step 5: Found stale lock for message {message.message.id}, cleaning up")
                                try:
                                    redis_client.delete(lock_key)
                                    redis_client.delete(f"{lock_key}:owner")
                                except Exception as e:
                                    logger.error(f"Step 5: Error cleaning up stale lock for message {message.message.id}: {e}")
                                    log_audit('error', f"Step 5: Error cleaning up stale lock for message {message.message.id}: {e}")
                        
                        # Try to acquire a lock for this message
                        lock = Lock(redis_client, lock_key, timeout=settings.LOCK_TIMEOUTS['send'], blocking_timeout=5)
                        if not lock.acquire():
                            # Check if the lock is actually held by another process
                            lock_owner = redis_client.get(f"{lock_key}:owner")
                            if lock_owner:
                                logger.warning(f"Step 5: Lock for message {message.message.id} is held by process {lock_owner.decode()}")
                                log_audit('warning', f"Step 5: Lock for message {message.message.id} is held by process {lock_owner.decode()}")
                            else:
                                logger.warning(f"Step 5: Could not acquire lock for message {message.message.id}, but no owner found")
                                log_audit('warning', f"Step 5: Could not acquire lock for message {message.message.id}, but no owner found")
                            continue
                        
                        try:
                            # Get the user's service activation
                            try:
                                user_activation = UserService.objects.get(
                                    user=message.user,
                                    service=message.service,
                                    is_active=True
                                )
                            except UserService.DoesNotExist:
                                error_msg = f"Step 5: User {message.user.username} is not activated for service {message.service.name}"
                                logger.error(error_msg)
                                message.status = 'failed'
                                message.error_message = error_msg
                                message.retry_count += 1
                                message.last_retry_at = timezone.now()
                                message.save()
                                total_failed += 1
                                log_audit('error', error_msg, message.service)
                                continue
                            
                            # Get the recipient email from the user's service activation
                            recipient_email = user_activation.config.get('email_address')
                            if not recipient_email:
                                error_msg = f"Step 5: No email address configured for user {message.user.username} in service {message.service.name}"
                                logger.error(error_msg)
                                message.status = 'failed'
                                message.error_message = error_msg
                                message.retry_count += 1
                                message.last_retry_at = timezone.now()
                                message.save()
                                total_failed += 1
                                log_audit('error', error_msg, message.service)
                                continue
                            
                            # Prepare message data for sending
                            message_data = {
                                'to': recipient_email,
                                'subject': message.message.subject,
                                'body': message.message.payload.get('content', ''),
                                'attachments': message.message.attachments
                            }
                            
                            # Send the message
                            success = plugin.send_message(message_data)
                            
                            # Update message status based on success
                            if success:
                                message.status = 'sent'
                                message.processed_at = timezone.now()
                                message.save()
                                
                                # Check if all copies of this message have been sent
                                unsent_copies = MessageQueue.objects.filter(
                                    message=message.message,
                                    status__in=['queued', 'failed']
                                ).count()
                                
                                if unsent_copies == 0:
                                    # All copies sent, mark the original message as fully processed
                                    message.message.status = 'sent'
                                    message.message.processing_step = 'sent'
                                    message.message.save()
                                    log_audit(
                                        'outgoing_send',
                                        f"Step 5: All copies of message {message.message.id} have been sent",
                                        None
                                    )
                                
                                total_sent += 1
                                logger.info(f"Step 5: Successfully sent message {message.message.id} to {recipient_email}")
                            else:
                                error_msg = "Step 5: Failed to send message"
                                logger.error(error_msg)
                                message.status = 'failed'
                                message.error_message = error_msg
                                message.retry_count += 1
                                message.last_retry_at = timezone.now()
                                message.save()
                                total_failed += 1
                                log_audit('error', error_msg, message.service)
                            
                        finally:
                            if lock and lock.locked():
                                try:
                                    lock.release()
                                except Exception as e:
                                    logger.error(f"Step 5: Error releasing lock for message {message.message.id}: {e}")
                                    log_audit('error', f"Step 5: Error releasing lock for message {message.message.id}: {e}")
                        
                    except Exception as e:
                        error_msg = f"Step 5: Error processing message {message.message.id}: {str(e)}"
                        logger.error(error_msg)
                        message.status = 'failed'
                        message.error_message = str(e)
                        message.retry_count += 1
                        message.last_retry_at = timezone.now()
                        message.save()
                        total_failed += 1
                        log_audit('error', error_msg, message.service)
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
        
        return {
            'sent': total_sent,
            'failed': total_failed,
            'retrying': total_retrying,
            'total': message_count
        }
        
    except Exception as e:
        error_msg = f"Step 5: Error in send_queued_messages task: {str(e)}"
        logger.error(error_msg)
        log_audit('error', error_msg)
        return None

@shared_task
def process_incoming_messages(service_id=None):
    """Step 2: Process incoming messages.
    
    Args:
        service_id: Optional service ID to process messages for. If None, processes for all services.
    """
    try:
        # Get services to process
        if service_id:
            services = Service.objects.filter(id=service_id, incoming_enabled=True)
        else:
            services = Service.objects.filter(incoming_enabled=True)
            
        total_services = services.count()
        if total_services == 0:
            log_audit(
                'incoming_process',
                "Step 2: No active incoming services configured",
                None
            )
            return None
            
        # Log start of processing cycle
        log_audit(
            'incoming_process',
            f"Step 2: Starting processing cycle for {total_services} incoming service{'s' if total_services > 1 else ''}",
            None
        )
        
        # Initialize counters
        total_processed = 0
        total_errors = 0
        total_duplicates = 0
        total_retries = 0
        
        for service in services:
            # Get batch size from service config or use default
            batch_size = service.config.get('process_batch_size', 100)
            
            # Get all new messages that need standardization
            messages = Message.objects.filter(
                service=service,
                direction='incoming',
                status='new',
                processing_step='ingested'
            ).select_related('service')[:batch_size]  # Limit batch size
            
            message_count = messages.count()
            if message_count == 0:
                log_audit(
                    'incoming_process',
                    f"Step 2: No new messages to process for service {service.name}",
                    service
                )
                continue
                
            # Log start of processing
            log_audit(
                'incoming_process',
                f"Step 2: Processing {message_count} new message{'s' if message_count > 1 else ''} for service {service.name}",
                service
            )
            
            # Initialize service-specific counters
            processed_count = 0
            error_count = 0
            duplicate_count = 0
            retry_count = 0
            
            for message in messages:
                lock = None
                try:
                    # Check for duplicate standardized message using source_service and service_message_id
                    if Message.objects.filter(
                        source_service=message.service,
                        service_message_id=message.service_message_id,
                        status='standardized'
                    ).exists():
                        logger.info(f"Step 2: Message {message.service_message_id} already has a standardized version")
                        duplicate_count += 1
                        continue
                    
                    # Handle retry logic for failed messages
                    if message.status == 'failed':
                        retry_count = message.retry_count or 0
                        if retry_count >= settings.MAX_RETRIES:
                            logger.warning(f"Step 2: Message {message.service_message_id} has exceeded max retries ({settings.MAX_RETRIES})")
                            continue
                        message.retry_count = retry_count + 1
                        message.status = 'new'
                        message.save()
                    
                    # Create a unique lock key for this message
                    lock_key = f"process_message:{message.id}"
                    
                    # Get lock timeout from service config or use default
                    lock_timeout = service.config.get('process_timeout', 60)
                    
                    # Check for stale lock
                    lock_exists = redis_client.exists(lock_key)
                    if lock_exists:
                        lock_owner = redis_client.get(f"{lock_key}:owner")
                        if not lock_owner:
                            logger.warning(f"Step 2: Found stale lock for message {message.service_message_id}, cleaning up")
                            try:
                                redis_client.delete(lock_key)
                                redis_client.delete(f"{lock_key}:owner")
                            except Exception as e:
                                logger.error(f"Step 2: Error cleaning up stale lock for message {message.service_message_id}: {e}")
                                log_audit('error', f"Step 2: Error cleaning up stale lock for message {message.service_message_id}: {e}", service)
                    
                    # Try to acquire a lock for this message
                    lock = Lock(redis_client, lock_key, timeout=lock_timeout, blocking_timeout=5)
                    if not lock.acquire():
                        # Check if the lock is actually held by another process
                        lock_owner = redis_client.get(f"{lock_key}:owner")
                        if lock_owner:
                            logger.warning(f"Step 2: Lock for message {message.service_message_id} is held by process {lock_owner.decode()}")
                            log_audit('warning', f"Step 2: Lock for message {message.service_message_id} is held by process {lock_owner.decode()}", service)
                        else:
                            logger.warning(f"Step 2: Could not acquire lock for message {message.service_message_id}, but no owner found")
                            log_audit('warning', f"Step 2: Could not acquire lock for message {message.service_message_id}, but no owner found", service)
                        continue
                    
                    try:
                        # Update processing time for Step 1
                        processing_time = message.step_processing_time or {}
                        if 'ingested' in processing_time and not processing_time['ingested'].get('end'):
                            processing_time['ingested']['end'] = timezone.now().isoformat()
                        
                        # Create standardized message
                        standardized_message = Message.objects.create(
                            service=service,
                            direction='incoming',
                            status='standardized',
                            processing_step='standardized',
                            step_processing_time={
                                'standardized': {
                                    'start': timezone.now().isoformat(),
                                    'end': None
                                }
                            },
                            source_service=message.service,
                            service_message_id=message.service_message_id,  # Preserve the IMAP UID
                            raingull_id=message.raingull_id,  # Copy the raingull_id from the original message
                            subject=message.subject,
                            sender=message.sender,
                            recipient=message.recipient,
                            timestamp=message.timestamp,
                            payload=message.payload,
                            created_at=timezone.now()
                        )
                        
                        # Mark original message as processed
                        message.status = 'processed'
                        message.processing_step = 'standardized'
                        message.processed_at = timezone.now()
                        message.save()
                        
                        processed_count += 1
                        logger.info(f"Step 2: Successfully processed standardized message {message.service_message_id} from {service.name}")
                        
                    except Exception as e:
                        error_msg = f"Step 2: Error processing standardized message {message.service_message_id} from {service.name}: {str(e)}"
                        logger.error(error_msg)
                        log_audit('error', error_msg, service)
                        error_count += 1
                        
                        # Mark original message as failed
                        message.status = 'failed'
                        message.error_message = str(e)
                        message.save()
                        
                    finally:
                        if lock and lock.locked():
                            try:
                                lock.release()
                            except Exception as e:
                                logger.error(f"Step 2: Error releasing lock for message {message.service_message_id}: {e}")
                                log_audit('error', f"Step 2: Error releasing lock for message {message.service_message_id}: {e}", service)
                    
                except Exception as e:
                    error_msg = f"Step 2: Error processing standardized message {message.service_message_id}: {str(e)}"
                    logger.error(error_msg)
                    log_audit('error', error_msg, service)
                    error_count += 1
                    continue
            
            # Update total counters
            total_processed += processed_count
            total_errors += error_count
            total_duplicates += duplicate_count
            total_retries += retry_count
            
            # Log processing results for this service
            result_msg = (
                f"Step 2: Processing complete for {service.name} - "
                f"Processed: {processed_count}, "
                f"Errors: {error_count}, "
                f"Duplicates: {duplicate_count}, "
                f"Retries: {retry_count}, "
                f"Total: {message_count}"
            )
            logger.info(result_msg)
            log_audit('incoming_process', result_msg, service)
        
        # Log final processing results
        final_result_msg = (
            f"Step 2: Processing complete for all services - "
            f"Processed: {total_processed}, "
            f"Errors: {total_errors}, "
            f"Duplicates: {total_duplicates}, "
            f"Retries: {total_retries}, "
            f"Total Services: {total_services}"
        )
        logger.info(final_result_msg)
        log_audit('incoming_process', final_result_msg, None)
        
        return {
            'processed': total_processed,
            'errors': total_errors,
            'duplicates': total_duplicates,
            'retries': total_retries,
            'total_services': total_services
        }
        
    except Exception as e:
        error_msg = f"Step 2: Error in process_incoming_messages task: {str(e)}"
        logger.error(error_msg)
        log_audit('error', error_msg)
        return None

@shared_task
def distribute_outgoing_messages():
    """Step 3: Distribute messages to outgoing services."""
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
        
        # Get new standardized messages that need distribution
        messages = Message.objects.filter(
            status='standardized',  # Changed from 'new' to 'standardized'
            direction='incoming',
            processing_step='standardized'
        ).select_related('service')
        
        message_count = messages.count()
        if message_count == 0:
            log_audit(
                'outgoing_process',
                "Step 3: No new standardized messages to distribute",
                None
            )
            return None
            
        log_audit(
            'outgoing_process',
            f"Step 3: Found {message_count} new standardized message{'s' if message_count > 1 else ''} to distribute",
            None
        )
        
        total_distributed = 0
        error_count = 0
        duplicate_count = 0
        
        for message in messages:
            lock = None
            try:
                # Create a unique lock key for this message
                lock_key = f"distribute_message:{message.id}"
                
                # Check for stale lock
                lock_exists = redis_client.exists(lock_key)
                if lock_exists:
                    lock_owner = redis_client.get(f"{lock_key}:owner")
                    if not lock_owner:
                        logger.warning(f"Step 3: Found stale lock for message {message.id}, cleaning up")
                        try:
                            redis_client.delete(lock_key)
                            redis_client.delete(f"{lock_key}:owner")
                        except Exception as e:
                            logger.error(f"Step 3: Error cleaning up stale lock for message {message.id}: {e}")
                            log_audit('error', f"Step 3: Error cleaning up stale lock for message {message.id}: {e}")
                
                # Try to acquire a lock for this message
                lock = Lock(redis_client, lock_key, timeout=60, blocking_timeout=5)
                if not lock.acquire():
                    # Check if the lock is actually held by another process
                    lock_owner = redis_client.get(f"{lock_key}:owner")
                    if lock_owner:
                        logger.warning(f"Step 3: Lock for message {message.id} is held by process {lock_owner.decode()}")
                        log_audit('warning', f"Step 3: Lock for message {message.id} is held by process {lock_owner.decode()}")
                    else:
                        logger.warning(f"Step 3: Could not acquire lock for message {message.id}, but no owner found")
                        log_audit('warning', f"Step 3: Could not acquire lock for message {message.id}, but no owner found")
                    continue
                
                try:
                    # Update processing time for Step 2
                    processing_time = message.step_processing_time or {}
                    if 'standardized' in processing_time and not processing_time['standardized'].get('end'):
                        processing_time['standardized']['end'] = timezone.now().isoformat()
                    
                    # Process for each service
                    for service_instance in service_instances:
                        try:
                            # Skip if this service already has a formatted copy
                            if Message.objects.filter(
                                source_service=message.service,
                                service=service_instance,
                                direction='outgoing',
                                status='formatted'
                            ).exists():
                                duplicate_count += 1
                                continue
                            
                            # Get the plugin instance
                            plugin = service_instance.get_plugin_instance()
                            if not plugin:
                                error_msg = f"Step 3: Could not get plugin instance for {service_instance.name}"
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
                            
                            # Create the formatted message
                            formatted_message = Message.objects.create(
                                service=service_instance,
                                direction='outgoing',
                                status='formatted',
                                processing_step='formatted',
                                step_processing_time={
                                    'formatted': {
                                        'start': timezone.now().isoformat(),
                                        'end': timezone.now().isoformat()  # Set end time immediately since formatting is complete
                                    }
                                },
                                source_service=message.service,
                                raingull_id=message.raingull_id,  # Copy the raingull_id from the original message
                                subject=translated_message.get('subject', ''),
                                sender=translated_message.get('from', ''),
                                recipient=translated_message.get('to', ''),
                                payload=translated_message.get('payload', {}),
                                created_at=timezone.now()
                            )
                            
                            # Update original message processing step
                            message.processing_step = 'formatted'
                            message.save()
                            
                            total_distributed += 1
                            logger.info(f"Step 3: Successfully formatted message {message.id} for {service_instance.name}")
                            
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
                            logger.error(f"Step 3: Error releasing lock for message {message.id}: {e}")
                            log_audit('error', f"Step 3: Error releasing lock for message {message.id}: {e}")
                    
            except Exception as e:
                error_msg = f"Step 3: Error processing message: {str(e)}"
                logger.error(error_msg)
                log_audit('error', error_msg)
                error_count += 1
                continue
                
        # Log distribution results
        result_msg = (
            f"Step 3: Distribution complete - "
            f"Distributed: {total_distributed}, "
            f"Errors: {error_count}, "
            f"Duplicates: {duplicate_count}, "
            f"Total Messages: {message_count}"
        )
        logger.info(result_msg)
        log_audit('outgoing_process', result_msg, None)
        
        return {
            'distributed': total_distributed,
            'errors': error_count,
            'duplicates': duplicate_count,
            'total': message_count
        }
        
    except Exception as e:
        error_msg = f"Step 3: Error in distribute_outgoing_messages task: {str(e)}"
        logger.error(error_msg)
        log_audit('error', error_msg)
        return None

@shared_task
def process_service_messages():
    """Process service-specific messages (invitations, password resets, etc.)"""
    try:
        # This task is no longer needed as we're using a unified Message model
        pass
                
    except Exception as e:
        logger.error(f"Error in process_service_messages: {e}")
        log_audit('error', f"Error in process_service_messages: {e}")

@shared_task
def distribute_messages():
    """
    Step 5: Distribute messages to their final destinations.
    This task:
    1. Gets all queued messages
    2. For each message:
       - Gets the appropriate plugin instance
       - Sends the message using the plugin
       - Updates message status
    """
    try:
        # Get all queued messages
        queued_messages = Message.objects.filter(
            status='queued'
        )
        
        total_messages = queued_messages.count()
        if total_messages == 0:
            log_audit(
                'message_distribution',
                "Step 5: No messages to distribute"
            )
            return None
            
        # Log start of distribution
        log_audit(
            'message_distribution',
            f"Step 5: Distributing {total_messages} message{'s' if total_messages > 1 else ''}"
        )
        
        distributed_count = 0
        for message in queued_messages:
            try:
                # Get the plugin instance
                plugin = message.service.get_plugin_instance()
                if not plugin:
                    error_msg = f"Step 5: Could not get plugin instance for service {message.service.name}"
                    logger.error(error_msg)
                    log_audit('error', error_msg, message.service)
                    continue
                    
                # Send the message
                result = plugin.send_message(message)
                if result:
                    message.status = 'sent'
                    message.sent_at = timezone.now()
                    message.save()
                    distributed_count += 1
                else:
                    message.status = 'failed'
                    message.error_message = "Failed to send message"
                    message.save()
                    
            except Exception as e:
                error_msg = f"Step 5: Error distributing message {message.id}: {str(e)}"
                logger.error(error_msg)
                log_audit('error', error_msg, message.service)
                message.status = 'failed'
                message.error_message = str(e)
                message.save()
                continue
                
        # Log distribution results
        log_audit(
            'message_distribution',
            f"Step 5: Distributed {distributed_count} of {total_messages} messages"
        )
        
        return None
        
    except Exception as e:
        error_msg = f"Step 5: Error in distribute_messages task: {str(e)}"
        logger.error(error_msg)
        log_audit('error', error_msg)
        return None

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

@shared_task
def monitor_message_processing():
    """
    Periodic task to monitor message processing and handle stuck messages.
    This task:
    1. Checks for messages stuck in processing
    2. Resets stuck messages for retry
    3. Collects processing metrics
    """
    try:
        # Get current time for comparison
        now = timezone.now()
        
        # Check for messages stuck in Step 1
        stuck_step1 = Message.objects.filter(
            processing_step='ingested',
            created_at__lt=now - timedelta(minutes=5)  # Stuck for more than 5 minutes
        )
        
        # Check for messages stuck in Step 2
        stuck_step2 = Message.objects.filter(
            processing_step='standardized',
            created_at__lt=now - timedelta(minutes=5)
        )
        
        # Check for messages stuck in Step 3
        stuck_step3 = Message.objects.filter(
            processing_step='formatted',
            created_at__lt=now - timedelta(minutes=5)
        )
        
        # Reset stuck messages
        for message in stuck_step1:
            message.processing_step = None
            message.save()
            logger.warning(f"Reset stuck message {message.id} from Step 1")
            
        for message in stuck_step2:
            message.processing_step = None
            message.status = 'new'
            message.save()
            logger.warning(f"Reset stuck message {message.id} from Step 2")
            
        for message in stuck_step3:
            message.processing_step = None
            message.status = 'new'
            message.save()
            logger.warning(f"Reset stuck message {message.id} from Step 3")
        
        # Collect processing metrics
        metrics = {
            'step1': {
                'total': Message.objects.filter(processing_step='ingested').count(),
                'stuck': stuck_step1.count()
            },
            'step2': {
                'total': Message.objects.filter(processing_step='standardized').count(),
                'stuck': stuck_step2.count()
            },
            'step3': {
                'total': Message.objects.filter(processing_step='formatted').count(),
                'stuck': stuck_step3.count()
            }
        }
        
        # Log metrics
        log_audit(
            'monitoring',
            f"Processing metrics: {json.dumps(metrics)}",
            None
        )
        
        return metrics
        
    except Exception as e:
        error_msg = f"Error in monitor_message_processing task: {str(e)}"
        logger.error(error_msg)
        log_audit('error', error_msg)
        return None 

@shared_task
def process_messages():
    """Main task that triggers all message processing steps."""
    try:
        # Step 1: Poll incoming services
        poll_incoming_services.delay()
        
        # Step 2: Process incoming messages
        process_incoming_messages.delay()
        
        # Step 3: Distribute outgoing messages
        distribute_outgoing_messages.delay()
        
        # Step 4: Queue outgoing messages for delivery
        # Get all active outgoing services
        outgoing_services = Service.objects.filter(outgoing_enabled=True)
        for service in outgoing_services:
            process_outgoing_messages.delay(service.id)
            
        # Step 5: Send queued messages (disabled for now)
        # for service in outgoing_services:
        #     send_queued_messages.delay(service.id)
            
        return {
            'status': 'success',
            'message': 'Started message processing pipeline'
        }
        
    except Exception as e:
        error_msg = f"Error in process_messages task: {str(e)}"
        logger.error(error_msg)
        log_audit('error', error_msg)
        return None 

@shared_task
def process_all_outgoing_messages():
    """
    Step 4: Process outgoing messages for all active outgoing services.
    This task:
    1. Gets all active outgoing services
    2. For each service, calls process_outgoing_messages
    """
    try:
        # Get all active outgoing services
        outgoing_services = Service.objects.filter(outgoing_enabled=True)
        
        total_services = outgoing_services.count()
        if total_services == 0:
            log_audit(
                'outgoing_queue',
                "Step 4: No active outgoing services configured",
                None
            )
            return None
            
        # Log start of processing
        log_audit(
            'outgoing_queue',
            f"Step 4: Starting processing for {total_services} outgoing service{'s' if total_services > 1 else ''}",
            None
        )
        
        # Process each service
        for service in outgoing_services:
            try:
                process_outgoing_messages.delay(service.id)
            except Exception as e:
                error_msg = f"Step 4: Error scheduling processing for service {service.name}: {str(e)}"
                logger.error(error_msg)
                log_audit('error', error_msg, service)
                continue
                
        return {
            'status': 'success',
            'message': f'Scheduled processing for {total_services} outgoing services'
        }
        
    except Exception as e:
        error_msg = f"Step 4: Error in process_all_outgoing_messages task: {str(e)}"
        logger.error(error_msg)
        log_audit('error', error_msg)
        return None 

@shared_task
def send_all_queued_messages():
    """
    Step 5: Send queued messages for all active outgoing services.
    This task:
    1. Gets all active outgoing services
    2. For each service, calls send_queued_messages
    """
    try:
        # Get all active outgoing services
        outgoing_services = Service.objects.filter(outgoing_enabled=True)
        
        total_services = outgoing_services.count()
        if total_services == 0:
            log_audit(
                'outgoing_send',
                "Step 5: No active outgoing services configured",
                None
            )
            return None
            
        # Log start of processing
        log_audit(
            'outgoing_send',
            f"Step 5: Starting sending for {total_services} outgoing service{'s' if total_services > 1 else ''}",
            None
        )
        
        # Process each service
        for service in outgoing_services:
            try:
                send_queued_messages.delay(service.id)
            except Exception as e:
                error_msg = f"Step 5: Error scheduling sending for service {service.name}: {str(e)}"
                logger.error(error_msg)
                log_audit('error', error_msg, service)
                continue
                
        return {
            'status': 'success',
            'message': f'Scheduled sending for {total_services} outgoing services'
        }
        
    except Exception as e:
        error_msg = f"Step 5: Error in send_all_queued_messages task: {str(e)}"
        logger.error(error_msg)
        log_audit('error', error_msg)
        return None 