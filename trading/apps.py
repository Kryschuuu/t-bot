from django.apps import AppConfig
from django.db.models.signals import post_migrate
import logging

logger = logging.getLogger('trading')

class TradingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'trading'

    def ready(self):
        super().ready()
        post_migrate.connect(self.start_active_bots, sender=self)

    def start_active_bots(self, sender, **kwargs):
        from .models import Configuration
        from .trading_bot import TradingBotManager
        bot_manager = TradingBotManager()
        try:
            active_configs = Configuration.objects.filter(is_running=True)
            for config in active_configs:
                bot_manager.start_bot(config)
        except Exception as e:
            logger.error("Fehler beim automatischen Starten der Bots: %s", e)
