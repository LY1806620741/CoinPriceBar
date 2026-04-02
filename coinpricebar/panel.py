import json
import logging
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from .config import (
    AppConfig,
    DEFAULT_CONFIG_PATH,
    EXCHANGE_ICON_PRESETS,
    FORMAT_PRESETS,
    ICON_STYLE_OPTIONS,
    OFFICIAL_EXCHANGE_ICON_URLS,
    PERFORMANCE_PRESETS,
    SUPPORTED_EXCHANGES,
    SUPPORTED_LANGUAGES,
    TEMPLATE_EXAMPLES,
    TEMPLATE_VARIABLE_GROUPS,
    TEMPLATE_VARIABLES,
    TickerConfig,
)
from .sources import BinancePriceSource, KucoinPriceSource


PANEL_HTML_PATH = Path(__file__).with_name("panel.html")
STATIC_DIR = Path(__file__).with_name("static")


class ConfigPanelServer:
    def __init__(
        self,
        get_config: Callable[[], AppConfig],
        get_tickers: Callable[[], list[TickerConfig]],
        save_config: Callable[[dict], AppConfig],
    ):
        self.get_config = get_config
        self.get_tickers = get_tickers
        self.save_config = save_config
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.port: int | None = None
        self.symbol_cache: dict[str, tuple[float, list[str]]] = {}
        self.symbol_cache_ttl = 300.0

    def _get_symbol_provider(self, exchange: str):
        return {
            "kucoin": KucoinPriceSource,
            "binance": BinancePriceSource,
        }.get(exchange.lower())

    def _list_symbols(self, exchange: str) -> list[str]:
        exchange = exchange.lower()
        now = time.monotonic()
        cached = self.symbol_cache.get(exchange)
        if cached and now - cached[0] < self.symbol_cache_ttl:
            return cached[1]
        provider = self._get_symbol_provider(exchange)
        if not provider:
            return []
        try:
            symbols = provider(lambda *_: None, lambda *_: None).list_symbols()
        except Exception as e:
            logging.warning(f"获取 {exchange} 交易对列表失败: {e}")
            symbols = []
        self.symbol_cache[exchange] = (now, symbols)
        return symbols

    def start(self) -> None:
        if self.httpd:
            return
        server = self

        class Handler(BaseHTTPRequestHandler):
            def _send_json(self, payload: dict, status: int = 200):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_html(self, content: str):
                body = content.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_file(self, path: Path, content_type: str):
                body = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path in {"/", "/index.html"}:
                    self._send_html(server._build_html())
                    return
                if parsed.path == "/assets/Sortable.min.js":
                    asset_path = STATIC_DIR / "Sortable.min.js"
                    if asset_path.exists():
                        self._send_file(asset_path, "application/javascript; charset=utf-8")
                        return
                    self._send_json({"error": "Not found"}, status=404)
                    return
                if parsed.path == "/api/config":
                    self._send_json(server._serialize_state())
                    return
                if parsed.path == "/api/symbols":
                    exchange = parse_qs(parsed.query).get("exchange", [""])[0]
                    self._send_json({"exchange": exchange, "symbols": server._list_symbols(exchange)})
                    return
                self._send_json({"error": "Not found"}, status=404)

            def do_POST(self):
                if self.path != "/api/config":
                    self._send_json({"error": "Not found"}, status=404)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                try:
                    payload = json.loads(raw)
                    config = server.save_config(payload)
                    self._send_json({"ok": True, "config": server._serialize_config(config)})
                except Exception as e:
                    logging.error(f"保存 UI 配置失败: {e}")
                    self._send_json({"ok": False, "error": str(e)}, status=400)

            def log_message(self, format, *args):
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="ConfigPanelServer")
        self.thread.start()
        logging.info(f"UI 配置面板已启动: http://127.0.0.1:{self.port}")

    def stop(self) -> None:
        if not self.httpd:
            return
        self.httpd.shutdown()
        self.httpd.server_close()
        self.httpd = None
        self.port = None

    def open(self) -> None:
        self.start()
        webbrowser.open_new_tab(f"http://127.0.0.1:{self.port}")

    def _serialize_config(self, config: AppConfig) -> dict:
        from .config import _serialize_default_config
        return _serialize_default_config(config)

    def _serialize_state(self) -> dict:
        config = self.get_config()
        tickers = self.get_tickers()
        prefs = config.ticker_preferences
        items = []
        for index, ticker in enumerate(tickers):
            pref = prefs.get(ticker.key.lower()) or prefs.get(ticker.key)
            items.append(
                {
                    "key": ticker.key,
                    "exchange": ticker.exchange,
                    "symbol": ticker.symbol,
                    "display_name": ticker.display_name,
                    "enabled": ticker.enabled,
                    "visible": True if pref is None else pref.visible,
                    "order": index,
                    "pinned_title": False if pref is None else pref.pinned_title,
                }
            )
        return {
            "config": self._serialize_config(config),
            "tickers": items,
            "configPath": str(DEFAULT_CONFIG_PATH),
            "performancePresets": PERFORMANCE_PRESETS,
            "formatPresets": FORMAT_PRESETS,
            "templateExamples": list(TEMPLATE_EXAMPLES),
            "templateVariableGroups": list(TEMPLATE_VARIABLE_GROUPS),
            "templateVariables": list(TEMPLATE_VARIABLES),
            "iconStyleOptions": dict(ICON_STYLE_OPTIONS),
            "iconPresets": EXCHANGE_ICON_PRESETS,
            "officialExchangeIconUrls": OFFICIAL_EXCHANGE_ICON_URLS,
            "languages": sorted(SUPPORTED_LANGUAGES),
            "exchanges": SUPPORTED_EXCHANGES,
            "exchangeShortNames": config.exchange_short_names,
        }

    def _build_html(self) -> str:
        return PANEL_HTML_PATH.read_text(encoding="utf-8")
