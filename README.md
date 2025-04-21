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

The Raingull system processes messages through a 5-step pipeline, with each step handling a specific aspect of message flow. For detailed documentation, see [Message Processing Pipeline](docs/message_processing_pipeline.md).

### Step 1: Incoming Message Retrieval
- **Task**: `poll_imap_services`
- **Input**: IMAP server
- **Output**: `plugin_serviceid_in` table (e.g., `imap_incoming_1`)
- **Purpose**: Retrieves new messages from the IMAP server and stores them in the plugin-specific incoming table
- **Status Flow**: Messages are stored with `status='new'` to indicate they need processing

### Step 2: Core Message Translation
- **Task**: `process_incoming_messages`
- **Input**: `plugin_serviceid_in` table
- **Output**: `core_messages` table
- **Purpose**: Translates plugin-specific messages into the standard Raingull message format
- **Status Flow**: Updates original message to `status='processed'` after successful translation

### Step 3: Outgoing Service Formatting
- **Task**: `format_outgoing_messages`
- **Input**: `core_messages` table
- **Output**: `plugin_serviceid_out` tables (e.g., `smtp_outgoing_2`)
- **Purpose**: Creates service-specific formatted copies of messages for each active outgoing service
- **Status Flow**: Messages are stored with `status='formatted'` to indicate they're ready for distribution

### Step 4: User Distribution
- **Task**: `distribute_outgoing_messages`
- **Input**: `plugin_serviceid_out` tables
- **Output**: `core_message_queue` table
- **Purpose**: Creates queue entries for each active user of each outgoing service
- **Status Flow**: Queue entries are created with `status='queued'` for delivery

### Step 5: Message Delivery
- **Task**: `process_outgoing_messages`
- **Input**: `core_message_queue` table
- **Output**: Outgoing service (e.g., SMTP server)
- **Purpose**: Sends messages using the appropriate outgoing service
- **Status Flow**: Updates queue entry to `status='sent'` or `status='failed'`

### Key Benefits of the 5-Step Approach
1. **Clear Separation of Concerns**: Each step handles a specific aspect of message processing
2. **Data Format Guarantee**: Each outgoing service gets its own properly formatted copy
3. **Error Isolation**: Issues in one step don't affect others
4. **Performance**: Formatting happens once per service type, not per user
5. **Audit Trail**: Clear record of message lifecycle and formatting 

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