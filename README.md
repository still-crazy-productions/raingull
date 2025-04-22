# Raingull

## 🛠️ Developer Environment
- OS: Linux (EndeavourOS)
- Shell: Zsh
- IDE: Cursor
- Python Version: 3.x
- Virtual Environment: .venv

> **Important**: All commands in this project should use Linux CLI/bash/zsh syntax. Do NOT use PowerShell commands.

## Known Issues

### Security Concerns
- **Password Storage**: IMAP and SMTP passwords are currently stored as plain text in the database. This is a significant security risk and should be addressed in future updates.
  - Consider implementing encryption for sensitive configuration data
  - Explore using Django's built-in encryption utilities
  - Implement secure key management for encrypted data

### Functionality Issues
- **Test Connection Buttons**: The test connection functionality in the service management interface is currently not working due to JavaScript loading/timing issues.
  - Issue appears to be related to DOM loading and event binding
  - May require restructuring of template loading or JavaScript execution timing

## Project Status
- Core service functionality is operational
- Dynamic table creation working correctly
- Plugin activation and service creation working as expected

## Project Overview
Raingull is a Django-based message processing and routing system with a plugin architecture for different services.

## Setup
1. Create and activate virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run migrations:
   ```bash
   python manage.py migrate
   ```

4. Start development server:
   ```bash
   python manage.py runserver
   ```

## Project Structure
- `core/`: Main application code
- `plugins/`: Service plugins
- `templates/`: HTML templates
- `static/`: Static files (CSS, JS, images)
- `raingull/`: Project configuration

## File Organization
### Templates
All templates should be placed in `/core/templates/` with the following structure:
- `/core/templates/core/`: Core application templates
- `/core/templates/registration/`: User registration templates
- `/core/templates/<plugin_name>/`: Plugin-specific templates

### Static Files
All static files should be placed in `/core/static/` with the following structure:
- `/core/static/css/`: CSS files
- `/core/static/js/`: JavaScript files
- `/core/static/<plugin_name>/`: Plugin-specific static files

## Development Guidelines
- Use Linux commands for all operations
- Follow PEP 8 style guide
- Document new features
- Test before committing 

## Message Processing Pipeline

The Raingull system processes messages through a 5-step pipeline, with each step handling a specific aspect of message flow. This design ensures reliable message delivery while maintaining clear separation of concerns and robust error handling.

### Step 1: Message Ingestion
- **Task**: `poll_incoming_services`
- **Purpose**: Retrieve new messages from incoming services
- **Process**:
  1. Polls all active incoming services (e.g., IMAP)
  2. Retrieves new messages and stores them in service-specific tables (e.g., `imap_1_in`)
  3. Implements proper locking to prevent duplicate processing
  4. Maintains detailed audit logs of polling operations
- **Status Flow**: Messages stored with `status='new'` for processing
- **Error Handling**: 
  - Service connection failures
  - Message retrieval errors
  - Lock acquisition issues

### Step 2: Message Processing
- **Task**: `process_incoming_messages`
- **Purpose**: Translate service-specific messages to standard format
- **Process**:
  1. Retrieves new messages from service-specific tables
  2. Translates to standard Raingull format
  3. Stores in `core_messages` table
  4. Updates original message status
- **Status Flow**: 
  - Original message: `status='processed'`
  - New message: `status='new'` for distribution
- **Error Handling**:
  - Translation failures
  - Database errors
  - Duplicate message detection

### Step 3: Message Distribution
- **Task**: `distribute_outgoing_messages`
- **Purpose**: Create service-specific formatted copies
- **Process**:
  1. Takes messages from `core_messages`
  2. For each active outgoing service:
     - Translates message to service format
     - Stores in service-specific table (e.g., `smtp_1_out`)
     - Creates `MessageDistribution` record
  3. Handles retries for failed distributions
- **Status Flow**:
  - Service message: `status='formatted'`
  - Distribution record: `status='formatted'` or `status='failed'`
- **Error Handling**:
  - Service-specific formatting errors
  - Distribution failures
  - Lock management issues

### Step 4: Message Queueing
- **Task**: `process_outgoing_messages`
- **Purpose**: Create individual queue entries for users
- **Process**:
  1. Takes messages from service-specific outgoing tables
  2. For each message:
     - Gets all active users for that service
     - Creates queue entries in `core_message_queue`
     - Skips original sender
     - Handles special cases (invitations)
  3. Updates service-specific message status
- **Status Flow**:
  - Queue entry: `status='queued'`
  - Service message: `status='queued'`
- **Error Handling**:
  - Missing user activations
  - Queue creation failures
  - Invalid recipient addresses

### Step 5: Message Sending
- **Task**: `send_queued_messages`
- **Purpose**: Deliver messages through appropriate services
- **Process**:
  1. Takes queued messages from `core_message_queue`
  2. For each message:
     - Gets appropriate plugin instance
     - Sends through service
     - Updates status
     - Handles retries with exponential backoff
  3. Marks messages as fully processed when all copies sent
- **Status Flow**:
  - Queue entry: `status='sent'` or `status='failed'`
  - Original message: `status='processed'` when complete
- **Error Handling**:
  - Send failures
  - Retry management
  - Service connection issues
  - Lock management

### Key Features and Benefits
1. **Clear Separation of Concerns**: Each step has a specific, well-defined responsibility
2. **Robust Error Handling**: Comprehensive error handling at each step
3. **Reliable Message Delivery**: Retry logic and status tracking ensure delivery
4. **Performance Optimization**: 
   - Message batching by service
   - Efficient plugin initialization
   - Proper locking mechanisms
5. **Comprehensive Audit Trail**: Detailed logging at each step
6. **Flexible Service Integration**: Easy addition of new service types
7. **User-Specific Delivery**: Proper handling of user service activations
8. **Original Sender Protection**: Prevents message loops by skipping original sender

### Database Tables Involved
- Core Tables:
  - `core_messages`: Standard message format
  - `core_message_queue`: Individual delivery queue
  - `core_user_services`: User service activations
  - `core_services`: Service configurations
  - `core_plugins`: Plugin definitions
- Service-specific Tables:
  - Incoming: `{plugin_name}_{instance.id}_in` (e.g., `imap_1_in`)
  - Outgoing: `{plugin_name}_{instance.id}_out` (e.g., `smtp_1_out`)

### Status Tracking
- **Message States**:
  - `new`: Initial state
  - `processed`: Successfully processed
  - `formatted`: Ready for distribution
  - `queued`: Ready for sending
  - `sent`: Successfully delivered
  - `failed`: Delivery failed
- **Retry Tracking**:
  - `retry_count`: Number of attempts
  - `last_retry_at`: Timestamp of last attempt
  - Exponential backoff between retries

### Audit Logging
- **Event Types**:
  - `incoming_poll`: Step 1 operations
  - `incoming_process`: Step 2 operations
  - `outgoing_process`: Step 3 operations
  - `outgoing_queue`: Step 4 operations
  - `outgoing_send`: Step 5 operations
  - `error`: Error conditions
  - `warning`: Warning conditions
- **Log Format**: Consistent prefixing with step number and detailed context

# Get all active outgoing services
outgoing_services = Service.objects.filter(
    outgoing_enabled=True
)

# Get unprocessed messages
unprocessed_messages = Message.objects.filter(
    processed=False
)

if outgoing_model.objects.filter(raingull_id=message.raingull_id).exists():
    continue 

lock_key = f"format_message:{service.id}:{message.raingull_id}" 

class MessageDistribution(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE)
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('formatted', 'Formatted'),
        ('failed', 'Failed')
    ])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True) 

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from django.utils import timezone
from core.models import Message, Service
from core.plugin_base import BasePlugin
import imaplib
import email
from email.utils import parsedate_to_datetime

class Plugin(BasePlugin):
    def get_manifest(self):
        return {
            "name": "imap",
            "friendly_name": "IMAP Email",
            "version": "1.0",
            "description": "IMAP email integration",
            "capabilities": {
                "incoming": True,
                "outgoing": False
            },
            "formatting": {
                "header_template": "**{user} via Email says:**\n---\n",
                "message_format": "markdown"
            },
            "config_schema": {
                "host": {"type": "string", "required": True},
                "port": {"type": "integer", "required": True},
                "use_ssl": {"type": "boolean", "default": True}
            }
        }

    def fetch_messages(self):
        # Connect to IMAP server
        imap = self._connect()
        if not imap:
            return []

        messages = []
        try:
            # IMAP-specific message fetching logic
            # Convert to Raingull format
            for msg in raw_messages:
                messages.append({
                    'service_message_id': msg['message_id'],
                    'subject': msg['subject'],
                    'sender': msg['from'],
                    'timestamp': parsedate_to_datetime(msg['date']),
                    'payload': {
                        'content': msg['body'],
                        'attachments': msg.get('attachments', [])
                    }
                })
        finally:
            imap.logout()
        return messages

    def test_connection(self):
        try:
            imap = self._connect()
            if imap:
                imap.logout()
                return True
        except Exception as e:
            logger.error(f"IMAP connection test failed: {e}")
        return False

    def _connect(self):
        try:
            imap = imaplib.IMAP4_SSL if self.config.get('use_ssl', True) else imaplib.IMAP4
            connection = imap(self.config['host'], self.config['port'])
            connection.login(self.config['username'], self.config['password'])
            return connection
        except Exception as e:
            logger.error(f"IMAP connection failed: {e}")
            return None 