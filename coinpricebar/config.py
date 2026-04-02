import json
import logging
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
DEFAULT_DISPLAY_FIELDS = ["exchange", "symbol", "price", "change_percent", "status"]
DEFAULT_TITLE_TEMPLATE = "{exchange}:{symbol} {price}"
DEFAULT_MENU_TEMPLATE = "{exchange}:{symbol} {price} ({change_percent})"
FORMAT_PRESETS = {
    "short": {
        "title_template": "{exchange_icon}{symbol} {price}",
        "menu_template": "{exchange_icon}{symbol} {price} ({change_percent})",
        "label": "短格式",
    },
    "long": {
        "title_template": "{exchange_icon}{exchange_full} {symbol} 最新价 {price}",
        "menu_template": "{exchange_icon}{exchange_full} {symbol} 最新价 {price} 涨跌 {change_percent} 状态 {status}",
        "label": "长格式",
    },
    "custom": {
        "title_template": DEFAULT_TITLE_TEMPLATE,
        "menu_template": DEFAULT_MENU_TEMPLATE,
        "label": "自定义",
    },
}
DEFAULT_FORMAT_MODE = "short"
OFFICIAL_EXCHANGE_ICON_URLS = {
    "kucoin": "https://www.kucoin.com/logo.png",
    "binance": "https://public.bnbstatic.com/static/images/common/favicon.ico",
}
EXCHANGE_ICON_PRESETS = {
    "none": {"kucoin": "", "binance": ""},
    "emoji": {"kucoin": "🟢 ", "binance": "🟡 "},
    "text": {"kucoin": "[KC] ", "binance": "[BN] "},
    "official": {"kucoin": "", "binance": ""},
}
ICON_STYLE_OPTIONS = {
    "none": "无图标",
    "emoji": "Emoji 图标",
    "text": "文本图标",
    "official": "官方 Logo",
}
DEFAULT_ICON_STYLE = "official"
TEMPLATE_VARIABLES = [
    {"name": "exchange", "example": "KC", "description": "交易所短名称"},
    {"name": "exchange_short", "example": "KC", "description": "交易所短名称（同 exchange）"},
    {"name": "exchange_full", "example": "KuCoin", "description": "交易所完整名称"},
    {"name": "exchange_icon", "example": "🟢 ", "description": "交易所图标/前缀"},
    {"name": "symbol", "example": "BTC", "description": "显示名称或交易对"},
    {"name": "price", "example": "67019.00", "description": "当前价格"},
    {"name": "change", "example": "↑+520.00", "description": "价格涨跌额"},
    {"name": "change_percent", "example": "↑0.78%", "description": "价格涨跌幅"},
    {"name": "status", "example": "在线", "description": "连接状态"},
]
TEMPLATE_EXAMPLES = [
    "{exchange_icon}{exchange}:{symbol} {price}",
    "{exchange_icon}{exchange}:{symbol} {price} ({change_percent})",
    "{exchange_full} {symbol} 最新价 {price} 状态 {status}",
]
SUPPORTED_FIELDS = {
    "exchange",
    "exchange_short",
    "exchange_full",
    "exchange_icon",
    "symbol",
    "price",
    "change",
    "change_percent",
    "status",
}
DEFAULT_TICKERS = [
    ("kucoin", "KCS-USDT", "KCS"),
    ("kucoin", "BTC-USDT", "BTC"),
    ("kucoin", "ETH-USDT", "ETH"),
    ("binance", "ETH-USDT", "ETH"),
]
PERFORMANCE_PRESETS = {
    "stable": 0.5,
    "balanced": 0.25,
    "realtime": 0.12,
    "custom": None,
}
DEFAULT_PERFORMANCE_MODE = "balanced"
SUPPORTED_LANGUAGES = {"zh-CN", "en-US"}
DEFAULT_LANGUAGE = "zh-CN"
SUPPORTED_EXCHANGES = {
    "kucoin": "KuCoin",
    "binance": "Binance",
}
DEFAULT_EXCHANGE_SHORT_NAMES = {
    "kucoin": "KC",
    "binance": "BN",
}


@dataclass
class TickerConfig:
    exchange: str
    symbol: str
    enabled: bool = True
    display_name: str | None = None

    @property
    def normalized_symbol(self) -> str:
        return normalize_symbol(self.symbol)

    @property
    def key(self) -> str:
        return f"{self.exchange.lower()}::{self.normalized_symbol}"


@dataclass
class UITickerPreference:
    key: str
    visible: bool = True
    order: int = 0
    pinned_title: bool = False


@dataclass
class ExchangeConfig:
    enabled: bool = True


@dataclass
class AppConfig:
    max_visible: int = 3
    title_index: int = 0
    display_fields: List[str] = field(default_factory=lambda: list(DEFAULT_DISPLAY_FIELDS))
    format_mode: str = DEFAULT_FORMAT_MODE
    title_template: str = DEFAULT_TITLE_TEMPLATE
    menu_template: str = DEFAULT_MENU_TEMPLATE
    icon_style: str = DEFAULT_ICON_STYLE
    exchange_icons: Dict[str, str] = field(default_factory=lambda: dict(EXCHANGE_ICON_PRESETS[DEFAULT_ICON_STYLE]))
    show_exchange_links: bool = True
    ticker_preferences: Dict[str, UITickerPreference] = field(default_factory=dict)
    ui_refresh_interval: float = PERFORMANCE_PRESETS[DEFAULT_PERFORMANCE_MODE]
    performance_mode: str = DEFAULT_PERFORMANCE_MODE
    language: str = DEFAULT_LANGUAGE
    exchanges: Dict[str, ExchangeConfig] = field(default_factory=lambda: {name: ExchangeConfig(enabled=True) for name in SUPPORTED_EXCHANGES})
    tickers: List[TickerConfig] = field(default_factory=list)
    exchange_short_names: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_EXCHANGE_SHORT_NAMES))

    @classmethod
    def default(cls) -> "AppConfig":
        ticker_items = get_default_tickers()
        preferences: Dict[str, UITickerPreference] = {}
        for index, ticker in enumerate(ticker_items):
            preferences[ticker.key.lower()] = UITickerPreference(
                key=ticker.key.lower(),
                visible=True,
                order=index,
                pinned_title=index == 0,
            )
        return cls(
            max_visible=4,
            title_index=0,
            display_fields=list(DEFAULT_DISPLAY_FIELDS),
            format_mode=DEFAULT_FORMAT_MODE,
            title_template=FORMAT_PRESETS[DEFAULT_FORMAT_MODE]["title_template"],
            menu_template=FORMAT_PRESETS[DEFAULT_FORMAT_MODE]["menu_template"],
            icon_style=DEFAULT_ICON_STYLE,
            exchange_icons=dict(EXCHANGE_ICON_PRESETS[DEFAULT_ICON_STYLE]),
            show_exchange_links=True,
            ticker_preferences=preferences,
            ui_refresh_interval=PERFORMANCE_PRESETS[DEFAULT_PERFORMANCE_MODE],
            performance_mode=DEFAULT_PERFORMANCE_MODE,
            language=DEFAULT_LANGUAGE,
            exchanges={name: ExchangeConfig(enabled=True) for name in SUPPORTED_EXCHANGES},
            tickers=ticker_items,
            exchange_short_names=dict(DEFAULT_EXCHANGE_SHORT_NAMES),
        )


def normalize_symbol(symbol: str) -> str:
    return (symbol or "").strip().upper().replace("_", "-")


def get_default_tickers() -> List[TickerConfig]:
    return [
        TickerConfig(exchange=exchange, symbol=symbol, display_name=display_name)
        for exchange, symbol, display_name in DEFAULT_TICKERS
    ]


def _normalize_performance_mode(mode: object) -> str:
    mode_str = str(mode or DEFAULT_PERFORMANCE_MODE).strip().lower()
    return mode_str if mode_str in PERFORMANCE_PRESETS else DEFAULT_PERFORMANCE_MODE


def _normalize_language(language: object) -> str:
    value = str(language or DEFAULT_LANGUAGE).strip()
    return value if value in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def _normalize_format_mode(mode: object) -> str:
    value = str(mode or DEFAULT_FORMAT_MODE).strip().lower()
    return value if value in FORMAT_PRESETS else DEFAULT_FORMAT_MODE


def _normalize_icon_style(style: object) -> str:
    value = str(style or DEFAULT_ICON_STYLE).strip().lower()
    return value if value in EXCHANGE_ICON_PRESETS else DEFAULT_ICON_STYLE


def _resolve_refresh_interval(ui: dict, default_config: AppConfig) -> tuple[str, float]:
    mode = _normalize_performance_mode(ui.get("performance_mode", default_config.performance_mode))
    raw_value = ui.get("ui_refresh_interval", default_config.ui_refresh_interval)
    try:
        custom_value = max(0.05, float(raw_value))
    except (TypeError, ValueError):
        custom_value = default_config.ui_refresh_interval
    preset_value = PERFORMANCE_PRESETS.get(mode)
    return mode, (custom_value if preset_value is None else float(preset_value))


def _resolve_templates(ui: dict, default_config: AppConfig) -> tuple[str, str, str]:
    format_mode = _normalize_format_mode(ui.get("format_mode", default_config.format_mode))
    preset = FORMAT_PRESETS[format_mode]
    if format_mode == "custom":
        title_template = str(ui.get("title_template", default_config.title_template))
        menu_template = str(ui.get("menu_template", default_config.menu_template))
    else:
        title_template = preset["title_template"]
        menu_template = preset["menu_template"]
    return format_mode, title_template, menu_template


def _load_exchange_configs(raw: object, fallback: Dict[str, ExchangeConfig]) -> Dict[str, ExchangeConfig]:
    configs = {name: ExchangeConfig(enabled=config.enabled) for name, config in fallback.items()}
    if not isinstance(raw, dict):
        return configs
    for name in SUPPORTED_EXCHANGES:
        item = raw.get(name)
        if isinstance(item, dict):
            configs[name] = ExchangeConfig(enabled=bool(item.get("enabled", configs[name].enabled)))
    return configs


def _load_exchange_short_names(raw: object, fallback: Dict[str, str]) -> Dict[str, str]:
    names = dict(fallback)
    if not isinstance(raw, dict):
        return names
    for exchange in SUPPORTED_EXCHANGES:
        value = str(raw.get(exchange, names.get(exchange, ""))).strip()
        if value:
            names[exchange] = value
    return names


def _load_exchange_icons(raw: object, icon_style: str) -> Dict[str, str]:
    icons = dict(EXCHANGE_ICON_PRESETS.get(icon_style, EXCHANGE_ICON_PRESETS[DEFAULT_ICON_STYLE]))
    if not isinstance(raw, dict):
        return icons
    for exchange in SUPPORTED_EXCHANGES:
        icons[exchange] = str(raw.get(exchange, icons.get(exchange, "")))
    return icons


def _load_ticker_configs(raw_tickers: object) -> List[TickerConfig]:
    if not isinstance(raw_tickers, list):
        return get_default_tickers()
    items: List[TickerConfig] = []
    for item in raw_tickers:
        if not isinstance(item, dict):
            continue
        exchange = str(item.get("exchange", "")).strip().lower()
        symbol = normalize_symbol(str(item.get("symbol", "")))
        if exchange not in SUPPORTED_EXCHANGES or not symbol:
            continue
        items.append(
            TickerConfig(
                exchange=exchange,
                symbol=symbol,
                enabled=bool(item.get("enabled", True)),
                display_name=(str(item.get("display_name", "")).strip() or None),
            )
        )
    return items or get_default_tickers()


def _sanitize_display_fields(fields: List[str]) -> List[str]:
    valid = [field for field in fields if field in SUPPORTED_FIELDS]
    return valid or list(DEFAULT_DISPLAY_FIELDS)


def _load_ticker_preferences(raw_tickers: object, fallback: Dict[str, UITickerPreference]) -> Dict[str, UITickerPreference]:
    if not isinstance(raw_tickers, list):
        return dict(fallback)
    preferences: Dict[str, UITickerPreference] = {}
    for index, item in enumerate(raw_tickers):
        if not isinstance(item, dict):
            continue
        if "key" in item:
            key = str(item.get("key", "")).strip().lower()
        else:
            exchange = str(item.get("exchange", "")).strip().lower()
            symbol = normalize_symbol(str(item.get("symbol", "")))
            key = f"{exchange}::{symbol}" if exchange and symbol else ""
        if not key:
            continue
        preferences[key] = UITickerPreference(
            key=key,
            visible=bool(item.get("visible", True)),
            order=int(item.get("order", index)),
            pinned_title=bool(item.get("pinned_title", False)),
        )
    merged = dict(fallback)
    merged.update(preferences)
    return merged


def _serialize_tickers(tickers: List[TickerConfig]) -> List[Dict[str, object]]:
    return [
        {
            "exchange": ticker.exchange,
            "symbol": ticker.normalized_symbol,
            "display_name": ticker.display_name,
            "enabled": ticker.enabled,
        }
        for ticker in tickers
    ]


def _serialize_default_config(default_config: AppConfig) -> Dict[str, object]:
    return {
        "ui": {
            "language": default_config.language,
            "max_visible": default_config.max_visible,
            "title_index": default_config.title_index,
            "display_fields": list(default_config.display_fields),
            "format_mode": default_config.format_mode,
            "title_template": default_config.title_template,
            "menu_template": default_config.menu_template,
            "template_examples": list(TEMPLATE_EXAMPLES),
            "template_variables": list(TEMPLATE_VARIABLES),
            "icon_style_options": dict(ICON_STYLE_OPTIONS),
            "exchange_icons": dict(default_config.exchange_icons),
            "official_exchange_icon_urls": dict(OFFICIAL_EXCHANGE_ICON_URLS),
            "show_exchange_links": default_config.show_exchange_links,
            "performance_mode": default_config.performance_mode,
            "ui_refresh_interval": default_config.ui_refresh_interval,
            "exchanges": {name: asdict(config) for name, config in default_config.exchanges.items()},
            "exchange_short_names": dict(default_config.exchange_short_names),
            "tickers": _serialize_tickers(default_config.tickers),
            "ticker_preferences": [
                {
                    "key": pref.key,
                    "visible": pref.visible,
                    "order": pref.order,
                    "pinned_title": pref.pinned_title,
                }
                for pref in sorted(default_config.ticker_preferences.values(), key=lambda item: item.order)
            ],
        }
    }


def _build_app_config(raw: Dict[str, object], default_config: AppConfig) -> AppConfig:
    ui = raw.get("ui") or raw
    if not isinstance(ui, dict):
        ui = {}

    performance_mode, ui_refresh_interval = _resolve_refresh_interval(ui, default_config)
    format_mode, title_template, menu_template = _resolve_templates(ui, default_config)
    icon_style = _normalize_icon_style(ui.get("icon_style", default_config.icon_style))
    tickers = _load_ticker_configs(ui.get("tickers"))
    fallback_prefs: Dict[str, UITickerPreference] = {}
    for index, ticker in enumerate(tickers):
        existing = default_config.ticker_preferences.get(ticker.key.lower())
        fallback_prefs[ticker.key.lower()] = UITickerPreference(
            key=ticker.key.lower(),
            visible=existing.visible if existing else True,
            order=existing.order if existing else index,
            pinned_title=existing.pinned_title if existing else index == 0,
        )

    display_fields = ui.get("display_fields", default_config.display_fields)
    if not isinstance(display_fields, list):
        display_fields = list(default_config.display_fields)

    max_visible_raw = ui.get("max_visible", default_config.max_visible)
    title_index_raw = ui.get("title_index", default_config.title_index)
    try:
        max_visible = max(1, int(max_visible_raw))
    except (TypeError, ValueError):
        max_visible = default_config.max_visible
    try:
        title_index = max(0, int(title_index_raw))
    except (TypeError, ValueError):
        title_index = default_config.title_index

    return AppConfig(
        max_visible=max_visible,
        title_index=title_index,
        display_fields=_sanitize_display_fields(display_fields),
        format_mode=format_mode,
        title_template=title_template,
        menu_template=menu_template,
        icon_style=icon_style,
        exchange_icons=_load_exchange_icons(ui.get("exchange_icons"), icon_style),
        show_exchange_links=bool(ui.get("show_exchange_links", default_config.show_exchange_links)),
        ticker_preferences=_load_ticker_preferences(ui.get("ticker_preferences") or ui.get("tickers"), fallback_prefs),
        ui_refresh_interval=ui_refresh_interval,
        performance_mode=performance_mode,
        language=_normalize_language(ui.get("language", default_config.language)),
        exchanges=_load_exchange_configs(ui.get("exchanges"), default_config.exchanges),
        tickers=tickers,
        exchange_short_names=_load_exchange_short_names(ui.get("exchange_short_names"), default_config.exchange_short_names),
    )


def _write_default_config(config_path: Path, default_config: AppConfig) -> None:
    with config_path.open("w", encoding="utf-8") as fp:
        json.dump(_serialize_default_config(default_config), fp, ensure_ascii=False, indent=2)


def load_app_config(config_path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    default_config = AppConfig.default()
    if not config_path.exists():
        _write_default_config(config_path, default_config)
        logging.info(f"已生成默认配置文件: {config_path}")
        return default_config

    try:
        with config_path.open("r", encoding="utf-8") as fp:
            raw = json.load(fp)
    except Exception as e:
        logging.error(f"读取配置失败，使用默认配置: {e}\n{traceback.format_exc()}")
        return default_config

    if not isinstance(raw, dict):
        logging.warning("配置文件格式无效，使用默认配置")
        return default_config

    return _build_app_config(raw, default_config)
