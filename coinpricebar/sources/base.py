from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import threading
import time

from ..config import OFFICIAL_EXCHANGE_ICON_URLS, normalize_symbol


@dataclass
class MarketSnapshot:
    exchange: str
    symbol: str
    price: float = 0.0
    change: float = 0.0
    change_percent: float = 0.0
    status: str = ""
    is_first: bool = True
    has_error: bool = False
    display_name: str | None = None

    @property
    def key(self) -> str:
        return f"{self.exchange.lower()}::{normalize_symbol(self.symbol)}"


class BasePriceSource:
    source_name = "base"
    display_label = "Base"
    home_url = ""
    local_icon_name: str | None = None
    source_mode = "poll"
    menu_icon_style: dict[str, object] | None = None
    require_image_content_type = False
    retry_icon_download_on_load_failure = False

    def __init__(self, update_callback: Callable[[str, str, float], None], status_callback: Callable[[str, str], None]):
        self.update_callback = update_callback
        self.status_callback = status_callback
        self.running = False
        self.lock = threading.Lock()

    @classmethod
    def get_icon_url(cls) -> str:
        return OFFICIAL_EXCHANGE_ICON_URLS.get(cls.source_name, "")

    @classmethod
    def get_display_label(cls) -> str:
        return cls.display_label or cls.source_name.title()

    @classmethod
    def get_home_url(cls) -> str:
        return cls.home_url

    @classmethod
    def get_menu_icon_style(cls) -> dict[str, object] | None:
        return cls.menu_icon_style

    @classmethod
    def get_icon_request_headers(cls) -> dict[str, str]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        home_url = cls.get_home_url()
        if home_url:
            headers["Referer"] = home_url
        return headers

    @classmethod
    def accepts_icon_content_type(cls, content_type: str) -> bool:
        lowered = str(content_type or "").lower()
        return ("image" in lowered) if cls.require_image_content_type else True

    @classmethod
    def should_retry_icon_download_on_load_failure(cls) -> bool:
        return cls.retry_icon_download_on_load_failure

    @classmethod
    def get_local_icon_path(cls) -> Path | None:
        if not cls.local_icon_name:
            return None
        path = Path(__file__).resolve().parent / cls.local_icon_name
        return path if path.exists() and path.is_file() else None

    def start(self, symbols: list[str]) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def list_symbols(self) -> list[str]:
        return []

    @classmethod
    def build_trade_url(cls, symbol: str) -> str | None:
        return None

    def _wait_interval(self, interval_seconds: float) -> None:
        slept = 0.0
        while self.running and slept < interval_seconds:
            time_slice = min(0.25, interval_seconds - slept)
            threading.Event().wait(time_slice)
            slept += time_slice

    def _emit_price(self, symbol: str, price: float):
        self.update_callback(self.source_name, normalize_symbol(symbol), price)

    def _emit_status(self, status: str):
        self.status_callback(self.source_name, status)
