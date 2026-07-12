# trading/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer

# WICHTIG: Der Gruppenname muss exakt mit dem Namen uebereinstimmen, an den
# BacktestTask.update_progress() (trading/models.py) sendet:
#   f'backtest_progress_{self.id}'
# Vorher trat der Consumer der Gruppe f"backtest_{self.task_id}" bei - das
# war ein Namens-Mismatch, wodurch KEINE Fortschritts-Nachricht jemals beim
# Client ankam (das WebSocket verband sich, blieb aber stumm).
class BacktestConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.task_id = self.scope['url_route']['kwargs']['task_id']
        self.group_name = f"backtest_progress_{self.task_id}"
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    # Der "type": "backtest.progress" im group_send() wird von Channels
    # automatisch zu dieser Methode "backtest_progress" gemappt.
    async def backtest_progress(self, event):
        await self.send(text_data=json.dumps(event))
