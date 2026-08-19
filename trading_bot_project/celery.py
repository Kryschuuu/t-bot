# trading_bot_project/celery.py
#
# HINWEIS Render Free Tier: Ohne REDIS_URL laeuft Celery im "eager" Modus
# (siehe settings.py) - es gibt dann keinen echten Broker und somit auch
# keinen "celery beat" Prozess, der den unten stehenden beat_schedule
# ausfuehren wuerde (Render Free Tier bietet ohnehin keine Background-
# Worker-/Cron-Instanzen). trading.tasks.schedule_backtests() kann
# stattdessen manuell (Django-Shell/Management-Command) oder ueber einen
# externen Cron-Dienst (z.B. cron-job.org), der einen geschuetzten
# Endpunkt/Management-Command ausloest, periodisch aufgerufen werden.
# Auf einem bezahlten Plan mit Redis + separatem Worker- und Beat-Service
# greift der beat_schedule unten wieder ganz normal.
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", "trading_bot_project.settings"
)  # Ersetze your_project

app = Celery("trading_bot_project")  # Passe den Namen an

app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


app.conf.beat_schedule = {
    "check-scheduled-backtests": {
        "task": "trading.tasks.schedule_backtests",
        #'task': 'tasks.schedule_backtests', # Pfad zu deiner schedule_backtests Task
        "schedule": crontab(),  # Führt jede Minute aus, anpassbar z.B. crontab(minute='*/5') für alle 5 Minuten
    },
}


@app.task(bind=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
