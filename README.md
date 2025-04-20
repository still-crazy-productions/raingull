# Raingull

## 🛠️ Developer Environment
- OS: Linux (EndeavourOS)
- Shell: Zsh
- IDE: Cursor
- Python Version: 3.x
- Virtual Environment: .venv

> **Important**: All commands in this project should use Linux CLI/bash/zsh syntax. Do NOT use PowerShell commands.

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