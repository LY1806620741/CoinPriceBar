import json
import logging
import os
import threading
import time
import traceback
from urllib.request import urlopen

from kucoin_universal_sdk.api import DefaultClient
from kucoin_universal_sdk.generate.spot.spot_public import SpotPublicWS, TickerEvent
from kucoin_universal_sdk.model import (
    ClientOptionBuilder,
    GLOBAL_API_ENDPOINT,
    GLOBAL_BROKER_API_ENDPOINT,
    GLOBAL_FUTURES_API_ENDPOINT,
    WebSocketClientOptionBuilder,
    WebSocketEvent,
)

from .base import BasePriceSource

KUCOIN_SYMBOLS_URL = "https://api.kucoin.com/api/v2/symbols"

UI_UPDATE_INTERVAL = 0.1
THREAD_JOIN_TIMEOUT = 2


def _dump_threads(tag: str):
    names = [(t.name, t.daemon) for t in threading.enumerate()]
    logging.info(f"[{tag}] Threads: {names}")


class KucoinPriceSource(BasePriceSource):
    source_name = "kucoin"
    local_icon_name = "kucoin.png"

    def __init__(self, update_callback, status_callback):
        super().__init__(update_callback, status_callback)
        self.client: DefaultClient | None = None
        self.spot_ws: SpotPublicWS | None = None
        self.app_status = {
            WebSocketEvent.EVENT_CONNECTED: "",
            WebSocketEvent.EVENT_DISCONNECTED: "⚫",
            WebSocketEvent.EVENT_TRY_RECONNECT: "🟡",
        }

    def _init_client(self) -> bool:
        try:
            client_option = (
                ClientOptionBuilder()
                .set_key(os.getenv("API_KEY", ""))
                .set_secret(os.getenv("API_SECRET", ""))
                .set_passphrase(os.getenv("API_PASSPHRASE", ""))
                .set_websocket_client_option(
                    WebSocketClientOptionBuilder()
                    .with_event_callback(self._ws_event_callback)
                    .build()
                )
                .set_spot_endpoint(GLOBAL_API_ENDPOINT)
                .set_futures_endpoint(GLOBAL_FUTURES_API_ENDPOINT)
                .set_broker_endpoint(GLOBAL_BROKER_API_ENDPOINT)
                .build()
            )
            self.client = DefaultClient(client_option)
            logging.info("KuCoin客户端初始化成功")
            return True
        except Exception as e:
            logging.error(f"KuCoin 客户端初始化失败: {e}\n{traceback.format_exc()}")
            return False

    def _ws_event_callback(self, event_type: WebSocketEvent, msg: str, err: str):
        if event_type in self.app_status:
            logging.info(f"KuCoin WS事件: {event_type} | {msg}")
            try:
                self._emit_status(self.app_status.get(event_type, ""))
            except Exception:
                pass

    def _ticker_callback(self, topic: str, subject: str, data: TickerEvent) -> None:
        try:
            symbol = topic.split(":")[-1]
            price = float(data.price)
            logging.debug(f"KuCoin ticker: {symbol} -> {price}")
            self._emit_price(symbol, price)
        except Exception as e:
            logging.error(f"KuCoin 回调处理失败: {e}\n{traceback.format_exc()}")

    def _start_socket(self, symbols: list[str]) -> None:
        if not self.client:
            raise RuntimeError("KuCoin client not initialized")
        ws_service = self.client.ws_service()
        self.spot_ws = ws_service.new_spot_public_ws()
        self.spot_ws.start()
        logging.info(f"KuCoin 订阅成功，ID: {self.spot_ws.ticker(symbols, self._ticker_callback)}")

    def _wait_until_stopped(self) -> None:
        _dump_threads("KuCoin WS started")
        while self.running:
            time.sleep(UI_UPDATE_INTERVAL)

    def start(self, symbols: list[str]) -> None:
        with self.lock:
            if self.running:
                return
            self.running = True

        if not self.client and not self._init_client():
            self._emit_status("⚫")
            return

        try:
            self._start_socket(symbols)
            self._wait_until_stopped()
        except Exception as e:
            logging.error(f"KuCoin 监控启动失败: {e}\n{traceback.format_exc()}")
            self._emit_status("⚫")

    def stop(self) -> None:
        with self.lock:
            if not self.running:
                return
            self.running = False

        ws = self.spot_ws
        self.spot_ws = None
        if ws:
            try:
                try:
                    if hasattr(ws, "disable_reconnect"):
                        ws.disable_reconnect()
                    elif hasattr(ws, "set_reconnect_attempts"):
                        ws.set_reconnect_attempts(0)
                    elif hasattr(ws, "client_option"):
                        try:
                            ws.client_option.reconnect_attempts = 0
                        except Exception:
                            pass
                except Exception as e:
                    logging.warning(f"KuCoin 关闭重连失败或无此API: {e}")

                def _stop_ws():
                    try:
                        if hasattr(ws, "close"):
                            ws.close()
                        elif hasattr(ws, "shutdown"):
                            ws.shutdown()
                        else:
                            ws.stop()
                    except Exception as inner:
                        logging.error(f"停止 KuCoin WS 失败: {inner}\n{traceback.format_exc()}")

                thread = threading.Thread(target=_stop_ws, daemon=True, name="KuCoin-WS-Stopper")
                thread.start()
                thread.join(timeout=THREAD_JOIN_TIMEOUT)
                if thread.is_alive():
                    logging.warning("KuCoin WebSocket 停止超时，将继续后台收尾")
                else:
                    logging.info("KuCoin WebSocket 已停止")
            except Exception as e:
                logging.error(f"停止 KuCoin WS 异常: {e}\n{traceback.format_exc()}")

        try:
            if self.client and hasattr(self.client, "ws_service"):
                svc = self.client.ws_service()
                if hasattr(svc, "close"):
                    svc.close()
        except Exception as e:
            logging.warning(f"关闭 KuCoin ws_service 失败或无此API: {e}")

    def list_symbols(self) -> list[str]:
        try:
            with urlopen(KUCOIN_SYMBOLS_URL, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            items = []
            for symbol_info in payload.get("data", []):
                if not symbol_info.get("enableTrading", False):
                    continue
                symbol = str(symbol_info.get("symbol", "")).upper().replace("_", "-")
                if symbol:
                    items.append(symbol)
            return sorted(set(items))
        except Exception as e:
            logging.warning(f"获取 KuCoin 交易对列表失败: {e}")
            return []
