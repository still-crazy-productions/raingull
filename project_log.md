## Raingull Project Log (Updated April 22, 2025)

### ✅ Recent Changes:

1. **Architectural Simplification**
   - Eliminated dynamic table system in favor of a unified message storage approach
   - Implemented a single `Message` model with service-specific fields stored as JSON
   - Removed complex table creation/deletion logic
   - Simplified service management and message handling
   - Improved database consistency and reduced complexity

2. **Service Management UI Improvements**
   - Enhanced form layouts for both Add and Edit Service pages
   - Added proper spacing and padding using Tailwind CSS
   - Improved field organization and visual hierarchy
   - Added password toggle functionality for secure input
   - Implemented proper handling of unavailable capabilities
   - Added delete confirmation modal for service removal

3. **Plugin System Refinements**
   - Updated SMTP plugin manifest with proper TLS options
   - Removed unnecessary default_recipient field
   - Improved field type handling in forms
   - Added help text support for configuration fields
   - Enhanced test connection functionality

### ✅ Accomplishments:

1. **Project Initialization**
   - Created Django project `raingull`.
   - Setup applications: `core` (main app), `email_plugin` (handles IMAP/SMTP).
   - Defined models (`Plugin`, `ServiceInstance`) with JSON-based dynamic configurations.

2. **Plugin Infrastructure**
   - Established a plugin registration system.
   - Implemented manifest structure (`manifest.json`) for plugins.
   - Tested manifest file parsing and dynamic configuration handling successfully.

3. **Dynamic Form Handling**
   - Successfully generated dynamic Django forms from plugin manifest files.
   - Resolved issues with dynamic fields not displaying in the Django admin by shifting to custom views/templates.
   - Confirmed dynamic form fields render correctly and data is stored as intended.

4. **Custom Admin Management**
   - Developed routes (`urls.py`) and views (`views.py`) for managing service instances outside of Django's built-in admin.
   - Created and tested custom templates:
     - `templates/core/service_instance_list.html`
     - `templates/core/manage_service_instance.html`

5. **IMAP Plugin Implementation**
   - Successfully implemented full CRUD operations for IMAP service instances:
     - Create: Dynamic tables created based on plugin manifest
     - Read: Configuration fields properly displayed and loaded
     - Update: Changes saved correctly to database
     - Delete: Service instance and associated tables properly removed
   - Added "Test Connection" functionality that works in both create and manage views
   - Implemented robust table creation and deletion for dynamic models
   - Added comprehensive error handling and logging

6. **SMTP Plugin Implementation**
   - Successfully implemented full CRUD operations for SMTP service instances
   - Added "Test Connection" functionality matching IMAP plugin behavior
   - Implemented outgoing message schema for email sending
   - Added proper error handling for SMTP operations
   - Verified dynamic table creation and deletion
   - Confirmed proper handling of different encryption types (None, STARTTLS, SSL/TLS)

7. **Message Standardization**
   - Implemented `RaingullStandardMessage` model for unified message format
   - Added `raingull_id` field to track messages across different services
   - Implemented message translation from IMAP to standard format
   - Added snippet generation (first 200 characters) for message previews
   - Verified proper copying of message IDs across tables
   - Tested successful translation of multiple messages

### ⚠️ Current Known Issues:
- None at this time

### 🚧 Next Immediate Steps:
- Implement message processing with the new unified storage approach
- Add message distribution logic for the simplified architecture
- Create a unified interface for managing messages across services
- Add comprehensive error handling and retry mechanisms

### 🚀 Git Push Workflow:

```bash
cd ~/dev/raingull
git status
git add .
git commit -m "Simplified architecture: Removed dynamic tables, improved service management UI"
git push origin main
```

## 2025-04-21
- Fixed database table names to use consistent naming:
  - Changed `core_user` to `core_users`
  - Confirmed `core_user_permissions` is correct
  - Updated initial migration file to reflect correct table names
  - Verified all other model table names are correct
- Identified issue with user activation URL pattern (to be fixed later):
  - Current pattern expects only token parameter
  - Code trying to pass both uidb64 and token
  - Will need to update URL pattern when implementing invitation email functionality

## 2024-04-20
- Renamed tables to be more consistent and descriptive:
  - `core_raingullstandardmessage` → `core_messages`
  - `core_outgoingmessagequeue` → `core_message_queues`
  - `core_raingulluser` → `core_users` (using standard Django User model)
  - `core_raingulluser_groups` → `core_user_groups` (using standard Django Group model)
  - `core_plugin` → `core_plugins`
  - `core_userserviceactivation` → `core_user_services`
- Switched from custom `RaingullUser` model to standard Django User model
- Moved user-specific fields to `UserProfile` model:
  - timezone
  - mfa_enabled
  - mfa_secret
  - web_login_enabled
- Added Django admin interface
- Created default groups: 'Admins' and 'Moderators'

## 2024-04-16
- Implemented RaingullStandardMessage model for unified message format
- Added raingull_id field to track messages across services
- Implemented message translation from IMAP to standard format
- Added snippet generation for message previews
- Verified proper copying of message IDs across tables
- Tested successful translation of multiple messages

## 2024-03-22
- Successfully implemented SMTP plugin with full CRUD operations
- Added test connection functionality for SMTP service instances
- Verified proper handling of different encryption types
- Confirmed dynamic table creation and deletion

## 2024-03-21
- Implemented dynamic configuration fields for ServiceInstance based on plugin manifest
- Created DynamicServiceInstanceForm to handle plugin-specific configuration
- Added test connection functionality for plugins with incoming capability
- Fixed manifest loading and field type handling in ServiceInstance model
- Implemented service instance management interface
- Added debug output for connection testing
- Current issue: Test connection button not working in manage service instance view despite working in create view
  - Debug info shows plugin and manifest are loaded correctly
  - JavaScript event handlers appear to be attached
  - No errors in browser console
  - Next steps: Compare event handling between create and manage views, check CSRF token handling

## 2024-03-20
// ... existing code ...

## 2025-04-19
- Fixed IMAP Plugin issues:
  - Added proper message ID tracking to prevent duplicate processing
  - Improved message processing logic to ensure each message is only processed once
  - Fixed message ID handling in database storage
- Fixed SMTP Plugin issues:
  - Added unique constraint to raingull_id field to prevent duplicate entries
  - Identified and documented database consistency issues
- Identified need for database cleanup and rebuild:
  - Multiple copies of messages in processed folder
  - Duplicate entries in SMTP outgoing table
  - Inconsistent message queue entries
- Next steps:
  - Rebuild database from scratch
  - Test IMAP and SMTP integration with clean state
  - Implement additional safeguards against duplicate processing

## 2024-04-20
- Fixed SMTP sending functionality in Celery worker process
- Corrected recipient email handling to use user's service activation configuration
- Identified and documented MXRoute limitation regarding recipient addresses
- Successfully tested message distribution through multiple SMTP services
- Verified correct handling of From addresses based on SMTP service configuration
- Improved error handling and logging in SMTP message sending
- Fixed user activation system:
  - Properly combined user ID and token in activation URLs
  - Fixed token validation in activation view
  - Added proper error handling for invalid activation links
- Improved invitation emails:
  - Added dynamic field support based on service instance configuration
  - Used service instance's configured sender email
  - Fixed message template formatting to include user's first name
  - Ensured activation links work correctly
- Fixed message distribution:
  - Added proper handling of invitation messages
  - Improved message queue handling for service-specific messages
- Fixed dynamic fields not appearing in invite user form
  - Moved JavaScript code from head block to extra_js block in invite_user.html
  - Ensures DOM is fully loaded before executing JavaScript
  - Maintains existing navigation menu functionality
  - Improves user experience by properly loading service-specific fields

### 🚧 Next Steps:
- Remove Django admin interface
- Design and implement custom admin panel
- Improve error handling for SMTP recipient validation
- Consider implementing fallback SMTP service on send failure

<div class="form-group">
    <div class="custom-control custom-checkbox">
        <input type="checkbox" class="custom-control-input" id="enable_web_login" name="enable_web_login">
        <label class="custom-control-label" for="enable_web_login">Enable web login access</label>
        <small class="form-text text-muted">If checked, the user will receive a link to access the web interface. If unchecked, they will only be able to receive messages.</small>
    </div>
</div>

# Project Log

## 2024-04-20

### Model Refactoring
- Renamed `ServiceInstance` model to `Service` for clarity
- Updated all references in `views.py` to use the new name
- Fixed import statements and model references throughout the codebase
- Created migration to rename the `ServiceInstance` table to `core_services`
- Added `app_config` field to the `Service` model

### Service Testing
- Successfully tested service creation and plugin activation
- Verified dynamic table creation (smtp_1_out, imap_2_in)
- Confirmed core_services table structure and data integrity

### Known Issues
- Test Connection buttons not working (JavaScript loading/timing issue)
- IMAP/SMTP passwords stored as plain text in database (security concern)

### Pending Tasks
- Drop the `PluginInstance` table
- Fix Test Connection button functionality
- Implement secure password storage for service configurations

class Message(models.Model):
    # ... existing fields ...
    processed = models.BooleanField(default=False)

# In process_incoming_messages
for message in new_messages:
    # Create standard message
    standard_message = Message.create_standard_message(...)
    standard_message.processed = False  # Mark as unprocessed for Step 3
    
    # Create distribution records for all active outgoing services
    for service in Service.objects.filter(outgoing_enabled=True):
        # Skip if message is from this service (no echo)
        if message.source_service == service:
            continue
        if MessageDistribution.objects.filter(
            message=message,
            service_instance=service,
            status='formatted'
        ).exists():
            continue
        MessageDistribution.objects.get_or_create(
            message=standard_message,
            service=service,
            defaults={'status': 'pending'}
        )

# In format_outgoing_messages
new_messages = Message.objects.filter(
    Q(messagedistribution__isnull=True) |  # New messages from Step 2
    Q(messagedistribution__status='failed')  # Failed distributions to retry
).distinct()

class MessageQueue(models.Model):
    # ... existing fields ...
    retry_count = models.IntegerField(default=0)
    last_retry_at = models.DateTimeField(null=True, blank=True)

## 2024-03-21: Message Processing System Improvements

### Step 4: Message Queueing Implementation
- **Task**: `process_outgoing_messages`
- **Changes**:
  - Separated queueing logic from sending logic
  - Implemented original sender protection
  - Enhanced error handling and logging
  - Added proper status tracking
- **Database Updates**:
  - Confirmed use of `core_message_queue` (singular)
  - Verified table relationships and indexes
- **Audit Logging**:
  - Added consistent "Step 4:" prefix to logs
  - Enhanced error context in logs
  - Improved logging for skipped messages
- **Performance**:
  - Implemented proper locking mechanism
  - Added batch processing capabilities
  - Optimized database queries

### Step 5: Message Sending Implementation
- **Task**: `send_queued_messages`
- **Changes**:
  - Moved sending logic from Step 4
  - Implemented retry logic with exponential backoff
  - Added comprehensive error handling
  - Enhanced status tracking
- **Retry Mechanism**:
  - Added `retry_count` and `last_retry_at` fields
  - Implemented exponential backoff timing
  - Set maximum retry limit
- **Audit Logging**:
  - Added consistent "Step 5:" prefix to logs
  - Enhanced error and retry logging
  - Improved status tracking logs
- **Error Handling**:
  - Added service connection error handling
  - Implemented lock management
  - Enhanced message status updates

### System Improvements
- **Message Flow**:
  - Clear separation between queueing and sending
  - Improved status tracking across steps
  - Enhanced error recovery
- **Performance**:
  - Optimized database operations
  - Improved locking mechanisms
  - Enhanced batch processing
- **Documentation**:
  - Updated README.md with detailed pipeline description
  - Added comprehensive status tracking documentation
  - Enhanced error handling documentation

### Next Steps
1. Implement message cleanup system
2. Add monitoring and alerting
3. Enhance performance metrics
4. Add system health checks

## Previous Entries
// ... existing code ...