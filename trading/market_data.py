import json

import requests


class MarketDataError(RuntimeError):
    pass


def _base_symbol(symbol):
    return symbol.split(":", 1)[0]


def _compact_symbol(symbol):
    return _base_symbol(symbol).replace("/", "").upper()


def _bitmart_symbol(symbol):
    return _base_symbol(symbol).replace("/", "_").upper()


class PublicHTTPMarketData:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "t-bot-paper-trading/1.0"})

    def _json(self, url, **kwargs):
        response = self.session.get(url, timeout=15, **kwargs)
        if response.status_code in {418, 429}:
            raise MarketDataError(
                f"Rate-Limit {response.status_code} von {response.url}: {response.text[:300]}"
            )
        try:
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise MarketDataError(f"Marktdaten-Anfrage fehlgeschlagen: {exc}") from exc
        return payload

    def close(self):
        self.session.close()


class BinancePublicMarketData(PublicHTTPMarketData):
    """Preis-Adapter für Binances getrennten, öffentlichen Marktdaten-Endpunkt.

    Der normale api.binance.com-Endpunkt teilt auf Cloud-Plattformen häufig
    IP-Rate-Limits mit vielen Nutzern. Ein Batch-Request ersetzt außerdem je
    Zyklus N einzelne fetch_ticker-Aufrufe durch genau einen Request.
    """

    def __init__(self, market):
        super().__init__()
        self.market = market
        self.base_url = (
            "https://fapi.binance.com/fapi/v1"
            if market == "futures"
            else "https://data-api.binance.vision/api/v3"
        )

    def fetch_tickers(self, symbols):
        compact_to_symbol = {_compact_symbol(symbol): symbol for symbol in symbols}
        params = {}
        if self.market == "spot":
            params["symbols"] = json.dumps(
                list(compact_to_symbol),
                separators=(",", ":"),
            )
        payload = self._json(f"{self.base_url}/ticker/price", params=params)
        if isinstance(payload, dict):
            payload = [payload]
        prices = {}
        for row in payload:
            original = compact_to_symbol.get(str(row.get("symbol", "")).upper())
            if original and row.get("price") is not None:
                prices[original] = {"last": row["price"]}
        return prices


class BitMartPublicMarketData(PublicHTTPMarketData):
    """Ersatz für den in CCXT 4.5 entfernten BitMart-Adapter (Spot-Marktdaten)."""

    base_url = "https://api-cloud.bitmart.com/spot/quotation/v3/ticker"

    def __init__(self, market):
        if market != "spot":
            raise ValueError(
                "BitMart Futures wird vom aktuellen Marktdaten-Adapter nicht unterstützt; "
                "bitte Spot oder eine andere Exchange wählen."
            )
        super().__init__()

    def fetch_tickers(self, symbols):
        prices = {}
        for symbol in symbols:
            payload = self._json(
                self.base_url,
                params={"symbol": _bitmart_symbol(symbol)},
            )
            if payload.get("code") != 1000:
                raise MarketDataError(
                    f"BitMart-Fehler {payload.get('code')}: {payload.get('message', payload)}"
                )
            data = payload.get("data") or {}
            last = data.get("last") or data.get("last_price")
            if last is None:
                raise MarketDataError(f"BitMart lieferte keinen Preis für {symbol}")
            prices[symbol] = {"last": last}
        return prices
