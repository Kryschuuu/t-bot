import ccxt
import asyncio
import threading
import logging
import time
from decimal import Decimal, ROUND_HALF_UP

from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction

from .models import Configuration, DataLog, TradingLog

logger = logging.getLogger("trading")


# =========================================================
# DB-HILFSFUNKTIONEN (ASYNC-SAFE)
# =========================================================

@sync_to_async
def db_get_config(config_id):
    return Configuration.objects.get(id=config_id)


@sync_to_async
def db_create_datalog_safe(**kwargs):
    try:
        with transaction.atomic():
            DataLog.objects.create(**kwargs)
    except IntegrityError:
        # Duplicate → ignorieren, NICHT crashen
        pass


@sync_to_async
def db_create_tradinglog_safe(**kwargs):
    try:
        with transaction.atomic():
            TradingLog.objects.create(**kwargs)
    except IntegrityError:
        pass


@sync_to_async
def db_get_recent_deltadelta(symbol, config_id, limit=10):
    return list(
        DataLog.objects.filter(
            configuration_id=config_id,
            symbol=symbol
        ).order_by("-timestamp")[:limit]
    )


# =========================================================
# TRADING BOT
# =========================================================

class TradingBot(threading.Thread):

    def __init__(self, config: Configuration):
        super().__init__(daemon=True)

        self.config_id = config.id
        self.config = config
        self.running = True

        self.symbols = [s.strip() for s in config.symbols.split(",")]
        self.price_buffer = {s: [] for s in self.symbols}
        self.positions = {}

        # Sichtbarkeit fuer die UI/API (siehe bot_status_api): ohne das
        # war ein dauerhaft scheiternder fetch_ticker() (z.B. Binance
        # blockiert die Region/IP von Render mit HTTP 451) fuer den Nutzer
        # komplett unsichtbar - der Bot "lief", aber es gab weder Fehler
        # noch Daten irgendwo sichtbar außer im Server-Log.
        self.last_error = None
        self.last_error_at = None
        self.last_success_at = None
        self.started_at = time.time()

        self.loop = asyncio.new_event_loop()
        self.exchange = self._setup_exchange()

        self.start_time = time.time() + config.countdown * 60
        self.start_countdown_over = False

    # -----------------------------------------------------

    def _setup_exchange(self):
        exchange_cls = getattr(ccxt, self.config.exchange)
        params = {"enableRateLimit": True}

        if self.config.api_key and self.config.secret_key:
            params["apiKey"] = self.config.api_key
            params["secret"] = self.config.secret_key

        return exchange_cls(params)

    # -----------------------------------------------------

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.main_loop())

    def stop(self):
        self.running = False

    # =====================================================
    # MAIN LOOP
    # =====================================================

    async def main_loop(self):
        while self.running:
            try:
                self.config = await db_get_config(self.config_id)

                results = await asyncio.gather(
                    *(self.process_symbol(s) for s in self.symbols),
                    return_exceptions=True
                )

                any_success = False
                for sym, res in zip(self.symbols, results):
                    if isinstance(res, Exception):
                        logger.error(f"{sym} Fehler: {res}")
                        self.last_error = f"{sym}: {res}"
                        self.last_error_at = time.time()
                    else:
                        any_success = True

                if any_success:
                    self.last_success_at = time.time()

                await asyncio.sleep(self.config.time_interval)

            except Exception as e:
                logger.exception(f"Main Loop Error: {e}")
                self.last_error = f"main_loop: {e}"
                self.last_error_at = time.time()
                await asyncio.sleep(2)

    # =====================================================
    # SYMBOL PIPELINE
    # =====================================================

    async def process_symbol(self, symbol):
        await self.fetch_price(symbol)
        await self.calculate_and_store(symbol)

    # -----------------------------------------------------

    async def fetch_price(self, symbol):
        ticker = await self.loop.run_in_executor(
            None, self.exchange.fetch_ticker, symbol
        )

        price = Decimal(str(ticker["last"]))
        buf = self.price_buffer[symbol]
        buf.append(price)

        if len(buf) > 10:
            buf.pop(0)

    # =====================================================
    # INDICATORS
    # =====================================================

    async def calculate_and_store(self, symbol):
        prices = self.price_buffer[symbol]
        if len(prices) < 3:
            return

        p0, p1, p2 = prices[-1], prices[-2], prices[-3]

        da = p0 - p1
        nda = (da / p1 * 100) if p1 else Decimal(0)

        prev_da = p1 - p2
        prev_nda = (prev_da / p1 * 100) if p1 else Decimal(0)

        dva = nda - prev_nda
        deltadelta = (nda + prev_nda) / 2
        div_dva = (dva / prev_nda) if prev_nda else Decimal(0)

        max_price = max(prices)
        min_price = min(prices)
        mvd = min_price / max_price if max_price else Decimal(0)

        await db_create_datalog_safe(
            configuration_id=self.config_id,
            symbol=symbol,
            price=p0,
            max_price=max_price,
            min_price=min_price,
            current_da=da,
            nda=nda,
            prev_da=prev_da,
            prev_nda=prev_nda,
            dva=dva,
            deltadelta=deltadelta,
            div_DVA_prev_NDA=div_dva,
            mvd=mvd
        )

        await self.check_trading(symbol, p0, nda, deltadelta, div_dva)

    # =====================================================
    # TRADING LOGIC
    # =====================================================

    async def check_trading(self, symbol, price, nda, deltadelta, div_dva):

        # Countdown
        if not self.start_countdown_over:
            if time.time() >= self.start_time:
                self.start_countdown_over = True
            return

        # SELL
        if symbol in self.positions:
            entry = self.positions[symbol]["price"]
            pl_pct = (price - entry) / entry * 100

            if pl_pct >= self.config.take_profit or pl_pct <= -self.config.stop_loss:
                await self.execute_trade(symbol, "sell")
                return

        # BUY
        if (
            symbol not in self.positions
            and nda > self.config.nda_threshold_buy
            and deltadelta > self.config.deltadelta_threshold_buy
            and div_dva > self.config.div_DVA_prev_NDA_threshold_buy
        ):
            await self.execute_trade(symbol, "buy")

    # =====================================================
    # ORDER EXECUTION
    # =====================================================

    async def execute_trade(self, symbol, side):
        price = self.price_buffer[symbol][-1]
        amount = (self.config.trade_amount / price).quantize(
            Decimal("1e-8"), rounding=ROUND_HALF_UP
        )

        fee = amount * price * self.config.fee / 100
        pl_nominal = Decimal(0)

        if side == "sell":
            entry = self.positions.pop(symbol)
            pl_nominal = (price - entry["price"]) * amount - fee

        await db_create_tradinglog_safe(
            configuration_id=self.config_id,
            symbol=symbol,
            action=side,
            price=price,
            amount=amount,
            fee_amount=fee,
            pl_nominal=pl_nominal,
            pl_relative=(pl_nominal / (price * amount) * 100) if price * amount else Decimal(0),
            total_pl=pl_nominal,
            current_capital=Decimal(0),
            tank=pl_nominal,
            order_id=f"sim_{side}_{time.time()}"
        )

        if side == "buy":
            self.positions[symbol] = {"price": price}


# =========================================================
# BOT MANAGER
# =========================================================

class TradingBotManager:
    def __init__(self):
        self.bots = {}

    def is_running(self, config_id):
        return config_id in self.bots

    def start_bot(self, config):
        if config.id in self.bots:
            return  # 🛑 läuft schon

        bot = TradingBot(config)
        bot.start()
        self.bots[config.id] = bot

    def stop_bot(self, config):
        bot = self.bots.pop(config.id, None)
        if bot:
            bot.stop()
            bot.join()

    def status(self, config_id):
        """Echter, pro-Konfiguration abrufbarer Bot-Status (fuer bot_status_api).

        Ersetzt das frühere globale, nie aktualisierte BOT_STATE-Dict aus
        trading/bot_manager.py (siehe Debugging-Protokoll, Fehler "Bot: STOPPED").
        """
        bot = self.bots.get(config_id)
        if not bot:
            return {
                "running": False,
                "config_id": config_id,
                "started_at": None,
                "last_error": None,
                "last_error_at": None,
                "last_success_at": None,
            }
        return {
            "running": bot.is_alive(),
            "config_id": config_id,
            "started_at": bot.started_at,
            "last_error": bot.last_error,
            "last_error_at": bot.last_error_at,
            "last_success_at": bot.last_success_at,
        }


bot_manager = TradingBotManager()
