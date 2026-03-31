import json
import logging
import traceback

import websocket

from ..config import normalize_symbol
from .base import BasePriceSource

BINANCE_WS_URL = "wss://stream.binance.com:9443/stream?streams={}"


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _binance_stream_name(symbol: str) -> str:
    return normalize_symbol(symbol).replace("-", "").lower() + "@ticker"


class BinancePriceSource(BasePriceSource):
    source_name = "binance"

    def __init__(self, update_callback, status_callback):
        super().__init__(update_callback, status_callback)
        self.ws_app: websocket.WebSocketApp | None = None
        self.current_symbols: list[str] = []

    def _build_url(self, symbols: list[str]) -> str:
        streams = "/".join(_binance_stream_name(symbol) for symbol in symbols)
        return BINANCE_WS_URL.format(streams)

    def _on_open(self, _ws):
        logging.info("Binance WebSocket 已连接")
        self._emit_status("")

    def _on_message(self, _ws, message: str):
        try:
            payload = json.loads(message)
            data = payload.get("data") or payload
            symbol = normalize_symbol(data.get("s", ""))
            if not symbol:
                return
            if "-" not in symbol:
                raw_symbol = str(data.get("s", "")).upper()
                for quote in ("USDT", "BTC", "ETH", "BNB", "FDUSD", "TRY", "EUR"):
                    if raw_symbol.endswith(quote) and len(raw_symbol) > len(quote):
                        symbol = f"{raw_symbol[:-len(quote)]}-{quote}"
                        break
                else:
                    symbol = raw_symbol
            self._emit_price(symbol, _safe_float(data.get("c")))
        except Exception as e:
            logging.error(f"Binance 消息处理失败: {e}\n{traceback.format_exc()}")

    def _on_error(self, _ws, error):
        logging.error(f"Binance WebSocket 错误: {error}")
        self._emit_status("⚫")

    def _on_close(self, _ws, status_code, msg):
        logging.info(f"Binance WebSocket 已关闭: {status_code} {msg}")
        self._emit_status("🟡" if self.running else "⚫")

    def start(self, symbols: list[str]) -> None:
        with self.lock:
            if self.running:
                return
            self.running = True
            self.current_symbols = [normalize_symbol(symbol) for symbol in symbols]

        if not self.current_symbols:
            logging.info("Binance 未配置交易对，跳过启动")
            self.running = False
            return

        self.ws_app = websocket.WebSocketApp(
            self._build_url(self.current_symbols),
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        try:
            self.ws_app.run_forever(ping_interval=15, ping_timeout=5)
        except Exception as e:
            logging.error(f"Binance 监控启动失败: {e}\n{traceback.format_exc()}")
            self._emit_status("⚫")
        finally:
            self.running = False

    def stop(self) -> None:
        with self.lock:
            if not self.running and not self.ws_app:
                return
            self.running = False
        ws = self.ws_app
        self.ws_app = None
        if ws:
            try:
                ws.close()
                logging.info("Binance WebSocket 已请求关闭")
            except Exception as e:
                logging.error(f"停止 Binance WS 失败: {e}\n{traceback.format_exc()}")

