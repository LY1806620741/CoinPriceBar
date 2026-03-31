import logging
import os
import queue
import threading
import time
import traceback
import webbrowser
from typing import Dict

import rumps
from AppKit import NSApp
from Foundation import NSObject

from .config import AppConfig, DEFAULT_CONFIG_PATH, TickerConfig, UITickerPreference, get_default_tickers, load_app_config, normalize_symbol
from .panel import ConfigPanelServer
from .sources import BasePriceSource, BinancePriceSource, KucoinPriceSource, MarketSnapshot

LOG_CONFIG = {
    "level": logging.INFO,
    "format": "%(asctime)s %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
    "datefmt": "%Y-%m-%d %H:%M:%S",
    "handlers": [
        logging.FileHandler("kucoin_status.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
}
UI_UPDATE_INTERVAL = 0.1
THREAD_JOIN_TIMEOUT = 2
HARD_EXIT_DELAY_SEC = 2
ENABLE_HARD_EXIT_FALLBACK = False
PRICE_EPSILON = 0.0001

EXCHANGE_URLS = {
    "kucoin": {
        "label": "KuCoin",
        "home": "https://www.kucoin.com/",
        "spot_trade": "https://www.kucoin.com/trade/{}-{}",
    },
    "binance": {
        "label": "Binance",
        "home": "https://www.binance.com/",
    },
}

logging.basicConfig(**LOG_CONFIG)


def is_color_dot(char: str) -> bool:
    if len(char) != 1:
        return False
    code = ord(char)
    return any(start <= code <= end for start, end in [(0x1F534, 0x1F535), (0x1F7E0, 0x1F7E2), (0x26AB, 0x26AB)])


def _dump_threads(tag: str):
    names = [(t.name, t.daemon) for t in threading.enumerate()]
    logging.info(f"[{tag}] Threads: {names}")


def _with_status_suffix(text: str, status: str) -> str:
    text = text.rstrip()
    if text and is_color_dot(text[-1]):
        text = text[:-1].rstrip()
    return f"{text} {status}".rstrip() if status else text


def _with_trend_suffix(text: str, change: float) -> str:
    text = text.rstrip()
    if change > 0:
        return f"{text} 🟢".rstrip()
    if change < 0:
        return f"{text} 🔴".rstrip()
    return text


def _split_symbol(symbol: str) -> tuple[str, str]:
    parts = normalize_symbol(symbol).split("-", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return symbol.upper(), ""


def build_trade_url(exchange: str, symbol: str) -> str | None:
    base, quote = _split_symbol(symbol)
    if exchange.lower() == "kucoin":
        return EXCHANGE_URLS["kucoin"]["spot_trade"].format(base, quote)
    if exchange.lower() == "binance":
        return f"https://www.binance.com/en/trade/{base}_{quote}?type=spot"
    return None


class Terminator(NSObject):
    def terminate_(self, _):
        NSApp.terminate_(None)


terminator = Terminator.alloc().init()


class MultiSourcePriceMonitor:
    def __init__(self, active_tickers: list[TickerConfig], update_callback, status_callback):
        self.active_tickers = active_tickers
        self.update_callback = update_callback
        self.status_callback = status_callback
        self.sources: Dict[str, BasePriceSource] = {}
        self.threads: Dict[str, threading.Thread] = {}
        self._build_sources()

    def _build_sources(self):
        exchange_map = {
            "kucoin": KucoinPriceSource,
            "binance": BinancePriceSource,
        }
        for exchange in {ticker.exchange.lower() for ticker in self.active_tickers if ticker.enabled}:
            source_cls = exchange_map.get(exchange)
            if source_cls:
                self.sources[exchange] = source_cls(self.update_callback, self.status_callback)
            else:
                logging.warning(f"未识别的数据源插件: {exchange}")

    def start_all(self):
        grouped: Dict[str, list[str]] = {}
        for ticker in self.active_tickers:
            if ticker.enabled:
                grouped.setdefault(ticker.exchange.lower(), []).append(ticker.normalized_symbol)
        for exchange, symbols in grouped.items():
            source = self.sources.get(exchange)
            if not source:
                continue
            thread = threading.Thread(target=source.start, args=(symbols,), daemon=True, name=f"Monitor-{exchange}")
            self.threads[exchange] = thread
            thread.start()
            logging.info(f"{exchange} 监控线程已启动")

    def stop_all(self):
        for exchange, source in self.sources.items():
            try:
                source.stop()
            except Exception as e:
                logging.error(f"停止 {exchange} 数据源失败: {e}\n{traceback.format_exc()}")
        for exchange, thread in self.threads.items():
            try:
                if thread.is_alive():
                    thread.join(timeout=THREAD_JOIN_TIMEOUT)
            except Exception as e:
                logging.warning(f"等待 {exchange} 线程退出失败: {e}")


class CoinPriceBarApp(rumps.App):
    def __init__(self, name: str = "CoinPriceBar", config: AppConfig | None = None, tickers: list[TickerConfig] | None = None):
        super().__init__(name, quit_button=None)
        self.config = config or AppConfig.default()
        self.config_path = DEFAULT_CONFIG_PATH
        self.all_tickers = tickers or get_default_tickers()
        self.monitored_tickers = [ticker for ticker in self.all_tickers if ticker.enabled]
        self.active_tickers = self._visible_tickers()
        self.title_ticker_index = self._resolve_title_ticker_index()
        self.ui_queue = queue.Queue()
        self.status_by_exchange: Dict[str, str] = {}
        self.snapshots: Dict[str, MarketSnapshot] = {}
        self.price_menu_items: Dict[str, rumps.MenuItem] = {}
        self.monitor = MultiSourcePriceMonitor(self.monitored_tickers, self._on_price_update, self._on_status_update)
        self.panel_server = ConfigPanelServer(self._get_current_config, self._get_all_tickers, self._save_ui_config_payload)
        self._quitting = False
        self._init_snapshots()
        self._init_menu()
        self._start_ui_timer()
        self.monitor.start_all()

    def _get_current_config(self) -> AppConfig:
        return self.config

    def _get_all_tickers(self) -> list[TickerConfig]:
        return list(self.all_tickers)

    def _save_ui_config_payload(self, payload: dict) -> AppConfig:
        ui = payload.get("ui") or {}
        config = load_app_config(self.config_path)
        config.max_visible = max(1, int(ui.get("max_visible", config.max_visible)))
        config.title_index = max(0, int(ui.get("title_index", config.title_index)))
        config.title_template = str(ui.get("title_template", config.title_template))
        config.menu_template = str(ui.get("menu_template", config.menu_template))
        display_fields = ui.get("display_fields", config.display_fields)
        if isinstance(display_fields, list):
            config.display_fields = [str(field).strip() for field in display_fields if str(field).strip()]
        config.show_exchange_links = bool(ui.get("show_exchange_links", config.show_exchange_links))
        config.performance_mode = str(ui.get("performance_mode", config.performance_mode)).strip().lower() or config.performance_mode
        config.ui_refresh_interval = max(0.05, float(ui.get("ui_refresh_interval", config.ui_refresh_interval)))
        ticker_prefs = {}
        for index, item in enumerate(ui.get("tickers") or []):
            key = str(item.get("key", "")).strip().lower()
            if not key:
                continue
            ticker_prefs[key] = UITickerPreference(
                key=key,
                visible=bool(item.get("visible", True)),
                order=int(item.get("order", index)),
                pinned_title=bool(item.get("pinned_title", False)),
            )
        if ticker_prefs:
            config.ticker_preferences = ticker_prefs
        from .config import _write_default_config
        _write_default_config(self.config_path, config)
        self.config = load_app_config(self.config_path)
        self._rebuild_ui_from_config()
        return self.config

    def _get_ticker_preference(self, ticker: TickerConfig) -> UITickerPreference:
        return self.config.ticker_preferences.get(
            ticker.key.lower(),
            UITickerPreference(key=ticker.key.lower(), visible=True, order=len(self.config.ticker_preferences), pinned_title=False),
        )

    def _visible_tickers(self) -> list[TickerConfig]:
        ordered = sorted(
            [ticker for ticker in self.all_tickers if ticker.enabled],
            key=lambda ticker: (self._get_ticker_preference(ticker).order, ticker.key),
        )
        visible = [ticker for ticker in ordered if self._get_ticker_preference(ticker).visible]
        return visible[: max(1, self.config.max_visible)]

    def _resolve_title_ticker_index(self) -> int:
        if not self.active_tickers:
            return 0
        for index, ticker in enumerate(self.active_tickers):
            if self._get_ticker_preference(ticker).pinned_title:
                return index
        return min(self.config.title_index, len(self.active_tickers) - 1)

    def _rebuild_active_tickers(self):
        self.monitored_tickers = [ticker for ticker in self.all_tickers if ticker.enabled]
        self.active_tickers = self._visible_tickers()
        self.title_ticker_index = self._resolve_title_ticker_index()

    def _init_snapshots(self):
        existing = getattr(self, "snapshots", {}) or {}
        self.snapshots = {}
        for ticker in self.monitored_tickers:
            snapshot = existing.get(ticker.key) or MarketSnapshot(
                exchange=ticker.exchange,
                symbol=ticker.normalized_symbol,
                status=self.status_by_exchange.get(ticker.exchange, ""),
                display_name=ticker.display_name,
            )
            snapshot.exchange = ticker.exchange
            snapshot.symbol = ticker.normalized_symbol
            snapshot.display_name = ticker.display_name
            if ticker.exchange in self.status_by_exchange:
                snapshot.status = self.status_by_exchange[ticker.exchange]
            self.snapshots[ticker.key] = snapshot
        logging.info(f"已初始化快照数量: {len(self.snapshots)} | keys: {list(self.snapshots.keys())}")

    def _init_menu(self):
        self.menu.clear()
        self.price_menu_items = {}
        if self.config.show_exchange_links:
            added = set()
            for ticker in self.active_tickers:
                exchange = ticker.exchange.lower()
                if exchange in added:
                    continue
                added.add(exchange)
                self.menu.add(rumps.MenuItem(f"打开 {self._menu_label(exchange)}", callback=lambda _, ex=exchange: self._open_exchange_home(ex)))
            if added:
                self.menu.add(rumps.separator)
        for ticker in self.active_tickers:
            item = rumps.MenuItem(
                title=f"{self._menu_label(ticker.exchange)}:{ticker.display_name or ticker.normalized_symbol}: 加载中...",
                callback=lambda _, tk=ticker: self._open_trade_page(tk.exchange, tk.normalized_symbol),
            )
            self.price_menu_items[ticker.key] = item
            self.menu.add(item)
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("UI配置面板", callback=self._open_ui_panel))
        self.menu.add(rumps.MenuItem("打开配置文件", callback=self._open_config_file))
        self.menu.add(rumps.MenuItem("重载UI配置", callback=self._reload_ui_config))
        self.menu.add(rumps.MenuItem("调试快照", callback=self._show_debug_snapshot))
        self.menu.add(rumps.MenuItem("退出", callback=self._cleanup_and_quit))

        logging.info(f"当前可见菜单项 keys: {list(self.price_menu_items.keys())}")
        for ticker in self.active_tickers:
            snapshot = self.snapshots.get(ticker.key)
            if snapshot:
                self._refresh_snapshot_ui(ticker.key)

    def _show_debug_snapshot(self, _):
        lines = []
        for key, snapshot in self.snapshots.items():
            lines.append(
                f"{key} | price={snapshot.price:.4f} | first={snapshot.is_first} | visible={key in self.price_menu_items} | status={snapshot.status or '在线'}"
            )
        message = "\n".join(lines) if lines else "暂无快照"
        logging.info(f"调试快照:\n{message}")
        rumps.alert("调试快照", message)

    def _menu_label(self, exchange: str) -> str:
        return EXCHANGE_URLS.get(exchange.lower(), {}).get("label", exchange.title())

    def _format_change(self, snapshot: MarketSnapshot) -> tuple[str, str]:
        if snapshot.is_first:
            return "", ""
        if snapshot.change > 0:
            return f"↑{snapshot.change:+.2f}", f"↑{abs(snapshot.change_percent):.2f}%"
        if snapshot.change < 0:
            return f"↓{abs(snapshot.change):.2f}", f"↓{abs(snapshot.change_percent):.2f}%"
        return f"{snapshot.change:+.2f}", f"{snapshot.change_percent:+.2f}%"

    def _build_display_context(self, snapshot: MarketSnapshot) -> Dict[str, str]:
        change_text, change_percent_text = self._format_change(snapshot)
        return {
            "exchange": self._menu_label(snapshot.exchange),
            "symbol": snapshot.display_name or snapshot.symbol,
            "price": "异常" if snapshot.has_error else ("加载中..." if snapshot.is_first and snapshot.price == 0 else f"{snapshot.price:.2f}"),
            "change": change_text,
            "change_percent": change_percent_text,
            "status": snapshot.status or "在线",
        }

    def _render_text(self, snapshot: MarketSnapshot, template: str, is_title: bool = False) -> str:
        context = self._build_display_context(snapshot)
        try:
            rendered = template.format(**context)
        except Exception:
            rendered = " ".join(context[field] for field in self.config.display_fields if field in context and context[field])

        rendered = rendered.strip()
        if not rendered:
            rendered = f"{context['exchange']} {context['symbol']} {context['price']}"

        rendered = _with_trend_suffix(rendered, snapshot.change)
        return _with_status_suffix(rendered, snapshot.status if not is_title else "")

    def _rebuild_ui_from_config(self):
        self._rebuild_active_tickers()
        self._init_snapshots()
        self._init_menu()
        for ticker in self.active_tickers:
            self._refresh_snapshot_ui(ticker.key)
        if not self.active_tickers:
            self.title = "CoinPriceBar"

    def _open_ui_panel(self, _):
        try:
            self.panel_server.open()
        except Exception as e:
            logging.error(f"打开 UI 配置面板失败: {e}\n{traceback.format_exc()}")
            rumps.alert("错误", f"无法打开 UI 配置面板：{e}")

    def _open_config_file(self, _):
        try:
            if not self.config_path.exists():
                load_app_config(self.config_path)
            self._open_url(self.config_path.as_uri(), "配置文件")
        except Exception as e:
            logging.error(f"打开配置文件失败: {e}\n{traceback.format_exc()}")
            rumps.alert("错误", f"无法打开配置文件：{e}")

    def _edit_ui_config(self, _):
        self._open_ui_panel(_)

    def _reload_ui_config(self, _):
        try:
            self.config = load_app_config(self.config_path)
            self._rebuild_ui_from_config()
            logging.info("UI 配置已重载")
        except Exception as e:
            logging.error(f"重载 UI 配置失败: {e}\n{traceback.format_exc()}")
            rumps.alert("错误", f"重载 UI 配置失败：{e}")

    def _start_ui_timer(self):
        self.ui_timer = rumps.Timer(self._process_ui_queue, self.config.ui_refresh_interval)
        self.ui_timer.start()

    def _on_price_update(self, exchange: str, symbol: str, price: float):
        if self._quitting:
            return
        key = f"{exchange.lower()}::{normalize_symbol(symbol)}"
        snapshot = self.snapshots.get(key)
        if not snapshot:
            logging.warning(f"收到价格但未找到对应快照: {key} | 当前快照: {list(self.snapshots.keys())}")
            return
        if not snapshot.is_first and abs(price - snapshot.price) < PRICE_EPSILON:
            return

        old_price = snapshot.price
        change = 0.0 if snapshot.is_first else price - old_price
        change_percent = (change / old_price * 100) if (old_price and not snapshot.is_first) else 0.0
        snapshot.price = price
        snapshot.change = change
        snapshot.change_percent = change_percent
        snapshot.is_first = False
        snapshot.has_error = False
        snapshot.status = self.status_by_exchange.get(exchange.lower(), snapshot.status)
        self.ui_queue.put(lambda ticker_key=key: self._refresh_snapshot_ui(ticker_key))

    def _on_status_update(self, exchange: str, status: str):
        if self._quitting:
            return
        exchange = exchange.lower()
        if self.status_by_exchange.get(exchange) == status:
            return
        self.status_by_exchange[exchange] = status
        self.ui_queue.put(lambda ex=exchange, st=status: self._apply_exchange_status(ex, st))

    def _apply_exchange_status(self, exchange: str, status: str):
        for snapshot in self.snapshots.values():
            if snapshot.exchange.lower() == exchange:
                snapshot.status = status
                self._refresh_snapshot_ui(snapshot.key)

    def _refresh_snapshot_ui(self, key: str):
        snapshot = self.snapshots.get(key)
        if not snapshot:
            logging.warning(f"刷新 UI 时未找到快照: {key}")
            return

        if self.active_tickers and key == self.active_tickers[self.title_ticker_index].key:
            self.title = self._render_text(snapshot, self.config.title_template, is_title=True)

        item = self.price_menu_items.get(key)
        if item is not None:
            item.title = self._render_text(snapshot, self.config.menu_template)
        else:
            logging.info(f"价格已更新但当前不可见: {key}")

    def _process_ui_queue(self, _=None):
        try:
            while not self.ui_queue.empty():
                task = self.ui_queue.get_nowait()
                if not self._quitting and callable(task):
                    task()
        except Exception as e:
            logging.error(f"处理UI任务失败: {e}\n{traceback.format_exc()}")

    def _open_exchange_home(self, exchange: str):
        url = EXCHANGE_URLS.get(exchange.lower(), {}).get("home")
        if url:
            self._open_url(url, f"{self._menu_label(exchange)} 官网")

    def _open_trade_page(self, exchange: str, symbol: str):
        try:
            trade_url = build_trade_url(exchange, symbol)
            if not trade_url:
                raise ValueError(f"不支持的数据源: {exchange}")
            self._open_url(trade_url, f"{self._menu_label(exchange)} {symbol} 交易页面")
        except Exception as e:
            logging.error(f"构造交易URL失败: {e}")
            rumps.alert("错误", f"无法打开 {symbol} 交易页面")

    def _open_url(self, url: str, desc: str):
        try:
            webbrowser.open_new_tab(url)
            logging.info(f"打开{desc}: {url}")
        except Exception as e:
            logging.error(f"打开{desc}失败: {e}\n{traceback.format_exc()}")
            rumps.alert("错误", f"无法打开{desc}，请检查浏览器设置")

    def _cleanup_and_quit(self, _):
        if self._quitting:
            return
        self._quitting = True
        logging.info("开始退出应用（非阻塞清理）...")
        _dump_threads("Quit requested")
        try:
            self.title = "正在退出…"
        except Exception:
            pass

        def _do_cleanup_then_quit():
            try:
                try:
                    if hasattr(self, "ui_timer"):
                        self.ui_timer.stop()
                except Exception:
                    pass
                try:
                    self.panel_server.stop()
                except Exception:
                    pass
                self.monitor.stop_all()
                logging.info("资源清理完成")
                _dump_threads("Cleanup done")
            finally:
                terminator.performSelectorOnMainThread_withObject_waitUntilDone_("terminate:", None, False)
                if ENABLE_HARD_EXIT_FALLBACK:
                    def _hard_kill():
                        time.sleep(HARD_EXIT_DELAY_SEC)
                        logging.critical("优雅退出可能未完成，执行 os._exit(0) 兜底")
                        os._exit(0)
                    threading.Thread(target=_hard_kill, daemon=True, name="HardExit").start()

        threading.Thread(target=_do_cleanup_then_quit, daemon=True, name="Cleanup-Worker").start()

    def run(self):
        try:
            if self.active_tickers:
                for ticker in self.active_tickers:
                    self._refresh_snapshot_ui(ticker.key)
            super().run()
        finally:
            try:
                if hasattr(self, "ui_timer"):
                    self.ui_timer.stop()
            except Exception:
                pass
