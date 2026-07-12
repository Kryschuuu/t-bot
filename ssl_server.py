# ssl_server.py
#
# NUR fuer lokale HTTPS-Entwicklung gedacht (z.B. um Browser-Feature-
# Beschraenkungen zu testen, die HTTPS voraussetzen). Auf Render WIRD DIESES
# SKRIPT NICHT VERWENDET: Render terminiert TLS/SSL zentral am Edge/Load-
# balancer und leitet unverschluesselten HTTP-Traffic an den Container
# weiter (Header X-Forwarded-Proto zeigt an, dass es urspruenglich https war,
# siehe SECURE_PROXY_SSL_HEADER in settings.py). Ein eigener SSL-Server im
# Container ist dort weder noetig noch sinnvoll - der Produktions-Start-
# befehl ist stattdessen ein ASGI-Server (daphne), siehe render.yaml.
import os
import ssl
from django.core.management.commands.runserver import Command as RunserverCommand

class Command(RunserverCommand):
    def handle(self, *args, **options):
        # Add SSL context
        certfile = os.path.join('.', 'cert', 'server.crt')
        keyfile = os.path.join('.', 'cert', 'server.key')
        
        options['addrport'] = '0.0.0.0:8000'  # Change port as needed
        options['use_ssl'] = True
        options['ssl_certfile'] = certfile
        options['ssl_keyfile'] = keyfile
        
        super().handle(*args, **options)

# Run this module directly
if __name__ == '__main__':
    import os
    import sys
    
    # Setup environment
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'trading_bot_project.settings')
    
    # Import Django
    import django
    django.setup()
    
    # Run command
    command = Command()
    command.run_from_argv(['manage.py', 'runserver', '--noreload'])
