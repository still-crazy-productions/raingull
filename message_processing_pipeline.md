# Raingull Message Processing Pipeline

## 1. Message Ingestion
**Purpose**: Get messages into the system from various sources
**Two Primary Methods**:

### A. Webhook-Based Ingestion
- Used by: Twilio SMS, Telegram, Discord, etc.
- Process:
  1. External service calls Raingull webhook
  2. Webhook validates and authenticates request
  3. Message stored in service-specific incoming table
  4. Status set to 'new'

### B. Polling-Based Ingestion
- Used by: IMAP, POP3, etc.
- Process:
  1. Celery beat scheduler runs periodic tasks
  2. Each Service Instance has its own polling task
  3. Task frequency configured per instance
  4. New messages stored in service-specific incoming table
  5. Status set to 'new'

**Implementation**:
```python
# Celery beat configuration
CELERY_BEAT_SCHEDULE = {
    'poll-imap-services': {
        'task': 'poll_service_instances',
        'schedule': timedelta(seconds=60)
    }
}

# Service Instance model
class ServiceInstance(models.Model):
    polling_interval = models.IntegerField()  # in seconds
    last_polled = models.DateTimeField(null=True)
```

## 2. Message Standardization
**Purpose**: Convert service-specific messages to Raingull standard format
**Process**:
1. Periodic task checks all service-specific incoming tables
2. Finds messages with status 'new'
3. Translates to Raingull format using plugin manifest rules
4. Stores in core message table
5. Updates original message status to 'processed'

**Implementation**:
```python
@celery.task
def standardize_messages():
    # Get all new messages across all services
    new_messages = IncomingMessage.objects.filter(
        status='new'
    ).select_for_update()
    
    for message in new_messages:
        try:
            standardized = translate_to_standard(message)
            CoreMessage.objects.create(
                raingull_id=uuid.uuid4(),
                content=standardized,
                source_service=message.service_instance
            )
            message.status = 'processed'
            message.save()
        except Exception as e:
            message.status = 'error'
            message.error_message = str(e)
            message.save()
```

## 3. Outgoing Message Preparation
**Purpose**: Convert standard messages to service-specific formats
**Process**:
1. Periodic task checks core message table
2. For each active outgoing service:
   - Translates message to service format
   - Creates entry in service-specific outgoing table
   - Handles snippets if configured
   - May reuse original format if compatible

**Implementation**:
```python
@celery.task
def prepare_outgoing_messages():
    core_messages = CoreMessage.objects.filter(
        status='new'
    )
    
    for message in core_messages:
        for service in active_outgoing_services:
            try:
                outgoing = translate_to_service_format(message, service)
                OutgoingMessage.objects.create(
                    service_instance=service,
                    core_message=message,
                    content=outgoing
                )
            except Exception as e:
                log_error(message, service, e)
```

## 4. User Message Queueing
**Purpose**: Create delivery queue entries for each user
**Process**:
1. For each outgoing message:
   - Find all users with active service configuration
   - Create delivery queue entry for each user
   - Apply user delivery preferences
   - Set scheduled delivery time

**Implementation**:
```python
@celery.task
def queue_messages_for_users():
    outgoing_messages = OutgoingMessage.objects.filter(
        status='queued'
    )
    
    for message in outgoing_messages:
        users = get_eligible_users(message.service_instance)
        for user in users:
            DeliveryQueue.objects.create(
                user=user,
                outgoing_message=message,
                scheduled_delivery=calculate_delivery_time(user.preferences)
            )
```

## 5. Message Delivery
**Purpose**: Send messages to users through appropriate services
**Process**:
1. Process delivery queue entries
2. Respect delivery windows
3. Handle retries
4. Track delivery status

**Implementation**:
```python
@celery.task
def process_delivery_queue():
    ready_messages = DeliveryQueue.objects.filter(
        status='queued',
        scheduled_delivery__lte=timezone.now()
    )
    
    for delivery in ready_messages:
        try:
            result = send_message(
                delivery.outgoing_message,
                delivery.user.service_config
            )
            delivery.status = 'delivered'
            delivery.save()
        except Exception as e:
            handle_delivery_failure(delivery, e)
```

## 6. Data Retention
**Purpose**: Clean up old messages
**Process**:
1. Daily task runs to purge old messages
2. Configurable retention period (default 30 days)
3. Purges all related records across tables
4. Maintains referential integrity

**Implementation**:
```python
@celery.task
def purge_old_messages():
    cutoff = timezone.now() - timedelta(days=settings.RETENTION_DAYS)
    old_messages = CoreMessage.objects.filter(
        status='completed',
        created_at__lt=cutoff
    )
    
    for message in old_messages:
        with transaction.atomic():
            delete_related_records(message.raingull_id)
```

## System Architecture Recommendations

1. **Message Broker**
- Use Redis or RabbitMQ as Celery broker
- Provides reliable message queuing
- Enables distributed processing

2. **Database Design**
- Use UUIDs for message identification
- Implement proper indexing
- Use transactions for data integrity
- Consider partitioning for large tables

3. **Monitoring**
- Track queue lengths
- Monitor processing times
- Alert on errors
- Track delivery success rates

4. **Error Handling**
- Implement retry mechanisms
- Use dead letter queues
- Log detailed error information
- Provide admin tools for manual intervention

5. **Scalability Considerations**
- Design for horizontal scaling
- Use connection pooling
- Implement rate limiting
- Consider message batching

6. **Admin Interface**
- Provide comprehensive monitoring
- Enable manual intervention
- Show message flow visualization
- Include analytics and reporting

This pipeline provides a robust foundation for handling messages across various services while maintaining flexibility for future expansion. Each step is designed to be independently scalable and maintainable. 