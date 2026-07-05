# trading/bot_manager.py
from django.utils import timezone

BOT_STATE = {
    "running": False,
    "config_id": None,
    "started_at": None,
}

def start_bot(config_id):
    BOT_STATE["running"] = True
    BOT_STATE["config_id"] = config_id
    BOT_STATE["started_at"] = timezone.now()

def stop_bot():
    BOT_STATE["running"] = False
    BOT_STATE["config_id"] = None
    BOT_STATE["started_at"] = None

def get_status():
    return BOT_STATE.copy()
