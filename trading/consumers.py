from channels.generic.websocket import AsyncWebsocketConsumer
import json

class BacktestConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.task_id = self.scope['url_route']['kwargs']['task_id']
        await self.channel_layer.group_add(f"backtest_{self.task_id}", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(f"backtest_{self.task_id}", self.channel_name)

    async def receive(self, text_data):
        await self.send(text_data=json.dumps({'message': 'connected'}))

    async def backtest_update(self, event):
        await self.send(text_data=json.dumps(event['data']))
