import json
import logging
import time
from urllib.request import urlopen

from ..config import normalize_symbol
from .base import BasePriceSource

BINANCE_FUTURES_EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
BINANCE_FUTURES_TICKER_URL = "https://fapi.binance.com/fapi/v1/ticker/price"
BINANCE_FUTURES_POLL_INTERVAL = 10.0


def _to_binance_futures_api_symbol(symbol: str) -> str:
    return normalize_symbol(symbol).replace("-", "")


class BinanceFuturesPriceSource(BasePriceSource):
    source_name = "binance_futures"
    display_label = "Binance Futures"
    home_url = "https://www.binance.com/en/futures/home"
    local_icon_name = "binance.ico"
    source_mode = "poll"
    menu_icon_style = {"bg": (0.95, 0.71, 0.09, 1.0), "fg": (0.1, 0.1, 0.1, 1.0), "text": "F"}

    @classmethod
    def build_trade_url(cls, symbol: str) -> str | None:
        normalized = normalize_symbol(symbol)
        base, _, quote = normalized.partition("-")
        if not base or not quote:
            return None
        return f"https://www.binance.com/futures/{base}{quote}"

    def __init__(self, update_callback, status_callback):
        super().__init__(update_callback, status_callback)
        self.current_symbols: list[str] = []

    def _fetch_all_prices(self) -> dict[str, float]:
        with urlopen(BINANCE_FUTURES_TICKER_URL, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        prices: dict[str, float] = {}
        for item in payload:
            raw_symbol = str(item.get("symbol", "")).upper()
            if not raw_symbol:
                continue
            price = float(item.get("price") or 0.0)
            prices[raw_symbol] = price
        return prices

    def start(self, symbols: list[str]) -> None:
        with self.lock:
            if self.running:
                return
            self.running = True
            self.current_symbols = [normalize_symbol(symbol) for symbol in symbols]

        if not self.current_symbols:
            logging.info("Binance Futures 未配置合约交易对，跳过启动")
            self.running = False
            return

        self._emit_status("")
        try:
            while self.running:
                try:
                    prices = self._fetch_all_prices()
                    for symbol in self.current_symbols:
                        api_symbol = _to_binance_futures_api_symbol(symbol)
                        price = prices.get(api_symbol)
                        if price is not None and price > 0:
                            self._emit_price(symbol, price)
                    self._emit_status("")
                except Exception as e:
                    logging.warning(f"获取 Binance Futures 行情失败: {e}")
                    self._emit_status("⚫")
                self._wait_interval(BINANCE_FUTURES_POLL_INTERVAL)
        finally:
            self.running = False

    def stop(self) -> None:
        with self.lock:
            self.running = False

    def list_symbols(self) -> list[str]:
        try:
            with urlopen(BINANCE_FUTURES_EXCHANGE_INFO_URL, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            items = []
            for symbol_info in payload.get("symbols", []):
                if symbol_info.get("status") != "TRADING":
                    continue
                if symbol_info.get("contractType") not in {"PERPETUAL", "CURRENT_QUARTER", "NEXT_QUARTER"}:
                    continue
                base = str(symbol_info.get("baseAsset", "")).upper()
                quote = str(symbol_info.get("quoteAsset", "")).upper()
                if base and quote:
                    items.append(f"{base}-{quote}")
            return sorted(set(items))
        except Exception as e:
            logging.warning(f"获取 Binance Futures 交易对列表失败: {e}")
            return []

