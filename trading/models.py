from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal
from django.utils import timezone
from celery.result import AsyncResult
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.exceptions import ObjectDoesNotExist
import logging

# Logging konfigurieren
logger = logging.getLogger(__name__)

class Configuration(models.Model):

    is_running = models.BooleanField(
        default=False,
        help_text="Gibt an, ob der Bot aktuell läuft"
    )

    MARKET_CHOICES = (
        ("spot", "Spot"),
        ("futures", "Futures"),
    )

    name = models.CharField(max_length=100)

    market = models.CharField(
        max_length=20,
        choices=MARKET_CHOICES,
        default="spot"
    )

    sales_stop_threshold = models.FloatField(
        default=0.0,
        help_text="Prozentualer Verlust, ab dem verkauft wird"
    )

    countdown_reset_indicators = models.BooleanField(
        default=False,
        help_text="Indikatoren nach Trade zurücksetzen"
    )
    EXCHANGE_CHOICES = (
        ("binance", "Binance"),
        ("bingx", "BingX"),
        ("bybit", "Bybit"),
        ("bitmart", "Bitmart"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    exchange = models.CharField(max_length=20, choices=EXCHANGE_CHOICES, default='binance')
    symbols = models.CharField(max_length=200, default='BTC/USDT,ETH/USDT,SOL/USDT,KAITO/USDT,LTC/USDT,XRP/USDT')

    start_capital = models.DecimalField(max_digits=20, decimal_places=8, default=Decimal("100"))
    trade_amount = models.DecimalField(max_digits=20, decimal_places=8, default=Decimal("10"))

    take_profit = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal("0.5"))
    stop_loss = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal("0.5"))
    fee = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal("0.1"))

    api_key = models.CharField(max_length=120, blank=True, null=True)
    secret_key = models.CharField(max_length=120, blank=True, null=True)

    countdown = models.IntegerField(default=1)
    time_interval = models.IntegerField(default=2)

    div_DVA_prev_NDA_threshold_buy = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    deltadelta_threshold_buy = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    nda_threshold_buy = models.DecimalField(max_digits=20, decimal_places=8, default=0)

    def __str__(self):
        return f"Config {self.id}"


class ErrorLog(models.Model):
    """Persistente Fehler-Log-Eintraege, unabhaengig von Render's kurzlebigen
    Log-Streams. Wird von trading_bot.py und views.py bei Fehlern befuellt.
    """
    configuration = models.ForeignKey(
        Configuration, on_delete=models.CASCADE,
        related_name="error_logs", null=True, blank=True
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=100, help_text="z.B. 'trading_bot.main_loop', 'config_activate'")
    message = models.TextField()

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.timestamp} [{self.source}] {self.message[:80]}"


class TradingLog(models.Model):
    configuration = models.ForeignKey(Configuration, on_delete=models.CASCADE, related_name="logs")
    timestamp = models.DateTimeField(auto_now_add=True)

    symbol = models.CharField(max_length=30)
    action = models.CharField(max_length=10)

    price = models.DecimalField(max_digits=20, decimal_places=8)
    amount = models.DecimalField(max_digits=20, decimal_places=8)
    fee_amount = models.DecimalField(max_digits=20, decimal_places=8)

    pl_nominal = models.DecimalField(max_digits=20, decimal_places=8)
    pl_relative = models.DecimalField(max_digits=20, decimal_places=8)
    total_pl = models.DecimalField(max_digits=20, decimal_places=8)

    current_capital = models.DecimalField(max_digits=20, decimal_places=8)
    tank = models.DecimalField(max_digits=20, decimal_places=8)

    order_id = models.CharField(max_length=120)

    def __str__(self):
        return f"{self.timestamp} {self.symbol} {self.action}"


class DataLog(models.Model):
    configuration = models.ForeignKey(Configuration, on_delete=models.CASCADE, related_name="data_logs")
    symbol = models.CharField(max_length=30)
    timestamp = models.DateTimeField(auto_now_add=True)

    price = models.DecimalField(max_digits=20, decimal_places=8)
    max_price = models.DecimalField(max_digits=20, decimal_places=8)
    min_price = models.DecimalField(max_digits=20, decimal_places=8)

    current_da = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    nda = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    prev_da = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    prev_nda = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    dva = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    deltadelta = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    div_DVA_prev_NDA = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    mvd = models.DecimalField(max_digits=20, decimal_places=8, default=Decimal("0"))

    class Meta:
        indexes = [
            models.Index(fields=["configuration", "symbol", "timestamp"]),
        ]

    def __str__(self):
        return f"{self.timestamp} {self.symbol}"


class BacktestTask(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('scheduled', 'Scheduled'), # Neu: Geplant
        ('running', 'Running'),
        ('paused', 'Paused'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    )
    configuration = models.ForeignKey(Configuration, on_delete=models.CASCADE)
    symbol = models.CharField(max_length=80)
    status = models.CharField(max_length=40, choices=STATUS_CHOICES, default='pending')
    progress = models.IntegerField(default=0)
    result = models.JSONField(null=True, blank=True)
    celery_task_id = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    parameters = models.JSONField(null=True, blank=True)  # Für die Parameter-Speicherung
    completed_at = models.DateTimeField(null=True, blank=True)
    scheduled_start_time = models.DateTimeField(null=True, blank=True) # Neu: Geplante Startzeit
    is_scheduled = models.BooleanField(default=False) # Neu: Ist der Task geplant?

    def save(self, *args, **kwargs):
        if self.status == 'completed' and not self.completed_at:
            self.completed_at = timezone.now()
        super().save(*args, **kwargs)

    def pause(self):
        if self.status == 'running':
            self.status = 'paused'
            self.save()

    def resume(self):
        if self.status == 'paused':
            self.status = 'running'
            self.save()

    def cancel(self):
        if self.status in ['scheduled', 'running', 'paused', 'pending']: # Geplante Tasks können auch abgebrochen werden
            if self.celery_task_id:
                celery_task = AsyncResult(self.celery_task_id)
                celery_task.revoke(terminate=True)  # Abbruch des Celery Tasks, falls er schon läuft oder pending ist
            self.status = 'cancelled'
            self.save()

    def update_progress(self, progress_percentage):
        """
        Aktualisiert den Fortschritt des BacktestTask in der Datenbank und sendet eine Nachricht über Django Channels.
        Methode direkt im BacktestTask Model.
        """
        try:
            self.progress = progress_percentage
            self.save()

            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'backtest_progress_{self.id}', {
                    'type': 'backtest.progress',
                    'progress': progress_percentage,
                    'task_id': self.id
                }
            )
            if progress_percentage == 3 or progress_percentage == 50 or progress_percentage == 99:
                logger.info(f'Fortschritt für Task {self.id} aktualisiert: {progress_percentage}%')

        except ObjectDoesNotExist:
            logger.error(f'BacktestTask {self.id} nicht gefunden beim Fortschritts-Update')
        except Exception as e:
            logger.error(f'Fehler beim Fortschritts-Update für Task {self.id}: {e}', exc_info=True)
