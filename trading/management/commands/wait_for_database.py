import random
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import OperationalError, close_old_connections, connection
from django.db.utils import InterfaceError


class Command(BaseCommand):
    help = "Wartet mit Backoff, bis die konfigurierte Datenbank erreichbar ist."

    def add_arguments(self, parser):
        parser.add_argument(
            "--attempts",
            type=int,
            default=settings.DB_RECONNECT_MAX_RETRIES + 1,
        )

    def handle(self, *args, **options):
        attempts = max(1, options["attempts"])
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                close_old_connections()
                connection.ensure_connection()
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
                self.stdout.write(self.style.SUCCESS("Datenbank ist erreichbar."))
                return
            except (OperationalError, InterfaceError) as exc:
                last_error = exc
                try:
                    connection.close()
                except Exception as close_error:
                    self.stderr.write(
                        f"Defekte DB-Verbindung konnte nicht geschlossen werden: {close_error}"
                    )
                if attempt >= attempts:
                    break
                dns_failure = "could not translate host name" in str(exc).lower()
                delay = min(
                    settings.DB_RECONNECT_MAX_DELAY,
                    settings.DB_RECONNECT_BASE_DELAY * (2 ** (attempt - 1)),
                )
                if dns_failure:
                    delay = max(5, delay)
                delay += random.uniform(0, delay * 0.25)
                self.stdout.write(
                    self.style.WARNING(
                        f"Datenbank nicht erreichbar (DNS={dns_failure}, "
                        f"Versuch {attempt}/{attempts}); neuer Versuch in {delay:.1f}s."
                    )
                )
                time.sleep(delay)
        raise CommandError(
            f"Datenbank nach {attempts} Versuchen nicht erreichbar: "
            f"{type(last_error).__name__}: {last_error}"
        )
