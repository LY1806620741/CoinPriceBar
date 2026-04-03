import json
import logging
import time
from urllib.request import Request, urlopen

from ..config import normalize_symbol
from .base import BasePriceSource

BINANCE_C2C_SEARCH_URL = "https://c2c.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
BINANCE_C2C_SYMBOLS = [
    "USDT-CNY",
    "FDUSD-CNY",
    "BTC-CNY",
    "ETH-CNY",
    "BNB-CNY",
]
BINANCE_C2C_POLL_INTERVAL = 15.0


def _split_c2c_symbol(symbol: str) -> tuple[str, str]:
    normalized = normalize_symbol(symbol)
    parts = normalized.split("-", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return normalized, "CNY"


class BinanceC2CPriceSource(BasePriceSource):
    source_name = "binance_c2c"
    display_label = "Binance C2C"
    home_url = "https://p2p.binance.com/"
    local_icon_name = "binance.ico"
    source_mode = "poll"
    menu_icon_style = {"bg": (0.95, 0.71, 0.09, 1.0), "fg": (0.1, 0.1, 0.1, 1.0), "text": "C"}

    @classmethod
    def build_trade_url(cls, symbol: str) -> str | None:
        asset, fiat = _split_c2c_symbol(symbol)
        if not asset or not fiat:
            return None
        return f"https://p2p.binance.com/trade/sell/{asset}?fiat={fiat}&payment=all-payments"

    def __init__(self, update_callback, status_callback):
        super().__init__(update_callback, status_callback)
        self.current_symbols: list[str] = []

    def _fetch_symbol_price(self, symbol: str) -> float:
        asset, fiat = _split_c2c_symbol(symbol)
        payload = {
            "page": 1,
            "rows": 1,
            "payTypes": [],
            "countries": [],
            "proMerchantAds": False,
            "publisherType": None,
            "asset": asset,
            "fiat": fiat,
            "tradeType": "SELL",
        }
        request = Request(
            BINANCE_C2C_SEARCH_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0",
            },
            method="POST",
        )
        with urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
        first_item = (result.get("data") or [None])[0] or {}
        adv = first_item.get("adv") or {}
        return float(adv.get("price") or 0.0)

    def start(self, symbols: list[str]) -> None:
        with self.lock:
            if self.running:
                return
            self.running = True
            self.current_symbols = [normalize_symbol(symbol) for symbol in symbols]

        if not self.current_symbols:
            logging.info("Binance C2C 未配置汇率对，跳过启动")
            self.running = False
            return

        self._emit_status("")
        try:
            while self.running:
                had_error = False
                for symbol in self.current_symbols:
                    if not self.running:
                        break
                    try:
                        price = self._fetch_symbol_price(symbol)
                        logging.debug(f"Binance C2C ticker: {symbol} -> {price}")
                        if price > 0:
                            self._emit_price(symbol, price)
                    except Exception as e:
                        had_error = True
                        logging.warning(f"获取 Binance C2C 汇率失败: {symbol} -> {e}")
                self._emit_status("⚫" if had_error else "")
                self._wait_interval(BINANCE_C2C_POLL_INTERVAL)
        finally:
            self.running = False

    def stop(self) -> None:
        with self.lock:
            self.running = False

    def list_symbols(self) -> list[str]:
        return list(BINANCE_C2C_SYMBOLS)

