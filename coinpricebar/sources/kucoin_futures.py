import json
import logging
import time
from urllib.parse import urlencode
from urllib.request import urlopen

from ..config import normalize_symbol
from .base import BasePriceSource

KUCOIN_FUTURES_CONTRACTS_URL = "https://api-futures.kucoin.com/api/v1/contracts/active"
KUCOIN_FUTURES_TICKER_URL = "https://api-futures.kucoin.com/api/v1/ticker"
KUCOIN_FUTURES_POLL_INTERVAL = 10.0


class KucoinFuturesPriceSource(BasePriceSource):
    source_name = "kucoin_futures"
    display_label = "KuCoin Futures"
    home_url = "https://www.kucoin.com/futures"
    local_icon_name = "kucoin.png"
    source_mode = "poll"
    menu_icon_style = {"bg": (0.14, 0.74, 0.63, 1.0), "fg": (1.0, 1.0, 1.0, 1.0), "text": "F"}
    require_image_content_type = True
    retry_icon_download_on_load_failure = True

    @classmethod
    def build_trade_url(cls, symbol: str) -> str | None:
        normalized = normalize_symbol(symbol)
        compact = normalized.replace("-", "")
        return f"https://www.kucoin.com/futures/trade/{compact}" if compact else None

    def __init__(self, update_callback, status_callback):
        super().__init__(update_callback, status_callback)
        self.current_symbols: list[str] = []

    def _fetch_symbol_price(self, symbol: str) -> float:
        query = urlencode({"symbol": symbol})
        with urlopen(f"{KUCOIN_FUTURES_TICKER_URL}?{query}", timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        data = payload.get("data") or {}
        return float(data.get("price") or 0.0)

    def start(self, symbols: list[str]) -> None:
        with self.lock:
            if self.running:
                return
            self.running = True
            self.current_symbols = [normalize_symbol(symbol) for symbol in symbols]

        if not self.current_symbols:
            logging.info("KuCoin Futures 未配置合约交易对，跳过启动")
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
                        if price > 0:
                            self._emit_price(symbol, price)
                    except Exception as e:
                        had_error = True
                        logging.warning(f"获取 KuCoin Futures 行情失败: {symbol} -> {e}")
                self._emit_status("⚫" if had_error else "")
                self._wait_interval(KUCOIN_FUTURES_POLL_INTERVAL)
        finally:
            self.running = False

    def stop(self) -> None:
        with self.lock:
            self.running = False

    def list_symbols(self) -> list[str]:
        try:
            with urlopen(KUCOIN_FUTURES_CONTRACTS_URL, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            items = []
            for contract in payload.get("data", []):
                symbol = normalize_symbol(str(contract.get("symbol", "")))
                if symbol:
                    items.append(symbol)
            return sorted(set(items))
        except Exception as e:
            logging.warning(f"获取 KuCoin Futures 合约列表失败: {e}")
            return []

