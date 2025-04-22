from django.core.management.base import BaseCommand
import os
import json
import logging
from pathlib import Path
from django.conf import settings
from core.models import Plugin

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Discovers and registers plugins from the plugins directory'

    def handle(self, *args, **options):
        try:
            # Get the plugins directory path
            plugins_dir = Path(settings.BASE_DIR) / 'plugins'
            if not plugins_dir.exists():
                logger.error("Plugins directory not found")
                return

            # Get existing plugins from database
            existing_plugins = set(Plugin.objects.values_list('name', flat=True))

            # Scan plugins directory
            discovered_plugins = set()
            for plugin_dir in plugins_dir.iterdir():
                if not plugin_dir.is_dir():
                    continue

                # Check for manifest.json
                manifest_path = plugin_dir / 'manifest.json'
                if not manifest_path.exists():
                    continue

                try:
                    # Load and validate manifest
                    with open(manifest_path) as f:
                        manifest = json.load(f)

                    # Validate required fields
                    required_fields = ['name', 'friendly_name', 'version', 'description', 'capabilities']
                    if not all(field in manifest for field in required_fields):
                        logger.warning(f"Plugin {plugin_dir.name} missing required fields in manifest")
                        continue

                    # Check for plugin.py
                    plugin_path = plugin_dir / 'plugin.py'
                    if not plugin_path.exists():
                        logger.warning(f"Plugin {plugin_dir.name} missing plugin.py")
                        continue

                    # Check for __init__.py
                    init_path = plugin_dir / '__init__.py'
                    if not init_path.exists():
                        logger.warning(f"Plugin {plugin_dir.name} missing __init__.py")
                        continue

                    # Plugin is valid
                    discovered_plugins.add(manifest['name'])

                    # Create or update plugin in database
                    Plugin.objects.update_or_create(
                        name=manifest['name'],
                        defaults={
                            'friendly_name': manifest['friendly_name'],
                            'version': manifest['version'],
                            'manifest': manifest,
                            'enabled': manifest['name'] in existing_plugins
                        }
                    )

                    logger.info(f"Discovered plugin: {manifest['name']}")

                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON in manifest for plugin {plugin_dir.name}")
                except Exception as e:
                    logger.error(f"Error processing plugin {plugin_dir.name}: {str(e)}")

            # Disable plugins that no longer exist
            for plugin_name in existing_plugins - discovered_plugins:
                Plugin.objects.filter(name=plugin_name).update(enabled=False)
                logger.info(f"Disabled non-existent plugin: {plugin_name}")

            self.stdout.write(self.style.SUCCESS('Plugin discovery completed successfully'))

        except Exception as e:
            logger.error(f"Error during plugin discovery: {str(e)}")
            self.stdout.write(self.style.ERROR(f'Error: {str(e)}')) 