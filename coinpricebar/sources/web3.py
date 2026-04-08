import json
import logging
import time
from dataclasses import dataclass
from string import hexdigits
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..config import normalize_symbol
from .base import BasePriceSource

COINGECKO_SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
DEXSCREENER_PAIR_URL = "https://api.dexscreener.com/latest/dex/pairs"
DEXSCREENER_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens"
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
WEB3_DEX_MARKET_EXAMPLES = [
    "DEX:AUTO:ETHEREUM:0XF34960D9D60BE18CC1D5AFC1A6F012A723A28811",
    "DEX:UNISWAP:ETHEREUM:0XF34960D9D60BE18CC1D5AFC1A6F012A723A28811:WETH",
    "DEX:UNISWAP:ETHEREUM:0XF34960D9D60BE18CC1D5AFC1A6F012A723A28811:USDC",
]
WEB3_SYMBOL_PLACEHOLDER = "ETH-USD / PAIR:ETHEREUM:0xPAIR / DEX:UNISWAP:ETHEREUM:0xTOKEN[:WETH]"
WEB3_SUPPORTED_CHAINS = ["ethereum", "base", "bsc", "arbitrum", "optimism", "polygon", "avalanche"]
WEB3_SUPPORTED_DEXES = ["auto", "uniswap", "sushiswap", "pancakeswap", "curve", "aerodrome", "camelot", "velodrome", "traderjoe"]
WEB3_QUOTE_EXAMPLES = ["WETH", "USDC", "USDT", "WBTC"]
WEB3_QUOTE_USD_PEGS = {
    "USDT": 1.0,
    "USDC": 1.0,
    "DAI": 1.0,
}
WEB3_QUOTE_COIN_IDS = {
    "USDT": "tether",
    "USDC": "usd-coin",
    "DAI": "dai",
    "WETH": "ethereum",
    "ETH": "ethereum",
    "WBTC": "wrapped-bitcoin",
    "BTC": "bitcoin",
}
WEB3_QUOTE_PRICE_TTL = 60.0
UNISWAP_EXPLORE_TOKENS_URL = "https://app.uniswap.org/explore/tokens"
UNISWAP_CHAIN_PATHS = {
    "ethereum": "ethereum",
    "base": "base",
    "arbitrum": "arbitrum",
    "optimism": "optimism",
    "polygon": "polygon",
    "avalanche": "avalanche",
}
UNISWAP_QUOTE_TOKEN_ADDRESSES = {
    "ethereum": {
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
    },
    "base": {
        "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "WETH": "0x4200000000000000000000000000000000000006",
    },
    "arbitrum": {
        "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        "USDT": "0xFd086bC7CD5C481DCC9C85ebe478A1C0b69FCbb9",
        "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        "WBTC": "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f",
    },
    "optimism": {
        "USDC": "0x0b2C639c533813f4Aa9D7837CaF62653d097Ff85",
        "USDT": "0x94b008aA00579c1307B0EF2c499AD98a8ce58e58",
        "WETH": "0x4200000000000000000000000000000000000006",
        "WBTC": "0x68f180fcCe6836688e9084f035309E29bf0A2095",
    },
    "polygon": {
        "USDC": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
        "USDT": "0xc2132D05D31c914a87C6611C10748AaCbC532Db",
        "WETH": "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        "WBTC": "0x1BFD67037B42Cf73acF2047067bd4F2C47D9BfD6",
    },
    "avalanche": {
        "USDC": "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E",
        "USDT": "0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7",
        "WETH": "0x49D5c2BdFfac6CE2BFdB6640F4F80f226bc10bAB",
        "WBTC": "0x50b7545627a5162F82A992c33b87aDc75187B218",
    },
}


@dataclass(frozen=True)
class DexMarketSpec:
    market: str
    chain: str
    token_address: str
    quote_filter: str | None = None


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


def _normalize_market_id(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _normalize_quote_filter(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if _is_evm_address(raw):
        return _normalize_evm_address(raw)
    return raw.upper().replace("-", "")


def _pair_liquidity_usd(pair: dict) -> float:
    liquidity = pair.get("liquidity") or {}
    value = liquidity.get("usd") or 0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_float(value: object) -> float | None:
    try:
        if value in {None, ""}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_uniswap_quote_address(chain: str, quote_filter: str | None) -> str | None:
    normalized_chain = _normalize_market_id(chain)
    normalized_quote = _normalize_quote_filter(quote_filter)
    if not normalized_quote:
        return None
    if _is_evm_address(normalized_quote):
        return _normalize_evm_address(normalized_quote)
    mapped = UNISWAP_QUOTE_TOKEN_ADDRESSES.get(normalized_chain, {}).get(normalized_quote)
    return _normalize_evm_address(mapped) if mapped else None


def _resolve_known_quote_symbol(chain: str, quote_filter: str | None) -> str | None:
    normalized_quote = _normalize_quote_filter(quote_filter)
    if not normalized_quote:
        return None
    if not _is_evm_address(normalized_quote):
        return normalized_quote
    normalized_chain = _normalize_market_id(chain)
    for symbol, address in UNISWAP_QUOTE_TOKEN_ADDRESSES.get(normalized_chain, {}).items():
        if _normalize_evm_address(address) == normalized_quote:
            return symbol
    return None


def _build_uniswap_trade_url(chain: str, output_token_address: str, quote_filter: str | None = None) -> str | None:
    chain_path = UNISWAP_CHAIN_PATHS.get(_normalize_market_id(chain))
    output_address = _normalize_evm_address(output_token_address)
    if not chain_path or not _is_evm_address(output_address):
        return None
    params = {
        "inputCurrency": output_address,
    }
    quote_address = _resolve_uniswap_quote_address(chain, quote_filter)
    if quote_address:
        params["outputCurrency"] = quote_address
    return f"{UNISWAP_EXPLORE_TOKENS_URL}/{chain_path}/{output_address}?{urlencode(params)}"


def _fetch_simple_usd_prices(coin_ids: list[str]) -> dict[str, float]:
    unique_ids = sorted({str(item).strip().lower() for item in coin_ids if str(item).strip()})
    if not unique_ids:
        return {}
    query = urlencode(
        {
            "ids": ",".join(unique_ids),
            "vs_currencies": WEB3_QUOTE.lower(),
        }
    )
    payload = _read_json(f"{COINGECKO_SIMPLE_PRICE_URL}?{query}")
    prices: dict[str, float] = {}
    for coin_id in unique_ids:
        value = (payload.get(coin_id) or {}).get(WEB3_QUOTE.lower())
        if value is None:
            continue
        prices[coin_id] = float(value)
    return prices


class Web3PriceSource(BasePriceSource):
    source_name = "web3"
    display_label = "Web3"
    home_url = "https://dexscreener.com/"
    source_mode = "poll"
    menu_icon_style = {"bg": (0.42, 0.27, 0.85, 1.0), "fg": (1.0, 1.0, 1.0, 1.0), "text": "W"}

    @classmethod
    def get_symbol_schema(cls) -> dict[str, object]:
        return {
            "symbol_placeholder": WEB3_SYMBOL_PLACEHOLDER,
            "symbol_help": "支持三种格式：1) CoinGecko 代币，如 ETH-USD / CG-BITCOIN-USD；2) 精确池地址，如 PAIR:<chain>:<pairAddress>；3) 指定 DEX 市场，如 DEX:<dexId|AUTO>:<chain>:<tokenAddress>[:quoteSymbol|quoteTokenAddress]。示例：DEX:UNISWAP:ETHEREUM:0xTOKEN:WETH。",
            "examples": list(cls.list_symbol_examples()),
            "editor": {
                "modes": [
                    {"value": "token", "label": "CoinGecko Token"},
                    {"value": "pair", "label": "Exact Pair"},
                    {"value": "dex", "label": "DEX Market"},
                ],
                "chains": list(WEB3_SUPPORTED_CHAINS),
                "dexes": list(WEB3_SUPPORTED_DEXES),
                "quote_examples": list(WEB3_QUOTE_EXAMPLES),
            },
        }

    @classmethod
    def list_symbol_examples(cls) -> list[str]:
        return [*WEB3_TOKEN_CATALOG, *WEB3_PAIR_EXAMPLES, *WEB3_DEX_MARKET_EXAMPLES]

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
    def _resolve_dex_market_spec(cls, symbol: str) -> DexMarketSpec | None:
        raw_value = str(symbol or "").strip()
        if not raw_value:
            return None
        parts = raw_value.split(":")
        if len(parts) not in {4, 5} or parts[0].strip().upper() != "DEX":
            return None
        market = _normalize_market_id(parts[1])
        chain = parts[2].strip().lower()
        token_address = _normalize_evm_address(parts[3])
        quote_filter = _normalize_quote_filter(parts[4]) if len(parts) == 5 else None
        if not market or not chain or not _is_evm_address(token_address):
            return None
        return DexMarketSpec(market=market, chain=chain, token_address=token_address, quote_filter=quote_filter)

    @classmethod
    def _pair_matches_market_spec(cls, pair: dict, spec: DexMarketSpec) -> bool:
        if _normalize_market_id(pair.get("chainId")) != spec.chain:
            return False
        base_token = pair.get("baseToken") or {}
        if _normalize_evm_address(base_token.get("address", "")) != spec.token_address:
            return False
        if spec.market not in {"auto", "best"} and _normalize_market_id(pair.get("dexId")) != spec.market:
            return False
        if not spec.quote_filter:
            return True
        quote_token = pair.get("quoteToken") or {}
        quote_address = _normalize_evm_address(quote_token.get("address", ""))
        quote_symbol = str(quote_token.get("symbol", "")).strip().upper().replace("-", "")
        return spec.quote_filter in {quote_address, quote_symbol}

    @classmethod
    def _pick_best_market_pair(cls, pairs: list[dict], spec: DexMarketSpec) -> dict | None:
        candidates = [pair for pair in pairs if cls._pair_matches_market_spec(pair, spec)]
        if not candidates:
            return None
        candidates.sort(key=lambda item: (_pair_liquidity_usd(item), _safe_float(item.get("priceUsd")) or 0.0), reverse=True)
        return candidates[0]

    @classmethod
    def _fetch_token_pairs(cls, token_address: str) -> list[dict]:
        payload = _read_json(f"{DEXSCREENER_TOKEN_URL}/{token_address}")
        return payload.get("pairs") or []

    @classmethod
    def _fetch_pair_details(cls, chain: str, pair_address: str) -> dict | None:
        payload = _read_json(f"{DEXSCREENER_PAIR_URL}/{chain}/{pair_address}")
        pairs = payload.get("pairs") or []
        if not pairs:
            return None
        normalized_address = _normalize_evm_address(pair_address)
        return next((item for item in pairs if _normalize_evm_address(str(item.get("pairAddress", ""))) == normalized_address), pairs[0])

    @classmethod
    def _serialize_market_candidate(cls, pair: dict) -> dict[str, object] | None:
        chain = _normalize_market_id(pair.get("chainId"))
        dex = _normalize_market_id(pair.get("dexId"))
        pair_address = _normalize_evm_address(pair.get("pairAddress", ""))
        base_token = pair.get("baseToken") or {}
        quote_token = pair.get("quoteToken") or {}
        base_address = _normalize_evm_address(base_token.get("address", ""))
        if not chain or not dex or not _is_evm_address(pair_address) or not _is_evm_address(base_address):
            return None
        quote_symbol = str(quote_token.get("symbol", "")).strip().upper()
        suggested_dex_symbol = f"DEX:{dex.upper()}:{chain.upper()}:{base_address.upper()}"
        if quote_symbol:
            suggested_dex_symbol = f"{suggested_dex_symbol}:{quote_symbol}"
        trade_url = _build_uniswap_trade_url(chain, base_address, quote_token.get("address") or quote_symbol) if dex == "uniswap" else None
        return {
            "chain": chain,
            "dex": dex,
            "pair_address": pair_address,
            "base_symbol": str(base_token.get("symbol", "")).strip().upper(),
            "base_address": base_address,
            "quote_symbol": quote_symbol,
            "quote_address": _normalize_evm_address(quote_token.get("address", "")),
            "price_usd": _safe_float(pair.get("priceUsd")),
            "price_native": _safe_float(pair.get("priceNative")),
            "liquidity_usd": _pair_liquidity_usd(pair),
            "trade_url": str(trade_url or pair.get("url") or f"https://dexscreener.com/{chain}/{pair_address}"),
            "suggested_pair_symbol": f"PAIR:{chain.upper()}:{pair_address.upper()}",
            "suggested_dex_symbol": suggested_dex_symbol,
        }

    @classmethod
    def list_market_candidates(
        cls,
        token_address: str,
        chain: str | None = None,
        market: str | None = None,
        quote_filter: str | None = None,
    ) -> list[dict[str, object]]:
        normalized_token = _normalize_evm_address(token_address)
        if not _is_evm_address(normalized_token):
            return []
        normalized_chain = _normalize_market_id(chain or "")
        normalized_market = _normalize_market_id(market or "")
        normalized_quote = _normalize_quote_filter(quote_filter)
        candidates: list[dict[str, object]] = []
        for pair in cls._fetch_token_pairs(normalized_token):
            item = cls._serialize_market_candidate(pair)
            if not item:
                continue
            if normalized_chain and item["chain"] != normalized_chain:
                continue
            if normalized_market and normalized_market not in {"auto", "best"} and item["dex"] != normalized_market:
                continue
            if normalized_quote and normalized_quote not in {item["quote_symbol"], item["quote_address"]}:
                continue
            candidates.append(item)
        candidates.sort(
            key=lambda item: (
                1 if normalized_chain and item["chain"] == normalized_chain else 0,
                1 if normalized_market and normalized_market not in {"auto", "best"} and item["dex"] == normalized_market else 0,
                1 if normalized_quote and normalized_quote in {item["quote_symbol"], item["quote_address"]} else 0,
                item["liquidity_usd"] or 0.0,
                item["price_usd"] or 0.0,
            ),
            reverse=True,
        )
        return candidates

    @classmethod
    def build_trade_url(cls, symbol: str) -> str | None:
        pair_spec = cls._resolve_pair_spec(symbol)
        if pair_spec:
            chain, pair_address = pair_spec
            try:
                pair = cls._fetch_pair_details(chain, pair_address)
            except Exception as e:
                logging.debug(f"构造 Web3 Pair 交易链接失败，回退 pair 页面: {symbol} -> {e}")
                pair = None
            if pair and _normalize_market_id(pair.get("dexId")) == "uniswap":
                base_token = pair.get("baseToken") or {}
                quote_token = pair.get("quoteToken") or {}
                uniswap_url = _build_uniswap_trade_url(chain, base_token.get("address", ""), quote_token.get("address") or quote_token.get("symbol"))
                if uniswap_url:
                    return uniswap_url
            return f"https://dexscreener.com/{chain}/{pair_address}"
        market_spec = cls._resolve_dex_market_spec(symbol)
        if market_spec:
            if market_spec.market == "uniswap":
                uniswap_url = _build_uniswap_trade_url(market_spec.chain, market_spec.token_address, market_spec.quote_filter)
                if uniswap_url:
                    return uniswap_url
            try:
                pair = cls._pick_best_market_pair(cls._fetch_token_pairs(market_spec.token_address), market_spec)
            except Exception as e:
                logging.debug(f"构造 Web3 DEX 市场链接失败，回退 token 页面: {symbol} -> {e}")
                pair = None
            if pair and pair.get("url"):
                return str(pair.get("url"))
            return f"https://dexscreener.com/{market_spec.chain}/{market_spec.token_address}"
        coin_id = cls._resolve_coin_id(symbol)
        return f"https://www.coingecko.com/en/coins/{coin_id}" if coin_id else None

    def __init__(self, update_callback, status_callback):
        super().__init__(update_callback, status_callback)
        self.current_symbols: list[str] = []
        self.quote_usd_cache: dict[str, tuple[float, float]] = {}

    def _fetch_legacy_prices(self, symbols: list[str]) -> dict[str, float]:
        coin_ids: dict[str, str] = {}
        for symbol in symbols:
            coin_id = self._resolve_coin_id(symbol)
            if coin_id:
                coin_ids[symbol] = coin_id
        if not coin_ids:
            return {}
        payload_prices = _fetch_simple_usd_prices(list(coin_ids.values()))

        prices: dict[str, float] = {}
        for symbol, coin_id in coin_ids.items():
            value = payload_prices.get(coin_id)
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

    def _extract_market_price(self, pair: dict, spec: DexMarketSpec) -> float | None:
        preferred_value = pair.get("priceNative") if spec.quote_filter else pair.get("priceUsd")
        fallback_value = pair.get("priceUsd")
        for raw_value in (preferred_value, fallback_value):
            if raw_value in {None, ""}:
                continue
            try:
                return float(raw_value)
            except (TypeError, ValueError):
                continue
        return None

    def _quote_usd_price(self, chain: str, quote_filter: str | None) -> float | None:
        quote_symbol = _resolve_known_quote_symbol(chain, quote_filter)
        if not quote_symbol:
            return None
        cached = self.quote_usd_cache.get(quote_symbol)
        now = time.monotonic()
        if cached and now - cached[0] < WEB3_QUOTE_PRICE_TTL:
            return cached[1]
        return WEB3_QUOTE_USD_PEGS.get(quote_symbol)

    def _refresh_quote_usd_prices(self, quote_symbols: list[str]) -> None:
        now = time.monotonic()
        pending_symbols = []
        coin_ids = []
        for symbol in sorted({str(item).strip().upper() for item in quote_symbols if str(item).strip()}):
            cached = self.quote_usd_cache.get(symbol)
            if cached and now - cached[0] < WEB3_QUOTE_PRICE_TTL:
                continue
            coin_id = WEB3_QUOTE_COIN_IDS.get(symbol)
            if not coin_id:
                continue
            pending_symbols.append(symbol)
            coin_ids.append(coin_id)
        if not coin_ids:
            return
        try:
            usd_prices = _fetch_simple_usd_prices(coin_ids)
        except Exception as e:
            logging.debug(f"刷新 Web3 quote USD 价格失败: {e}")
            return
        symbol_to_coin_id = {symbol: WEB3_QUOTE_COIN_IDS[symbol] for symbol in pending_symbols}
        for symbol, coin_id in symbol_to_coin_id.items():
            value = usd_prices.get(coin_id)
            if value is None:
                continue
            self.quote_usd_cache[symbol] = (now, float(value))

    def _reference_market_price(self, pairs: list[dict], spec: DexMarketSpec) -> float | None:
        reference_spec = DexMarketSpec(
            market=spec.market,
            chain=spec.chain,
            token_address=spec.token_address,
            quote_filter=None,
        )
        pair = self._pick_best_market_pair(pairs, reference_spec)
        if not pair:
            return None
        return _safe_float(pair.get("priceUsd"))

    def _reference_market_pair(self, pairs: list[dict], spec: DexMarketSpec) -> dict | None:
        reference_spec = DexMarketSpec(
            market=spec.market,
            chain=spec.chain,
            token_address=spec.token_address,
            quote_filter=None,
        )
        return self._pick_best_market_pair(pairs, reference_spec)

    def _route_quote_via_reference_pair(
        self,
        token_pairs_cache: dict[str, list[dict]],
        reference_pair: dict,
        spec: DexMarketSpec,
    ) -> float | None:
        native_price = _safe_float(reference_pair.get("priceNative"))
        if native_price in {None, 0}:
            return None
        quote_token = reference_pair.get("quoteToken") or {}
        quote_token_address = _normalize_evm_address(quote_token.get("address", ""))
        if not _is_evm_address(quote_token_address) or not spec.quote_filter:
            return None
        route_spec = DexMarketSpec(
            market=spec.market,
            chain=spec.chain,
            token_address=quote_token_address,
            quote_filter=spec.quote_filter,
        )
        route_pairs = token_pairs_cache.get(quote_token_address)
        if route_pairs is None:
            route_pairs = self._fetch_token_pairs(quote_token_address)
            token_pairs_cache[quote_token_address] = route_pairs
        route_pair = self._pick_best_market_pair(route_pairs, route_spec)
        if not route_pair:
            return None
        quote_price = self._extract_market_price(route_pair, route_spec)
        if quote_price in {None, 0}:
            return None
        return native_price * quote_price

    def _resolve_market_price(self, pairs: list[dict], spec: DexMarketSpec, token_pairs_cache: dict[str, list[dict]]) -> float | None:
        pair = self._pick_best_market_pair(pairs, spec)
        if pair:
            price = self._extract_market_price(pair, spec)
            if price is not None:
                return price
        if not spec.quote_filter:
            return None
        reference_pair = self._reference_market_pair(pairs, spec)
        if reference_pair is not None:
            routed_price = self._route_quote_via_reference_pair(token_pairs_cache, reference_pair, spec)
            if routed_price is not None:
                return routed_price
        base_price_usd = self._reference_market_price(pairs, spec)
        quote_price_usd = self._quote_usd_price(spec.chain, spec.quote_filter)
        if base_price_usd is None or quote_price_usd in {None, 0}:
            return None
        return base_price_usd / quote_price_usd

    def _fetch_prices(self, symbols: list[str]) -> dict[str, float]:
        prices = self._fetch_legacy_prices(symbols)
        token_pairs_cache: dict[str, list[dict]] = {}
        routed_quote_symbols = []
        for symbol in symbols:
            market_spec = self._resolve_dex_market_spec(symbol)
            if not market_spec or not market_spec.quote_filter:
                continue
            quote_symbol = _resolve_known_quote_symbol(market_spec.chain, market_spec.quote_filter)
            if quote_symbol:
                routed_quote_symbols.append(quote_symbol)
        self._refresh_quote_usd_prices(routed_quote_symbols)
        for symbol in symbols:
            pair_spec = self._resolve_pair_spec(symbol)
            if pair_spec:
                chain, pair_address = pair_spec
                try:
                    price = self._fetch_pair_price(chain, pair_address)
                except Exception as e:
                    logging.warning(f"获取 Web3 DEX 行情失败: {symbol} -> {e}")
                    continue
                if price is not None:
                    prices[symbol] = price
                continue

            market_spec = self._resolve_dex_market_spec(symbol)
            if not market_spec:
                continue
            try:
                pairs = token_pairs_cache.get(market_spec.token_address)
                if pairs is None:
                    pairs = self._fetch_token_pairs(market_spec.token_address)
                    token_pairs_cache[market_spec.token_address] = pairs
                price = self._resolve_market_price(pairs, market_spec, token_pairs_cache)
            except Exception as e:
                logging.warning(f"获取 Web3 市场行情失败: {symbol} -> {e}")
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
        return sorted(self.list_symbol_examples())

