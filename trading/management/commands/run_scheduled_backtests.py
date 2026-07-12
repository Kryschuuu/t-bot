from django.core.management.base import BaseCommand
from trading.tasks import schedule_backtests


class Command(BaseCommand):
    """Fuehrt trading.tasks.schedule_backtests() einmalig direkt aus.

    Ersatz fuer celery beat, das auf dem Render Free Tier nicht verfuegbar
    ist (kein kostenloser Background-Worker-/Cron-Job-Service-Typ). Dieser
    Command kann z.B. von einem externen Cron-Dienst wie cron-job.org
    regelmaessig ueber einen geschuetzten Trigger, oder manuell/per Render
    Shell aufgerufen werden:

        python manage.py run_scheduled_backtests

    Sucht nach BacktestTask-Eintraegen mit status='scheduled', deren
    geplante Startzeit erreicht ist, und startet sie (siehe trading/tasks.py).
    """

    help = "Startet faellige geplante Backtests (Ersatz fuer celery beat)."

    def handle(self, *args, **options):
        self.stdout.write("Pruefe auf faellige geplante Backtests ...")
        schedule_backtests()
        self.stdout.write(self.style.SUCCESS("Fertig."))
