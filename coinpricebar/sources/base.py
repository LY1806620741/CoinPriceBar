from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import threading

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
    local_icon_name: str | None = None

    def __init__(self, update_callback: Callable[[str, str, float], None], status_callback: Callable[[str, str], None]):
        self.update_callback = update_callback
        self.status_callback = status_callback
        self.running = False
        self.lock = threading.Lock()

    @classmethod
    def get_icon_url(cls) -> str:
        return OFFICIAL_EXCHANGE_ICON_URLS.get(cls.source_name, "")

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

    def _emit_price(self, symbol: str, price: float):
        self.update_callback(self.source_name, normalize_symbol(symbol), price)

    def _emit_status(self, status: str):
        self.status_callback(self.source_name, status)
