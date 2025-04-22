from django.core.management.base import BaseCommand
import subprocess
import os
import signal
import sys
import time
import logging
from core.models import AuditLog

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Reboots the Raingull application'

    def handle(self, *args, **options):
        try:
            self.stdout.write('Rebooting Raingull...')
            
            # Log the reboot attempt
            AuditLog.objects.create(
                event_type='info',
                status='info',
                details='Initiating Raingull reboot'
            )
            
            # Get the process ID of the current Django process
            pid = os.getpid()
            
            try:
                # Send SIGTERM to gracefully shut down
                os.kill(pid, signal.SIGTERM)
                
                # Wait a moment for the process to shut down
                time.sleep(2)
                
                # Start a new process
                subprocess.Popen([sys.executable, 'manage.py', 'runserver'])
                
                # Log successful reboot
                AuditLog.objects.create(
                    event_type='info',
                    status='success',
                    details='Raingull reboot completed successfully'
                )
                
                self.stdout.write(self.style.SUCCESS('Raingull has been rebooted'))
                
            except OSError as e:
                error_msg = f"Error during reboot process: {str(e)}"
                logger.error(error_msg)
                AuditLog.objects.create(
                    event_type='error',
                    status='error',
                    details=error_msg
                )
                self.stdout.write(self.style.ERROR(error_msg))
                
        except Exception as e:
            error_msg = f"Unexpected error during reboot: {str(e)}"
            logger.error(error_msg)
            AuditLog.objects.create(
                event_type='error',
                status='error',
                details=error_msg
            )
            self.stdout.write(self.style.ERROR(error_msg)) 