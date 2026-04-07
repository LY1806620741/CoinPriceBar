from .base import BasePriceSource, MarketSnapshot
from .binance import BinancePriceSource
from .binance_c2c import BinanceC2CPriceSource
from .binance_futures import BinanceFuturesPriceSource
from .kucoin import KucoinPriceSource
from .kucoin_futures import KucoinFuturesPriceSource
from .web3 import Web3PriceSource

SOURCE_REGISTRY = {
    KucoinPriceSource.source_name: KucoinPriceSource,
    BinancePriceSource.source_name: BinancePriceSource,
    BinanceC2CPriceSource.source_name: BinanceC2CPriceSource,
    KucoinFuturesPriceSource.source_name: KucoinFuturesPriceSource,
    BinanceFuturesPriceSource.source_name: BinanceFuturesPriceSource,
    Web3PriceSource.source_name: Web3PriceSource,
}


def get_source_class(exchange: str) -> type[BasePriceSource] | None:
    return SOURCE_REGISTRY.get(str(exchange or "").strip().lower())

__all__ = [
    "BasePriceSource",
    "MarketSnapshot",
    "SOURCE_REGISTRY",
    "get_source_class",
    "BinancePriceSource",
    "BinanceC2CPriceSource",
    "BinanceFuturesPriceSource",
    "KucoinPriceSource",
    "KucoinFuturesPriceSource",
    "Web3PriceSource",
]

