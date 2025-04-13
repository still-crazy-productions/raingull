# RainGull Project Log

## Environment Setup

### Date: [Today's Date]

**Accomplished:**
- Created the project directory (`~/dev/raingull`).
- Set up Python virtual environment (`.venv`).
- Installed Django 5.2.
- Resolved filesystem permission errors caused by mistakenly running commands with elevated permissions.
- Initialized Django project (`raingull`) successfully.
- Created initial Django apps:
  - `core` (for user management, plugin management, logging, message queues).
  - `email_plugin` within the `plugins` directory (for IMAP & SMTP email handling).
- Opened the project successfully in VS Code.

**Current Project Structure:**
```
raingull/
├── core/
│   ├── migrations/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── models.py
│   ├── tests.py
│   └── views.py
├── plugins/
│   └── email_plugin/
│       ├── migrations/
│       ├── __init__.py
│       ├── admin.py
│       ├── apps.py
│       ├── models.py
│       ├── tests.py
│       └── views.py
├── raingull/
│   ├── __init__.py
│   ├── asgi.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── manage.py
└── .venv/
```

## Next Steps
- Configure Django settings (`raingull/settings.py`) by adding:
  ```python
  INSTALLED_APPS = [
      'django.contrib.admin',
      'django.contrib.auth',
      'django.contrib.contenttypes',
      'django.contrib.sessions',
      'django.contrib.messages',
      'django.contrib.staticfiles',
      'core',
      'plugins.email_plugin',
  ]
  ```
- Begin designing the plugin architecture and core functionality:
  - Define basic models in the `core` app.
  - Establish an initial interface for plugins.
  - Implement basic IMAP/SMTP handling in `email_plugin`.

---

## Notes
- Avoid using global Python/Django installations (`sudo`, `pipx`) within virtual environments.
- Always activate your virtual environment before running Django-related commands.
- Document issues and their resolutions clearly in this log for future reference.

