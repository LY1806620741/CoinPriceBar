import logging
import os
import queue
import threading
import time
import traceback
import webbrowser
from pathlib import Path
from typing import Dict
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import rumps
from AppKit import NSApp, NSBitmapImageRep, NSColor, NSFont, NSImage, NSMakeRect, NSPNGFileType, NSStatusBar, NSVariableStatusItemLength, NSZeroRect
from Foundation import NSObject

from .config import AppConfig, DEFAULT_CONFIG_PATH, TickerConfig, UITickerPreference, get_default_tickers, load_app_config, normalize_symbol
from .panel import ConfigPanelServer
from .sources import BasePriceSource, MarketSnapshot, get_source_class

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

logging.basicConfig(**LOG_CONFIG)
MENU_ICON_SIZE = 18
ICON_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "exchange_icons"
ICON_DOWNLOAD_TIMEOUT = 5
MENU_ICON_CACHE_SUFFIX = ".menu.png"


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


class Terminator(NSObject):
    def terminate_(self, _):
        NSApp.terminate_(None)


class MenuLifecycleDelegate(NSObject):
    def menuWillOpen_(self, _menu):
        callback = getattr(self, "_on_open", None)
        if callable(callback):
            callback()

    def menuDidClose_(self, _menu):
        callback = getattr(self, "_on_close", None)
        if callable(callback):
            callback()


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
        for exchange in {ticker.exchange.lower() for ticker in self.active_tickers if ticker.enabled}:
            source_cls = get_source_class(exchange)
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
        self.all_tickers = tickers or list(self.config.tickers or get_default_tickers())
        self.monitored_tickers = [
            ticker for ticker in self.all_tickers
            if ticker.enabled and self.config.exchanges.get(ticker.exchange.lower()) and self.config.exchanges[ticker.exchange.lower()].enabled
        ]
        self.active_tickers = self._visible_tickers()
        self.title_ticker_index = self._resolve_title_ticker_index()
        self.ui_queue = queue.Queue()
        self.status_by_exchange: Dict[str, str] = {}
        self.snapshots: Dict[str, MarketSnapshot] = {}
        self.price_menu_items: Dict[str, rumps.MenuItem] = {}
        self.monitor = MultiSourcePriceMonitor(self.monitored_tickers, self._on_price_update, self._on_status_update)
        self.panel_server = ConfigPanelServer(self._get_current_config, self._get_all_tickers, self._save_ui_config_payload)
        self._quitting = False
        self._status_item = None
        self._menu_visible = False
        self._title_dirty = False
        self._dirty_menu_keys: set[str] = set()
        self._dirty_lock = threading.Lock()
        self._menu_delegate = None
        self._init_snapshots()
        self._init_menu()
        self._bind_status_item_button()
        self._start_ui_timer()
        self._warm_menu_icons_async()
        self.monitor.start_all()

    def _get_current_config(self) -> AppConfig:
        return self.config

    def _get_all_tickers(self) -> list[TickerConfig]:
        return list(self.all_tickers)

    def _save_ui_config_payload(self, payload: dict) -> AppConfig:
        ui = payload.get("ui") or {}
        config = load_app_config(self.config_path)
        config.language = str(ui.get("language", config.language)).strip() or config.language
        config.title_index = max(0, int(ui.get("title_index", config.title_index)))
        config.format_mode = str(ui.get("format_mode", config.format_mode)).strip().lower() or config.format_mode
        config.title_template = str(ui.get("title_template", config.title_template))
        config.title_template_multi = str(ui.get("title_template_multi", ui.get("title_template", config.title_template_multi)))
        config.title_separator = str(ui.get("title_separator", config.title_separator))
        config.menu_template = str(ui.get("menu_template", config.menu_template))
        config.icon_style = str(ui.get("icon_style", config.icon_style)).strip().lower() or config.icon_style
        display_fields = ui.get("display_fields", config.display_fields)
        if isinstance(display_fields, list):
            config.display_fields = [str(field).strip() for field in display_fields if str(field).strip()]
        config.show_exchange_links = bool(ui.get("show_exchange_links", config.show_exchange_links))
        config.performance_mode = str(ui.get("performance_mode", config.performance_mode)).strip().lower() or config.performance_mode
        config.ui_refresh_interval = max(0.05, float(ui.get("ui_refresh_interval", config.ui_refresh_interval)))

        exchanges_payload = ui.get("exchanges") or {}
        if isinstance(exchanges_payload, dict):
            for name, exchange_config in config.exchanges.items():
                item = exchanges_payload.get(name)
                if isinstance(item, dict):
                    exchange_config.enabled = bool(item.get("enabled", exchange_config.enabled))

        short_names_payload = ui.get("exchange_short_names") or {}
        if isinstance(short_names_payload, dict):
            for name, current_value in config.exchange_short_names.items():
                value = str(short_names_payload.get(name, current_value)).strip()
                if value:
                    config.exchange_short_names[name] = value

        exchange_icons_payload = ui.get("exchange_icons") or {}
        if isinstance(exchange_icons_payload, dict):
            for name, current_value in config.exchange_icons.items():
                config.exchange_icons[name] = str(exchange_icons_payload.get(name, current_value))

        tickers_payload = ui.get("tickers") or []
        if isinstance(tickers_payload, list):
            updated_tickers: list[TickerConfig] = []
            for item in tickers_payload:
                if not isinstance(item, dict):
                    continue
                exchange = str(item.get("exchange", "")).strip().lower()
                symbol = normalize_symbol(str(item.get("symbol", "")))
                if not exchange or not symbol:
                    continue
                updated_tickers.append(
                    TickerConfig(
                        exchange=exchange,
                        symbol=symbol,
                        enabled=bool(item.get("enabled", True)),
                        display_name=(str(item.get("display_name", "")).strip() or None),
                    )
                )
            if updated_tickers:
                config.tickers = updated_tickers

        ticker_prefs = {}
        for index, item in enumerate(ui.get("ticker_preferences") or []):
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
        self.all_tickers = list(self.config.tickers or get_default_tickers())
        self.monitor.stop_all()
        self.monitor = MultiSourcePriceMonitor(
            [
                ticker for ticker in self.all_tickers
                if ticker.enabled and self.config.exchanges.get(ticker.exchange.lower()) and self.config.exchanges[ticker.exchange.lower()].enabled
            ],
            self._on_price_update,
            self._on_status_update,
        )
        self._rebuild_ui_from_config()
        self.monitor.start_all()
        return self.config

    def _get_ticker_preference(self, ticker: TickerConfig) -> UITickerPreference:
        return self.config.ticker_preferences.get(
            ticker.key.lower(),
            UITickerPreference(key=ticker.key.lower(), visible=True, order=len(self.config.ticker_preferences), pinned_title=False),
        )

    def _visible_tickers(self) -> list[TickerConfig]:
        ordered = [ticker for ticker in self.all_tickers if ticker.enabled]
        visible = [ticker for ticker in ordered if self._get_ticker_preference(ticker).visible]
        return visible

    def _resolve_title_tickers(self) -> list[TickerConfig]:
        if not self.active_tickers:
            return []
        pinned = [ticker for ticker in self.active_tickers if CoinPriceBarApp._get_ticker_preference(self, ticker).pinned_title]
        if pinned:
            return pinned
        fallback_index = min(self.config.title_index, len(self.active_tickers) - 1)
        return [self.active_tickers[fallback_index]]

    def _resolve_title_ticker_index(self) -> int:
        title_tickers = CoinPriceBarApp._resolve_title_tickers(self)
        if not self.active_tickers or not title_tickers:
            return 0
        first_key = title_tickers[0].key
        for index, ticker in enumerate(self.active_tickers):
            if ticker.key == first_key:
                return index
        return 0

    def _rebuild_active_tickers(self):
        self.monitored_tickers = [
            ticker for ticker in self.all_tickers
            if ticker.enabled and self.config.exchanges.get(ticker.exchange.lower()) and self.config.exchanges[ticker.exchange.lower()].enabled
        ]
        self.active_tickers = self._visible_tickers()
        self.title_tickers = CoinPriceBarApp._resolve_title_tickers(self)
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

    @staticmethod
    def _ns_color(rgba: tuple[float, float, float, float]):
        return NSColor.colorWithCalibratedRed_green_blue_alpha_(*rgba)

    @staticmethod
    def _build_menu_icon(exchange: str) -> NSImage | None:
        source_cls = get_source_class(exchange)
        style = source_cls.get_menu_icon_style() if source_cls else None
        if not style:
            return None
        image = NSImage.alloc().initWithSize_((MENU_ICON_SIZE, MENU_ICON_SIZE))
        image.lockFocus()
        try:
            CoinPriceBarApp._ns_color(style["bg"]).set()
            NSColor.clearColor().set()
            from AppKit import NSBezierPath, NSAttributedString
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(0, 0, MENU_ICON_SIZE, MENU_ICON_SIZE), 4, 4)
            path.fill()
            attrs = {
                "NSFont": NSFont.boldSystemFontOfSize_(11),
                "NSColor": CoinPriceBarApp._ns_color(style["fg"]),
            }
            text = NSAttributedString.alloc().initWithString_attributes_(style["text"], attrs)
            text.drawAtPoint_((5, 2))
        except Exception:
            image.unlockFocus()
            return None
        image.unlockFocus()
        return image

    @staticmethod
    def _fit_image_for_menu(source: NSImage) -> NSImage | None:
        try:
            target = NSImage.alloc().initWithSize_((MENU_ICON_SIZE, MENU_ICON_SIZE))
            target.lockFocus()
            try:
                source_size = source.size()
                src_w = float(source_size.width)
                src_h = float(source_size.height)
                if src_w <= 0 or src_h <= 0:
                    return None
                scale = min(MENU_ICON_SIZE / src_w, MENU_ICON_SIZE / src_h)
                draw_w = max(1.0, src_w * scale)
                draw_h = max(1.0, src_h * scale)
                draw_x = (MENU_ICON_SIZE - draw_w) / 2.0
                draw_y = (MENU_ICON_SIZE - draw_h) / 2.0
                source.drawInRect_fromRect_operation_fraction_(NSMakeRect(draw_x, draw_y, draw_w, draw_h), NSZeroRect, 2, 1.0)
            finally:
                target.unlockFocus()
            return target
        except Exception as e:
            logging.debug(f"标准化菜单图标失败: {e}")
            return None

    @staticmethod
    def _icon_cache_path(exchange: str) -> Path:
        ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        source_cls = get_source_class(exchange)
        local_path = source_cls.get_local_icon_path() if source_cls else None
        if local_path is not None:
            return ICON_CACHE_DIR / f"{exchange.lower()}{local_path.suffix}"
        url = source_cls.get_icon_url() if source_cls else ""
        suffix = Path(urlparse(url).path).suffix or ".img"
        return ICON_CACHE_DIR / f"{exchange.lower()}{suffix}"

    @staticmethod
    def _is_valid_cache_file(path: Path) -> bool:
        return path.exists() and path.is_file() and path.stat().st_size > 0

    @staticmethod
    def _write_menu_icon_png(image: NSImage, target_path: Path) -> bool:
        try:
            tiff_data = image.TIFFRepresentation()
            if tiff_data is None:
                return False
            bitmap = NSBitmapImageRep.imageRepWithData_(tiff_data)
            if bitmap is None:
                return False
            png_data = bitmap.representationUsingType_properties_(NSPNGFileType, None)
            if png_data is None:
                return False
            ok = bool(png_data.writeToFile_atomically_(str(target_path), True))
            return ok and CoinPriceBarApp._is_valid_cache_file(target_path)
        except Exception as e:
            logging.debug(f"写入菜单 PNG 缓存失败: {target_path} -> {e}")
            return False

    @staticmethod
    def _download_exchange_icon(exchange: str) -> Path | None:
        source_cls = get_source_class(exchange)
        url = source_cls.get_icon_url() if source_cls else ""
        cache_path = CoinPriceBarApp._icon_cache_path(exchange)
        if CoinPriceBarApp._is_valid_cache_file(cache_path):
            return cache_path
        local_path = source_cls.get_local_icon_path() if source_cls else None
        try:
            if cache_path.exists() and not CoinPriceBarApp._is_valid_cache_file(cache_path):
                cache_path.unlink(missing_ok=True)
            ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            if url:
                request = Request(
                    url,
                    headers=source_cls.get_icon_request_headers() if source_cls else {},
                )
                with urlopen(request, timeout=ICON_DOWNLOAD_TIMEOUT) as response:
                    data = response.read()
                    content_type = str(response.headers.get("Content-Type", ""))
                if data and (source_cls.accepts_icon_content_type(content_type) if source_cls else True):
                    cache_path.write_bytes(data)
                    if CoinPriceBarApp._is_valid_cache_file(cache_path):
                        return cache_path
            if local_path is not None and local_path.exists():
                cache_path.write_bytes(local_path.read_bytes())
                return cache_path if CoinPriceBarApp._is_valid_cache_file(cache_path) else None
            return None
        except (OSError, URLError) as e:
            logging.warning(f"下载官方 logo 失败: {exchange} -> {e}")
            if local_path is not None and local_path.exists():
                try:
                    cache_path.write_bytes(local_path.read_bytes())
                    return cache_path if CoinPriceBarApp._is_valid_cache_file(cache_path) else None
                except OSError:
                    return None
            return cache_path if CoinPriceBarApp._is_valid_cache_file(cache_path) else None

    @staticmethod
    def _load_cached_exchange_icon(exchange: str) -> NSImage | None:
        cache_path = CoinPriceBarApp._download_exchange_icon(exchange)
        if not cache_path or not CoinPriceBarApp._is_valid_cache_file(cache_path):
            return None
        try:
            image = NSImage.alloc().initWithContentsOfFile_(str(cache_path))
            if image is None:
                cache_path.unlink(missing_ok=True)
                return None
            fitted = CoinPriceBarApp._fit_image_for_menu(image)
            return fitted or image
        except Exception as e:
            logging.debug(f"读取缓存 logo 失败: {exchange} -> {e}")
            cache_path.unlink(missing_ok=True)
            return None

    def _apply_menu_item_icon(self, item: rumps.MenuItem, exchange: str):
        try:
            native_item = getattr(item, "_menuitem", None)
            if native_item is None:
                return
            icon = CoinPriceBarApp._load_cached_exchange_icon(exchange)
            source_cls = get_source_class(exchange)
            if icon is None and source_cls and source_cls.should_retry_icon_download_on_load_failure():
                cache_path = CoinPriceBarApp._icon_cache_path(exchange)
                if cache_path.exists():
                    try:
                        cache_path.unlink()
                    except OSError:
                        pass
                    icon = CoinPriceBarApp._load_cached_exchange_icon(exchange)
            if icon is None:
                icon = CoinPriceBarApp._build_menu_icon(exchange)
            if icon is not None:
                native_item.setImage_(icon)
        except Exception as e:
            logging.debug(f"设置菜单图标失败: {exchange} -> {e}")

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
            self._apply_menu_item_icon(item, ticker.exchange)
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
        self._bind_menu_delegate()

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
        source_cls = get_source_class(exchange)
        return source_cls.get_display_label() if source_cls else exchange.title()

    def _exchange_short_label(self, exchange: str) -> str:
        exchange_key = exchange.lower()
        value = (self.config.exchange_short_names or {}).get(exchange_key, "")
        return value.strip() or self._menu_label(exchange)

    def _format_change(self, snapshot: MarketSnapshot) -> tuple[str, str]:
        if snapshot.is_first:
            return "", ""
        if snapshot.change > 0:
            return f"↑{snapshot.change:+.2f}", f"↑{abs(snapshot.change_percent):.2f}%"
        if snapshot.change < 0:
            return f"↓{abs(snapshot.change):.2f}", f"↓{abs(snapshot.change_percent):.2f}%"
        return f"{snapshot.change:+.2f}", f"{snapshot.change_percent:+.2f}%"

    def _build_display_context(self, snapshot: MarketSnapshot) -> dict[str, str]:
        change_text, change_percent_text = self._format_change(snapshot)
        exchange_short = self._exchange_short_label(snapshot.exchange)
        exchange_full = self._menu_label(snapshot.exchange)
        exchange_icon = (self.config.exchange_icons or {}).get(snapshot.exchange.lower(), "")
        price_text = "异常" if snapshot.has_error else ("加载中..." if snapshot.is_first and snapshot.price == 0 else f"{snapshot.price:.2f}")
        status_text = snapshot.status or ("🟢" if snapshot.change > 0 else "🔴" if snapshot.change < 0 else "⚪")
        return {
            "exchange": exchange_short,
            "exchange_short": exchange_short,
            "exchange_full": exchange_full,
            "exchange_icon": exchange_icon,
            "symbol": snapshot.display_name or snapshot.symbol,
            "price": price_text,
            "change": change_text,
            "change_percent": change_percent_text,
            "status": status_text,
        }

    def _render_text(self, snapshot: MarketSnapshot, template: str, is_title: bool = False) -> str:
        context = self._build_display_context(snapshot)
        if is_title:
            context = dict(context)
            context["exchange_icon"] = ""
        try:
            rendered = template.format(**context).strip()
        except Exception:
            rendered = f"{context['exchange']} {context['symbol']} {context['price']}"
        if not rendered:
            rendered = f"{context['exchange']} {context['symbol']} {context['price']}"

        rendered = _with_trend_suffix(rendered, snapshot.change)
        return _with_status_suffix(rendered, snapshot.status if not is_title else "")

    def _clear_title_icon(self):
        try:
            self.icon = None
        except Exception:
            try:
                self.icon = ""
            except Exception:
                pass

    def _resolve_title_icon_exchange(self, title_tickers: list[TickerConfig]) -> str | None:
        if not title_tickers or self.config.icon_style != "official":
            return None
        exchanges = {ticker.exchange.lower() for ticker in title_tickers}
        return title_tickers[0].exchange if len(exchanges) == 1 else None

    def _refresh_title(self):
        title_tickers = CoinPriceBarApp._resolve_title_tickers(self)
        self.title_tickers = title_tickers
        if not title_tickers:
            self.title = "CoinPriceBar"
            CoinPriceBarApp._clear_title_icon(self)
            return

        title_template = self.config.title_template if len(title_tickers) <= 1 else (self.config.title_template_multi or self.config.title_template)
        parts = []
        for ticker in title_tickers:
            snapshot = self.snapshots.get(ticker.key)
            if snapshot is not None:
                parts.append(self._render_text(snapshot, title_template, is_title=True))
        self.title = (self.config.title_separator or " | ").join(part for part in parts if part).strip() or "CoinPriceBar"

        icon_exchange = CoinPriceBarApp._resolve_title_icon_exchange(self, title_tickers)
        if icon_exchange:
            self._set_title_icon(icon_exchange)
        else:
            CoinPriceBarApp._clear_title_icon(self)

    def _rebuild_ui_from_config(self):
        self._rebuild_active_tickers()
        self._init_snapshots()
        self._init_menu()
        for ticker in self.active_tickers:
            self._refresh_snapshot_ui(ticker.key)
        if not self.active_tickers:
            self.title = "CoinPriceBar"
            CoinPriceBarApp._clear_title_icon(self)

    def _bind_status_item_button(self):
        try:
            candidates = []
            menu_impl = getattr(self, "menu", None)
            if menu_impl is not None:
                candidates.extend([
                    getattr(menu_impl, "_menu", None),
                    getattr(menu_impl, "_statusitem", None),
                    getattr(menu_impl, "statusitem", None),
                ])
            candidates.extend([
                getattr(self, "_statusitem", None),
                getattr(self, "_nsstatusitem", None),
                getattr(self, "_menuitem", None),
                getattr(self, "_status_bar", None),
                getattr(self, "_statusbar", None),
            ])
            raw_candidates = []
            for candidate in candidates:
                if candidate is None:
                    continue
                raw_candidates.append(candidate)
                raw_candidates.append(getattr(candidate, "_menuitem", None))
                raw_candidates.append(getattr(candidate, "_statusitem", None))
            for candidate in raw_candidates:
                if candidate is None:
                    continue
                if hasattr(candidate, "button") or hasattr(candidate, "setImage_"):
                    self._status_item = candidate
                    logging.info(f"标题状态栏对象已绑定: {type(candidate)}")
                    return
            self._status_item = None
            logging.warning("标题状态栏对象未找到")
        except Exception as e:
            logging.warning(f"绑定状态栏按钮失败: {e}")
            self._status_item = None

    def _bind_menu_delegate(self):
        try:
            native_menu = getattr(self.menu, "_menu", None)
            if native_menu is None:
                return
            delegate = MenuLifecycleDelegate.alloc().init()
            delegate._on_open = self._on_menu_will_open
            delegate._on_close = self._on_menu_did_close
            native_menu.setDelegate_(delegate)
            self._menu_delegate = delegate
        except Exception as e:
            logging.debug(f"绑定菜单生命周期代理失败: {e}")

    def _ensure_ui_dirty_state(self):
        if not hasattr(self, "_dirty_lock") or self._dirty_lock is None:
            self._dirty_lock = threading.Lock()
        if not hasattr(self, "_dirty_menu_keys") or self._dirty_menu_keys is None:
            self._dirty_menu_keys = set()
        if not hasattr(self, "_title_dirty"):
            self._title_dirty = False
        if not hasattr(self, "_menu_visible"):
            self._menu_visible = True

    def _on_menu_will_open(self):
        CoinPriceBarApp._ensure_ui_dirty_state(self)
        self._menu_visible = True
        CoinPriceBarApp._process_ui_queue(self)
        CoinPriceBarApp._refresh_visible_menu_items(self)

    def _on_menu_did_close(self):
        CoinPriceBarApp._ensure_ui_dirty_state(self)
        self._menu_visible = False

    def _mark_snapshot_dirty(self, key: str):
        CoinPriceBarApp._ensure_ui_dirty_state(self)
        with self._dirty_lock:
            self._dirty_menu_keys.add(key)
            title_keys = {ticker.key for ticker in CoinPriceBarApp._resolve_title_tickers(self)}
            if key in title_keys:
                self._title_dirty = True

    def _drain_dirty_state(self) -> tuple[bool, list[str]]:
        CoinPriceBarApp._ensure_ui_dirty_state(self)
        with self._dirty_lock:
            title_dirty = self._title_dirty
            if title_dirty:
                self._title_dirty = False
            if self._menu_visible:
                menu_keys = [key for key in self._dirty_menu_keys if key in self.price_menu_items]
                for key in menu_keys:
                    self._dirty_menu_keys.discard(key)
            else:
                menu_keys = []
        return title_dirty, menu_keys

    def _refresh_title_for_key(self, key: str):
        if key not in {ticker.key for ticker in CoinPriceBarApp._resolve_title_tickers(self)}:
            return
        CoinPriceBarApp._refresh_title(self)

    def _refresh_menu_item_for_key(self, key: str):
        snapshot = self.snapshots.get(key)
        if not snapshot:
            return
        item = self.price_menu_items.get(key)
        if item is not None:
            item.title = self._render_text(snapshot, self.config.menu_template)

    def _refresh_visible_menu_items(self):
        for ticker in self.active_tickers:
            CoinPriceBarApp._refresh_menu_item_for_key(self, ticker.key)

    def _set_title_icon(self, exchange: str):
        try:
            cache_path = CoinPriceBarApp._download_exchange_icon(exchange)
            if not cache_path or not CoinPriceBarApp._is_valid_cache_file(cache_path):
                logging.warning(f"设置标题图标失败: 未加载到 {exchange} 图标")
                return
            self.icon = str(cache_path)
            logging.debug(f"标题图标已设置: {exchange} -> {cache_path}")
        except Exception as e:
            logging.warning(f"设置标题图标失败: {exchange} -> {e}")

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
        self.ui_queue.put(lambda ticker_key=key: CoinPriceBarApp._mark_snapshot_dirty(self, ticker_key))

    def _on_status_update(self, exchange: str, status: str):
        if self._quitting:
            return
        exchange = exchange.lower()
        if self.status_by_exchange.get(exchange) == status:
            return
        self.status_by_exchange[exchange] = status
        self.ui_queue.put(lambda ex=exchange, st=status: CoinPriceBarApp._apply_exchange_status(self, ex, st))

    def _apply_exchange_status(self, exchange: str, status: str):
        for snapshot in self.snapshots.values():
            if snapshot.exchange.lower() == exchange:
                snapshot.status = status
                CoinPriceBarApp._mark_snapshot_dirty(self, snapshot.key)

    def _refresh_snapshot_ui(self, key: str):
        snapshot = self.snapshots.get(key)
        if not snapshot:
            logging.warning(f"刷新 UI 时未找到快照: {key}")
            return

        if key in {ticker.key for ticker in CoinPriceBarApp._resolve_title_tickers(self)}:
            CoinPriceBarApp._refresh_title_for_key(self, key)

        CoinPriceBarApp._refresh_menu_item_for_key(self, key)

    def _process_ui_queue(self, _=None):
        try:
            while not self.ui_queue.empty():
                task = self.ui_queue.get_nowait()
                if not self._quitting and callable(task):
                    task()
            title_dirty, menu_keys = CoinPriceBarApp._drain_dirty_state(self)
            if title_dirty and self.active_tickers:
                CoinPriceBarApp._refresh_title(self)
            for key in menu_keys:
                CoinPriceBarApp._refresh_menu_item_for_key(self, key)
        except Exception as e:
            logging.error(f"处理UI任务失败: {e}\n{traceback.format_exc()}")

    def _open_exchange_home(self, exchange: str):
        source_cls = get_source_class(exchange)
        url = source_cls.get_home_url() if source_cls else ""
        if url:
            self._open_url(url, f"{self._menu_label(exchange)} 官网")

    def _open_trade_page(self, exchange: str, symbol: str):
        try:
            source_cls = get_source_class(exchange)
            trade_url = source_cls.build_trade_url(symbol) if source_cls else None
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
                    self.monitor.stop_all()
                except Exception as e:
                    logging.error(f"停止监控失败: {e}\n{traceback.format_exc()}")
            finally:
                _dump_threads("Before terminate")
                if os.environ.get("COINPRICEBAR_SKIP_TERMINATE") != "1":
                    try:
                        NSApp.performSelectorOnMainThread_withObject_waitUntilDone_("terminate:", None, False)
                    except Exception:
                        try:
                            terminator.performSelectorOnMainThread_withObject_waitUntilDone_("terminate:", None, False)
                        except Exception as e:
                            logging.error(f"退出应用失败: {e}\n{traceback.format_exc()}")

        threading.Thread(target=_do_cleanup_then_quit, daemon=True, name="Quit-Cleanup").start()

        if ENABLE_HARD_EXIT_FALLBACK:
            def _hard_exit():
                time.sleep(HARD_EXIT_DELAY_SEC)
                os._exit(0)

            threading.Thread(target=_hard_exit, daemon=True, name="Quit-HardExit").start()

    def _refresh_all_menu_icons(self):
        for ticker in self.active_tickers:
            item = self.price_menu_items.get(ticker.key)
            if item is not None:
                self._apply_menu_item_icon(item, ticker.exchange)

    def _warm_menu_icons_async(self):
        exchanges = sorted({ticker.exchange.lower() for ticker in self.active_tickers})
        if not exchanges:
            return

        def _worker():
            try:
                for exchange in exchanges:
                    CoinPriceBarApp._download_exchange_icon(exchange)
                self.ui_queue.put(self._refresh_all_menu_icons)
            except Exception as e:
                logging.debug(f"后台预热交易所 logo 失败: {e}")

        threading.Thread(target=_worker, daemon=True, name="Warm-Menu-Icons").start()

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
