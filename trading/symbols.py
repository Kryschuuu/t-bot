"""Cached symbol catalog used by configuration autocomplete.

Autocomplete is advisory only. ConfigurationForm performs authoritative live
validation before saving, so a stale suggestion can never bypass validation.
"""

import threading
import time

import ccxt

from .market_data import (
    BitMartPublicMarketData,
    BitunixPublicMarketData,
    MarketDataConnectionError,
)

_CACHE = {}
_FAILURE_CACHE = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SECONDS = 15 * 60
_FAILURE_TTL_SECONDS = 60
_QUOTES = ("FDUSD", "USDT", "USDC", "EUR", "BTC", "ETH")
_BINANCE_SPOT = {
    "ADA/USDT",
    "AVAX/USDT",
    "BCH/USDT",
    "BNB/USDT",
    "BTC/USDT",
    "DOGE/USDT",
    "DOT/USDT",
    "ETH/USDT",
    "LINK/USDT",
    "LTC/USDT",
    "NEAR/USDT",
    "PEPE/USDT",
    "SHIB/USDT",
    "SOL/USDT",
    "SUI/USDT",
    "TON/USDT",
    "TRX/USDT",
    "XRP/USDT",
}
_BINANCE_FUTURES = _BINANCE_SPOT | {"1000PEPE/USDT", "1000SHIB/USDT"}


def _canonical(compact):
    compact = str(compact).replace("_", "").replace("-", "").replace("/", "").upper()
    for quote in _QUOTES:
        if compact.endswith(quote) and len(compact) > len(quote):
            return f"{compact[: -len(quote)]}/{quote}"
    return None


def _provider_symbols(provider):
    try:
        compact_symbols = provider.available_symbols()
        return {symbol for compact in compact_symbols if (symbol := _canonical(compact))}
    finally:
        provider.close()


def _load_symbols(exchange_id, market):
    if exchange_id == "binance":
        # Binance market-data WebSockets expose no complete symbol directory.
        # Curated liquid pairs avoid REST request weight; live validation on
        # submit remains authoritative for every manually entered symbol.
        return set(_BINANCE_FUTURES if market == "futures" else _BINANCE_SPOT)
    if exchange_id == "bitmart":
        if market != "spot":
            return set()
        return _provider_symbols(BitMartPublicMarketData(market))
    if exchange_id == "bitunix":
        return _provider_symbols(BitunixPublicMarketData(market))

    exchange_class = getattr(ccxt, exchange_id, None)
    if exchange_class is None:
        return set()
    default_type = "swap" if market == "futures" else "spot"
    exchange = exchange_class(
        {
            "enableRateLimit": True,
            "timeout": 15_000,
            "options": {"defaultType": default_type},
        }
    )
    try:
        markets = exchange.load_markets()
        return {
            symbol
            for symbol, info in markets.items()
            if info.get("active") is not False
            and (info.get("spot") if market == "spot" else info.get("swap"))
        }
    except (ccxt.BaseError, OSError, ValueError) as exc:
        raise MarketDataConnectionError(
            f"Symbolliste von {getattr(exchange, 'name', exchange_id)} nicht verfügbar: {exc}"
        ) from exc
    finally:
        close_method = getattr(exchange, "close", None)
        if close_method:
            close_method()


def get_available_symbols(exchange_id, market):
    exchange_id = exchange_id.strip().lower()
    market = market.strip().lower()
    key = (exchange_id, market)
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]
        failed = _FAILURE_CACHE.get(key)
        if failed and now - failed[0] < _FAILURE_TTL_SECONDS:
            raise MarketDataConnectionError(failed[1])
    try:
        symbols = tuple(sorted(_load_symbols(exchange_id, market)))
    except MarketDataConnectionError as exc:
        with _CACHE_LOCK:
            _FAILURE_CACHE[key] = (now, str(exc))
        raise
    with _CACHE_LOCK:
        _CACHE[key] = (now, symbols)
        _FAILURE_CACHE.pop(key, None)
    return symbols
