import sys
from django.apps import AppConfig
from django.db.models.signals import post_migrate
import logging

logger = logging.getLogger('trading')

# Management-Kommandos, bei denen NIE automatisch Bots gestartet werden
# sollen (z.B. waehrend des Render Build-Schritts "migrate" oder
# "collectstatic" - dort laeuft noch kein Server, der laufende
# Bot-Threads sinnvoll bedienen koennte).
_SKIP_AUTOSTART_COMMANDS = {
    'migrate', 'makemigrations', 'collectstatic', 'shell', 'test',
    'createsuperuser', 'dbshell', 'showmigrations',
}


class TradingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'trading'

    def ready(self):
        super().ready()
        post_migrate.connect(self.start_active_bots, sender=self)

    def start_active_bots(self, sender, **kwargs):
        from django.conf import settings

        if not getattr(settings, 'AUTOSTART_BOTS', True):
            return

        argv_command = sys.argv[1] if len(sys.argv) > 1 else ''
        if argv_command in _SKIP_AUTOSTART_COMMANDS:
            # post_migrate feuert auch, wenn "migrate" explizit im Build-Step
            # aufgerufen wird - hier sollen noch keine Bot-Threads starten.
            return

        from .models import Configuration
        # WICHTIG: Hier die geteilte Singleton-Instanz aus trading_bot.py
        # verwenden (nicht TradingBotManager() neu instanziieren!). Sonst
        # landen die hier gestarteten Bots in einer eigenen, isolierten
        # Registry, die views.py (welches den Singleton importiert) nicht
        # kennt - Start/Stop ueber die UI wuerde dann nicht mehr zu den
        # tatsaechlich laufenden Bot-Threads passen.
        from .trading_bot import bot_manager
        try:
            active_configs = Configuration.objects.filter(is_running=True)
            for config in active_configs:
                bot_manager.start_bot(config)
        except Exception as e:
            logger.error("Fehler beim automatischen Starten der Bots: %s", e)
