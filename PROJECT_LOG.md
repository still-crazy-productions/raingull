# Project Log

## 2024-04-20

### Database Cleanup
- Renamed tables to be more consistent and descriptive:
  - `core_raingullstandardmessage` → `core_messages`
  - `core_outgoingmessagequeue` → `core_message_queues`
  - `core_raingulluser` → `core_users` (using standard Django User model)
  - `core_raingulluser_groups` → `core_user_groups` (using standard Django Group model)
  - `core_plugin` → `core_plugins`
  - `core_userserviceactivation` → `core_user_services`

### User Model Changes
- Switched from custom `RaingullUser` model to standard Django User model
- Moved user-specific fields to `UserProfile` model:
  - timezone
  - mfa_enabled
  - mfa_secret
  - web_login_enabled
- Added Django admin interface
- Created default groups: 'Admins' and 'Moderators'

### Next Steps
1. Test the new database structure
2. Update any remaining code that references the old table names
3. Test user management functionality
4. Test message processing functionality
5. Test service activation functionality

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