# Raingull Plugin Development Guide

This guide explains how to create plugins for the Raingull message processing system.

## Plugin Structure

Each plugin should be a Python package with the following structure:

```
plugins/
└── your_plugin/
    ├── __init__.py
    ├── plugin.py
    ├── manifest.json
    └── README.md
```

## Required Files

### 1. `__init__.py`
An empty file that marks the directory as a Python package.

### 2. `plugin.py`
Contains the plugin implementation class that inherits from `BasePlugin`.

### 3. `manifest.json`
Defines the plugin's capabilities and configuration schema.

### 4. `README.md`
Documentation specific to your plugin.

## Plugin Implementation

### Basic Plugin Structure

```python
from core.plugin_base import BasePlugin

class Plugin(BasePlugin):
    def get_manifest(self):
        return {
            "name": "your_plugin",
            "friendly_name": "Your Plugin Name",
            "version": "1.0",
            "description": "Description of your plugin",
            "capabilities": {
                "incoming": True,  # Set to True if plugin supports incoming messages
                "outgoing": True   # Set to True if plugin supports outgoing messages
            },
            "formatting": {
                "header_template": "**{user} via Your Service says:**\n---\n",
                "message_format": "markdown"  # or "text", "html", etc.
            },
            "config_schema": {
                "host": {
                    "type": "string",
                    "required": True,
                    "help_text": "Service hostname or IP address"
                },
                "port": {
                    "type": "integer",
                    "required": True,
                    "default": 1234,
                    "help_text": "Service port number"
                }
            }
        }

    def fetch_messages(self):
        # Implement message fetching logic
        pass

    def send_message(self, message):
        # Implement message sending logic
        pass

    def test_connection(self):
        # Implement connection testing logic
        pass
```

## Required Methods

### 1. `get_manifest()`
Returns a dictionary defining the plugin's capabilities and configuration schema.

### 2. `fetch_messages()`
Retrieves new messages from the service and returns them in a standardized format.

### 3. `send_message(message)`
Sends a message through the service.

### 4. `test_connection()`
Verifies that the plugin can connect to the service.

## Optional Methods

### 1. `standardize_payload(raw_payload)`
Converts service-specific message payloads to the Raingull standard format.

### 2. `format_for_outgoing(message)`
Formats Raingull messages for outgoing delivery.

## Message Format

### Incoming Messages
```python
{
    "service_message_id": "original_id",
    "subject": "Message Subject",
    "sender": "sender@example.com",
    "recipient": "recipient@example.com",
    "timestamp": datetime_object,
    "payload": {
        "content": "Message body",
        "attachments": [
            {
                "filename": "file.txt",
                "content": "base64_encoded_content",
                "mime_type": "text/plain"
            }
        ],
        "metadata": {
            "format": "markdown",
            "original_format": "html"
        }
    }
}
```

### Outgoing Messages
```python
{
    "content": "Formatted message body",
    "attachments": [
        {
            "filename": "file.txt",
            "content": "base64_encoded_content",
            "mime_type": "text/plain"
        }
    ],
    "format": "markdown"
}
```

## Configuration Schema

The `config_schema` in the manifest defines the configuration fields required by the plugin:

```json
{
    "field_name": {
        "type": "string|integer|boolean",
        "required": true|false,
        "default": "default_value",
        "help_text": "Field description"
    }
}
```

## Best Practices

1. **Error Handling**
   - Use try/except blocks to catch and log errors
   - Return appropriate status codes and error messages
   - Implement retry logic for transient failures

2. **Logging**
   - Use the logger instance provided by the base class
   - Log important events and errors
   - Include relevant context in log messages

3. **Security**
   - Never store sensitive information in logs
   - Validate all input data
   - Use secure connections when available

4. **Performance**
   - Implement efficient message fetching
   - Use connection pooling when appropriate
   - Handle large attachments appropriately

## Example Plugin

Here's a complete example of a simple plugin:

```python
from core.plugin_base import BasePlugin
import requests
from datetime import datetime

class Plugin(BasePlugin):
    def get_manifest(self):
        return {
            "name": "example",
            "friendly_name": "Example Plugin",
            "version": "1.0",
            "description": "Example plugin for demonstration",
            "capabilities": {
                "incoming": True,
                "outgoing": True
            },
            "formatting": {
                "header_template": "**{user} via Example says:**\n---\n",
                "message_format": "markdown"
            },
            "config_schema": {
                "api_url": {
                    "type": "string",
                    "required": True,
                    "help_text": "API endpoint URL"
                },
                "api_key": {
                    "type": "string",
                    "required": True,
                    "help_text": "API authentication key"
                }
            }
        }

    def fetch_messages(self):
        try:
            response = requests.get(
                self.config['api_url'],
                headers={'Authorization': self.config['api_key']}
            )
            response.raise_for_status()
            
            messages = []
            for msg in response.json():
                messages.append({
                    "service_message_id": msg['id'],
                    "subject": msg['subject'],
                    "sender": msg['from'],
                    "recipient": msg['to'],
                    "timestamp": datetime.fromisoformat(msg['date']),
                    "payload": {
                        "content": msg['body'],
                        "attachments": msg.get('attachments', []),
                        "metadata": {
                            "format": "markdown",
                            "original_format": msg.get('format', 'text')
                        }
                    }
                })
            return messages
        except Exception as e:
            logger.error(f"Error fetching messages: {e}")
            return []

    def send_message(self, message):
        try:
            formatted = self.format_for_outgoing(message)
            response = requests.post(
                self.config['api_url'],
                headers={'Authorization': self.config['api_key']},
                json={
                    'to': message.recipient,
                    'subject': message.subject,
                    'body': formatted['content'],
                    'attachments': formatted['attachments']
                }
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return False

    def test_connection(self):
        try:
            response = requests.get(
                self.config['api_url'],
                headers={'Authorization': self.config['api_key']}
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
```

## Testing Your Plugin

1. Create a test service instance in the admin interface
2. Configure the service with test credentials
3. Use the test connection button to verify connectivity
4. Send test messages through the service
5. Check the logs for any errors

## Debugging

1. Enable debug logging in your plugin
2. Check the Raingull logs for plugin-related messages
3. Use the admin interface to monitor message flow
4. Test with small messages first
5. Verify configuration values are correct

## Contributing

1. Follow the plugin structure outlined above
2. Include comprehensive documentation
3. Test your plugin thoroughly
4. Submit a pull request with your changes 