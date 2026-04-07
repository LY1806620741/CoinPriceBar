import json
import logging
from string import hexdigits
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..config import normalize_symbol
from .base import BasePriceSource

COINGECKO_SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
DEXSCREENER_PAIR_URL = "https://api.dexscreener.com/latest/dex/pairs"
WEB3_POLL_INTERVAL = 15.0
WEB3_QUOTE = "USD"
WEB3_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}
WEB3_TOKEN_CATALOG = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "SOL-USD": "solana",
    "BNB-USD": "binancecoin",
    "ARB-USD": "arbitrum",
    "OP-USD": "optimism",
    "AVAX-USD": "avalanche-2",
    "LINK-USD": "chainlink",
    "UNI-USD": "uniswap",
    "AAVE-USD": "aave",
}
WEB3_PAIR_EXAMPLES = [
    "PAIR:ETHEREUM:0XB26A868FFA4CBBA926970D7AE9C6A36D088EE38C",
    "PAIR:ETHEREUM:0X88E6A0C2DDD26FEEB64F039A2C41296FCB3F5640",
    "PAIR:ETHEREUM:0XB4E16D0168E52D35CACD2C6185B44281EC28C9DC",
]


def _normalize_evm_address(value: str) -> str:
    raw = str(value or "").strip()
    if raw.upper().startswith("0X"):
        raw = f"0x{raw[2:]}"
    elif raw and not raw.startswith("0x") and len(raw) == 40:
        raw = f"0x{raw}"
    return raw.lower()


def _is_evm_address(value: str) -> bool:
    normalized = _normalize_evm_address(value)
    return normalized.startswith("0x") and len(normalized) == 42 and all(char in hexdigits for char in normalized[2:])


def _read_json(url: str) -> dict | list:
    request = Request(url, headers=WEB3_HTTP_HEADERS)
    with urlopen(request, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


class Web3PriceSource(BasePriceSource):
    source_name = "web3"
    display_label = "Web3"
    home_url = "https://dexscreener.com/"
    source_mode = "poll"
    menu_icon_style = {"bg": (0.42, 0.27, 0.85, 1.0), "fg": (1.0, 1.0, 1.0, 1.0), "text": "W"}

    @classmethod
    def _resolve_pair_spec(cls, symbol: str) -> tuple[str, str] | None:
        raw_value = str(symbol or "").strip()
        if not raw_value:
            return None
        parts = raw_value.split(":", 2)
        if len(parts) != 3 or parts[0].strip().upper() != "PAIR":
            return None
        chain = parts[1].strip().lower()
        pair_address = _normalize_evm_address(parts[2])
        if not chain or not _is_evm_address(pair_address):
            return None
        return chain, pair_address

    @classmethod
    def _resolve_coin_id(cls, symbol: str) -> str | None:
        normalized = normalize_symbol(symbol)
        if normalized in WEB3_TOKEN_CATALOG:
            return WEB3_TOKEN_CATALOG[normalized]
        if normalized.startswith("CG-") and normalized.endswith(f"-{WEB3_QUOTE}"):
            raw_coin_id = normalized[3 : -len(f"-{WEB3_QUOTE}")].strip("-")
            return raw_coin_id.lower() or None
        return None

    @classmethod
    def build_trade_url(cls, symbol: str) -> str | None:
        pair_spec = cls._resolve_pair_spec(symbol)
        if pair_spec:
            chain, pair_address = pair_spec
            return f"https://dexscreener.com/{chain}/{pair_address}"
        coin_id = cls._resolve_coin_id(symbol)
        return f"https://www.coingecko.com/en/coins/{coin_id}" if coin_id else None

    def __init__(self, update_callback, status_callback):
        super().__init__(update_callback, status_callback)
        self.current_symbols: list[str] = []

    def _fetch_legacy_prices(self, symbols: list[str]) -> dict[str, float]:
        coin_ids: dict[str, str] = {}
        for symbol in symbols:
            coin_id = self._resolve_coin_id(symbol)
            if coin_id:
                coin_ids[symbol] = coin_id
        if not coin_ids:
            return {}

        query = urlencode(
            {
                "ids": ",".join(sorted(set(coin_ids.values()))),
                "vs_currencies": WEB3_QUOTE.lower(),
            }
        )
        payload = _read_json(f"{COINGECKO_SIMPLE_PRICE_URL}?{query}")

        prices: dict[str, float] = {}
        for symbol, coin_id in coin_ids.items():
            coin_payload = payload.get(coin_id) or {}
            value = coin_payload.get(WEB3_QUOTE.lower())
            if value is None:
                continue
            prices[symbol] = float(value)
        return prices

    def _fetch_pair_price(self, chain: str, pair_address: str) -> float | None:
        payload = _read_json(f"{DEXSCREENER_PAIR_URL}/{chain}/{pair_address}")
        pairs = payload.get("pairs") or []
        if not pairs:
            return None
        pair = next((item for item in pairs if _normalize_evm_address(str(item.get("pairAddress", ""))) == pair_address), pairs[0])
        value = pair.get("priceUsd")
        return float(value) if value is not None else None

    def _fetch_prices(self, symbols: list[str]) -> dict[str, float]:
        prices = self._fetch_legacy_prices(symbols)
        for symbol in symbols:
            pair_spec = self._resolve_pair_spec(symbol)
            if not pair_spec:
                continue
            chain, pair_address = pair_spec
            try:
                price = self._fetch_pair_price(chain, pair_address)
            except Exception as e:
                logging.warning(f"获取 Web3 DEX 行情失败: {symbol} -> {e}")
                continue
            if price is not None:
                prices[symbol] = price
        return prices

    def start(self, symbols: list[str]) -> None:
        with self.lock:
            if self.running:
                return
            self.running = True
            self.current_symbols = [normalize_symbol(symbol) for symbol in symbols]

        if not self.current_symbols:
            logging.info("Web3 未配置资产，跳过启动")
            self.running = False
            return

        self._emit_status("")
        try:
            while self.running:
                try:
                    prices = self._fetch_prices(self.current_symbols)
                    for symbol in self.current_symbols:
                        price = prices.get(symbol)
                        if price is not None and price > 0:
                            self._emit_price(symbol, price)
                    self._emit_status("")
                except Exception as e:
                    logging.warning(f"获取 Web3 行情失败: {e}")
                    self._emit_status("⚫")
                self._wait_interval(WEB3_POLL_INTERVAL)
        finally:
            self.running = False

    def stop(self) -> None:
        with self.lock:
            self.running = False

    def list_symbols(self) -> list[str]:
        return sorted([*WEB3_TOKEN_CATALOG, *WEB3_PAIR_EXAMPLES])

