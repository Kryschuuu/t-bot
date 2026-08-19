import logging
import os
import sys
import threading

from django.apps import AppConfig

logger = logging.getLogger("trading")
_SKIP_AUTOSTART_COMMANDS = {
    "check",
    "collectstatic",
    "createsuperuser",
    "dbshell",
    "makemigrations",
    "migrate",
    "run_scheduled_backtests",
    "shell",
    "showmigrations",
    "test",
}


class TradingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "trading"
    _autostart_scheduled = False

    def ready(self):
        from django.conf import settings

        if not getattr(settings, "AUTOSTART_BOTS", True):
            return
        command = sys.argv[1] if len(sys.argv) > 1 else ""
        if command in _SKIP_AUTOSTART_COMMANDS:
            return
        if command == "runserver" and os.environ.get("RUN_MAIN") != "true":
            return
        if self.__class__._autostart_scheduled:
            return
        self.__class__._autostart_scheduled = True
        # Ein kurzer Delay vermeidet Datenbankzugriffe während der App-Registry-
        # Initialisierung. Anders als das frühere post_migrate-Signal läuft dies
        # auch beim normalen Daphne-Prozessstart auf Render.
        timer = threading.Timer(2, self.start_active_bots)
        timer.daemon = True
        timer.start()

    @staticmethod
    def start_active_bots():
        from django.db import close_old_connections

        from .models import Configuration, ErrorLog
        from .trading_bot import bot_manager

        close_old_connections()
        try:
            for config in Configuration.objects.filter(is_running=True).iterator():
                try:
                    bot_manager.start_bot(config)
                    logger.info("Bot für Konfiguration %s automatisch gestartet", config.id)
                except Exception as exc:
                    logger.exception("Autostart für Konfiguration %s fehlgeschlagen", config.id)
                    ErrorLog.objects.create(
                        configuration=config,
                        source="apps.autostart",
                        message=str(exc)[:4000],
                    )
        except Exception:
            logger.exception("Aktive Bots konnten beim Prozessstart nicht geladen werden")
        finally:
            close_old_connections()
