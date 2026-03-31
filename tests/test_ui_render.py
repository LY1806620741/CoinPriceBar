import unittest

from coinpricebar.app import CoinPriceBarApp, _with_trend_suffix
from coinpricebar.config import AppConfig, get_default_tickers
from coinpricebar.sources.base import MarketSnapshot


class DummyApp:
    pass


class UIRenderTests(unittest.TestCase):
    def setUp(self):
        self.app = DummyApp()
        self.app.config = AppConfig.default()
        self.app.config.display_fields = ["exchange", "symbol", "price", "change_percent"]
        self.app._menu_label = lambda exchange: exchange.title()
        self.app._format_change = lambda snapshot: CoinPriceBarApp._format_change(self.app, snapshot)
        self.app._build_display_context = lambda snapshot: CoinPriceBarApp._build_display_context(self.app, snapshot)

    def test_render_text_contains_up_down_arrows(self):
        rising = MarketSnapshot(exchange="kucoin", symbol="BTC-USDT", price=100.0, change=2.0, change_percent=2.0, is_first=False)
        falling = MarketSnapshot(exchange="binance", symbol="ETH-USDT", price=50.0, change=-1.5, change_percent=-3.0, is_first=False)

        rise_text = CoinPriceBarApp._render_text(self.app, rising, "{exchange}:{symbol} {price} {change_percent}")
        fall_text = CoinPriceBarApp._render_text(self.app, falling, "{exchange}:{symbol} {price} {change_percent}")

        self.assertIn("↑", rise_text)
        self.assertIn("↓", fall_text)

    def test_trend_suffix_contains_color_markers(self):
        self.assertIn("🟢", _with_trend_suffix("BTC 100", 1.0))
        self.assertIn("🔴", _with_trend_suffix("ETH 50", -1.0))

    def test_default_tickers_exist(self):
        self.assertGreaterEqual(len(get_default_tickers()), 2)


if __name__ == "__main__":
    unittest.main()
