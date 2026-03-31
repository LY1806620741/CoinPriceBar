import unittest

from coinpricebar.app import CoinPriceBarApp, _with_trend_suffix
from coinpricebar.config import AppConfig, SUPPORTED_EXCHANGES, _build_app_config, get_default_tickers
from coinpricebar.sources import BinancePriceSource, KucoinPriceSource
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

    def test_default_config_contains_update_tuning_fields(self):
        config = AppConfig.default()
        self.assertGreaterEqual(config.ui_refresh_interval, 0.05)
        self.assertEqual(config.performance_mode, "balanced")

    def test_performance_preset_overrides_refresh_interval(self):
        config = _build_app_config({"ui": {"performance_mode": "stable", "ui_refresh_interval": 0.1}}, AppConfig.default())
        self.assertEqual(config.performance_mode, "stable")
        self.assertEqual(config.ui_refresh_interval, 0.5)

    def test_custom_performance_mode_uses_numeric_value(self):
        config = _build_app_config({"ui": {"performance_mode": "custom", "ui_refresh_interval": 0.18}}, AppConfig.default())
        self.assertEqual(config.performance_mode, "custom")
        self.assertEqual(config.ui_refresh_interval, 0.18)

    def test_config_supports_language_exchange_flags_and_custom_tickers(self):
        config = _build_app_config(
            {
                "ui": {
                    "language": "en-US",
                    "exchanges": {"kucoin": {"enabled": False}, "binance": {"enabled": True}},
                    "tickers": [
                        {"exchange": "binance", "symbol": "SOL-USDT", "display_name": "SOL", "enabled": True},
                    ],
                    "ticker_preferences": [
                        {"key": "binance::SOL-USDT", "visible": True, "order": 0, "pinned_title": True},
                    ],
                }
            },
            AppConfig.default(),
        )
        self.assertEqual(config.language, "en-US")
        self.assertFalse(config.exchanges["kucoin"].enabled)
        self.assertTrue(config.exchanges["binance"].enabled)
        self.assertEqual(len(config.tickers), 1)
        self.assertEqual(config.tickers[0].key, "binance::SOL-USDT")
        self.assertIn("binance::sol-usdt", config.ticker_preferences)

    def test_sources_expose_symbol_list_api(self):
        self.assertTrue(hasattr(BinancePriceSource(lambda *_: None, lambda *_: None), "list_symbols"))
        self.assertTrue(hasattr(KucoinPriceSource(lambda *_: None, lambda *_: None), "list_symbols"))

    def test_supported_exchanges_include_panel_symbol_sources(self):
        self.assertIn("binance", SUPPORTED_EXCHANGES)
        self.assertIn("kucoin", SUPPORTED_EXCHANGES)


if __name__ == "__main__":
    unittest.main()
