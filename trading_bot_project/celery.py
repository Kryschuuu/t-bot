# trading_bot_project/celery.py
from celery import Celery
from celery.schedules import crontab
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'trading_bot_project.settings') # Ersetze your_project

app = Celery('trading_bot_project') # Passe den Namen an

app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()


app.conf.beat_schedule = {
    'check-scheduled-backtests': {
        'task': 'trading.tasks.schedule_backtests',
        #'task': 'tasks.schedule_backtests', # Pfad zu deiner schedule_backtests Task
        'schedule': crontab(), # Führt jede Minute aus, anpassbar z.B. crontab(minute='*/5') für alle 5 Minuten
    },
}


@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
