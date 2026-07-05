# trading/routing.py
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/backtest/(?P<task_id>\d+)/$', consumers.BacktestConsumer.as_asgi()),
]
