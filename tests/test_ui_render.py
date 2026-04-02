import unittest
from pathlib import Path

from coinpricebar.app import CoinPriceBarApp, _with_trend_suffix, build_trade_url
from coinpricebar.config import AppConfig, TEMPLATE_VARIABLE_GROUPS, _build_app_config, get_default_tickers
from coinpricebar.panel import ConfigPanelServer
from coinpricebar.sources import BinanceC2CPriceSource, BinanceFuturesPriceSource, BinancePriceSource, KucoinFuturesPriceSource, KucoinPriceSource
from coinpricebar.sources.base import MarketSnapshot


class DummyApp:
    pass


class UIRenderTests(unittest.TestCase):
    def setUp(self):
        self.app = DummyApp()
        self.app.config = AppConfig.default()
        self.app.config.display_fields = ["exchange", "symbol", "price", "change_percent"]
        self.app._menu_label = lambda exchange: "KuCoin" if exchange == "kucoin" else exchange.title()
        self.app._exchange_short_label = lambda exchange: CoinPriceBarApp._exchange_short_label(self.app, exchange)
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

    def test_default_tickers_include_binance_c2c_rate(self):
        self.assertIn("binance_c2c::USDT-CNY", [ticker.key for ticker in get_default_tickers()])

    def test_default_config_contains_update_tuning_fields(self):
        config = AppConfig.default()
        self.assertGreaterEqual(config.ui_refresh_interval, 0.05)
        self.assertEqual(config.performance_mode, "balanced")
        self.assertEqual(config.format_mode, "short")
        self.assertEqual(config.icon_style, "official")
        self.assertGreaterEqual(config.max_visible, len(config.tickers))

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
                    "format_mode": "custom",
                    "title_template": "{exchange_icon}{exchange}:{symbol} {price}",
                    "menu_template": "{exchange_full} {symbol} {price}",
                    "icon_style": "text",
                    "exchange_icons": {"kucoin": "[K] ", "binance": "[B] "},
                    "exchanges": {"kucoin": {"enabled": False}, "binance": {"enabled": True}},
                    "exchange_short_names": {"kucoin": "KU", "binance": "BN"},
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
        self.assertEqual(config.format_mode, "custom")
        self.assertEqual(config.icon_style, "text")
        self.assertEqual(config.exchange_icons["kucoin"], "[K] ")
        self.assertFalse(config.exchanges["kucoin"].enabled)
        self.assertTrue(config.exchanges["binance"].enabled)
        self.assertEqual(len(config.tickers), 1)
        self.assertEqual(config.tickers[0].key, "binance::SOL-USDT")
        self.assertEqual(config.exchange_short_names["kucoin"], "KU")
        self.assertEqual(config.exchange_short_names["binance"], "BN")
        self.assertIn("binance::sol-usdt", config.ticker_preferences)

    def test_config_supports_binance_c2c_ticker(self):
        config = _build_app_config(
            {
                "ui": {
                    "tickers": [
                        {"exchange": "binance_c2c", "symbol": "USDT-CNY", "display_name": "U/CNY", "enabled": True},
                    ],
                    "ticker_preferences": [
                        {"key": "binance_c2c::USDT-CNY", "visible": True, "order": 0, "pinned_title": True},
                    ],
                }
            },
            AppConfig.default(),
        )
        self.assertEqual(config.tickers[0].key, "binance_c2c::USDT-CNY")
        self.assertIn("binance_c2c::usdt-cny", config.ticker_preferences)
        self.assertIn("binance_c2c", config.exchanges)

    def test_config_supports_futures_tickers(self):
        config = _build_app_config(
            {
                "ui": {
                    "tickers": [
                        {"exchange": "kucoin_futures", "symbol": "XBTUSDTM", "display_name": "XBT 永续", "enabled": True},
                        {"exchange": "binance_futures", "symbol": "BTC-USDT", "display_name": "BTC 永续", "enabled": True},
                    ],
                    "ticker_preferences": [
                        {"key": "kucoin_futures::XBTUSDTM", "visible": True, "order": 0, "pinned_title": True},
                        {"key": "binance_futures::BTC-USDT", "visible": True, "order": 1, "pinned_title": False},
                    ],
                }
            },
            AppConfig.default(),
        )
        self.assertEqual([ticker.key for ticker in config.tickers], ["kucoin_futures::XBTUSDTM", "binance_futures::BTC-USDT"])
        self.assertIn("kucoin_futures", config.exchanges)
        self.assertIn("binance_futures", config.exchanges)

    def test_long_format_mode_uses_preset_templates(self):
        config = _build_app_config({"ui": {"format_mode": "long"}}, AppConfig.default())
        self.assertEqual(config.format_mode, "long")
        self.assertIn("{exchange_full}", config.title_template)
        self.assertIn("状态 {status}", config.menu_template)

    def test_build_app_config_normalizes_preference_order_to_ticker_sequence(self):
        config = _build_app_config(
            {
                "ui": {
                    "tickers": [
                        {"exchange": "binance", "symbol": "ETH-USDT", "display_name": "ETH", "enabled": True},
                        {"exchange": "kucoin", "symbol": "BTC-USDT", "display_name": "BTC", "enabled": True},
                    ],
                    "ticker_preferences": [
                        {"key": "kucoin::BTC-USDT", "visible": True, "order": 0, "pinned_title": False},
                        {"key": "binance::ETH-USDT", "visible": True, "order": 1, "pinned_title": True},
                    ],
                }
            },
            AppConfig.default(),
        )
        self.assertEqual([ticker.key for ticker in config.tickers], ["binance::ETH-USDT", "kucoin::BTC-USDT"])
        self.assertEqual(config.ticker_preferences["binance::eth-usdt"].order, 0)
        self.assertEqual(config.ticker_preferences["kucoin::btc-usdt"].order, 1)
        self.assertTrue(config.ticker_preferences["binance::eth-usdt"].pinned_title)

    def test_official_icon_style_is_supported(self):
        config = _build_app_config({"ui": {"icon_style": "official"}}, AppConfig.default())
        self.assertEqual(config.icon_style, "official")
        self.assertIn("kucoin", config.exchange_icons)
        self.assertEqual(config.exchange_icons["kucoin"], "")

    def test_panel_state_contains_official_icon_urls(self):
        config = AppConfig.default()
        panel = ConfigPanelServer(lambda: config, lambda: list(config.tickers), lambda payload: config)
        state = panel._serialize_state()
        self.assertIn("officialExchangeIconUrls", state)
        self.assertIn("kucoin", state["officialExchangeIconUrls"])
        self.assertIn("binance", state["officialExchangeIconUrls"])
        self.assertIn("binance_c2c", state["officialExchangeIconUrls"])
        self.assertIn("kucoin_futures", state["officialExchangeIconUrls"])
        self.assertIn("binance_futures", state["officialExchangeIconUrls"])

    def test_panel_state_contains_template_reference_lists(self):
        config = AppConfig.default()
        panel = ConfigPanelServer(lambda: config, lambda: list(config.tickers), lambda payload: config)
        state = panel._serialize_state()
        self.assertIn("templateVariables", state)
        self.assertIn("templateVariableGroups", state)
        self.assertIn("iconStyleOptions", state)
        exchange_icon = next(item for item in state["templateVariables"] if item["name"] == "exchange_icon")
        self.assertEqual(state["templateVariableGroups"], TEMPLATE_VARIABLE_GROUPS)
        self.assertEqual(exchange_icon["group"], "exchange_identity")
        self.assertIsInstance(exchange_icon["examples"], list)
        self.assertIn("官方 Logo（图片）", exchange_icon["examples"])
        self.assertIn("official", state["iconStyleOptions"])

    def test_panel_state_contains_structured_template_examples(self):
        config = AppConfig.default()
        panel = ConfigPanelServer(lambda: config, lambda: list(config.tickers), lambda payload: config)
        state = panel._serialize_state()

        self.assertTrue(state["templateExamples"])
        self.assertIsInstance(state["templateExamples"][0], dict)
        self.assertIn("items", state["templateExamples"][0])
        self.assertTrue(any(item["target"] == "menu" for group in state["templateExamples"] for item in group.get("items", [])))

    def test_sources_expose_symbol_list_api(self):
        self.assertTrue(hasattr(BinancePriceSource(lambda *_: None, lambda *_: None), "list_symbols"))
        self.assertTrue(hasattr(BinanceC2CPriceSource(lambda *_: None, lambda *_: None), "list_symbols"))
        self.assertTrue(hasattr(BinanceFuturesPriceSource(lambda *_: None, lambda *_: None), "list_symbols"))
        self.assertTrue(hasattr(KucoinPriceSource(lambda *_: None, lambda *_: None), "list_symbols"))
        self.assertTrue(hasattr(KucoinFuturesPriceSource(lambda *_: None, lambda *_: None), "list_symbols"))

    def test_binance_c2c_source_lists_supported_symbols(self):
        symbols = BinanceC2CPriceSource(lambda *_: None, lambda *_: None).list_symbols()
        self.assertIn("USDT-CNY", symbols)

    def test_futures_sources_list_symbols_methods(self):
        self.assertIsInstance(BinanceFuturesPriceSource(lambda *_: None, lambda *_: None).list_symbols(), list)
        self.assertIsInstance(KucoinFuturesPriceSource(lambda *_: None, lambda *_: None).list_symbols(), list)

    def test_exchange_template_uses_short_label_by_default(self):
        self.app.config.exchange_short_names = {"kucoin": "KC", "binance": "BN"}
        snapshot = MarketSnapshot(exchange="kucoin", symbol="BTC-USDT", display_name="BTC", price=100.0, change=1.0, change_percent=1.0, is_first=False)

        text = CoinPriceBarApp._render_text(self.app, snapshot, "{exchange}:{symbol} {price}")

        self.assertIn("KC:BTC 100.00", text)
        self.assertNotIn("KuCoin", text)

    def test_exchange_full_template_keeps_full_name(self):
        self.app.config.exchange_short_names = {"kucoin": "KC", "binance": "BN"}
        snapshot = MarketSnapshot(exchange="kucoin", symbol="BTC-USDT", display_name="BTC", price=100.0, change=1.0, change_percent=1.0, is_first=False)

        text = CoinPriceBarApp._render_text(self.app, snapshot, "{exchange_full}:{symbol} {price}")

        self.assertIn("KuCoin:BTC 100.00", text)

    def test_build_display_context_contains_exchange_variants(self):
        self.app.config.exchange_short_names = {"kucoin": "KC", "binance": "BN"}
        self.app.config.exchange_icons = {"kucoin": "🟢 ", "binance": "🟡 "}
        snapshot = MarketSnapshot(exchange="kucoin", symbol="BTC-USDT", display_name="BTC", price=100.0, change=0.0, change_percent=0.0, is_first=False)

        context = CoinPriceBarApp._build_display_context(self.app, snapshot)

        self.assertEqual(context["exchange"], "KC")
        self.assertEqual(context["exchange_short"], "KC")
        self.assertEqual(context["exchange_full"], "KuCoin")
        self.assertEqual(context["exchange_icon"], "🟢 ")

    def test_build_trade_url_supports_binance_c2c(self):
        url = build_trade_url("binance_c2c", "USDT-CNY")
        self.assertIn("p2p.binance.com", url)
        self.assertIn("USDT", url)
        self.assertIn("CNY", url)

    def test_build_trade_url_supports_futures(self):
        self.assertIn("binance.com/en/futures", build_trade_url("binance_futures", "BTC-USDT"))
        self.assertIn("kucoin.com/futures/trade", build_trade_url("kucoin_futures", "XBTUSDTM"))

    def test_build_display_context_status_uses_trend_dots_when_online(self):
        rising = MarketSnapshot(exchange="kucoin", symbol="BTC-USDT", display_name="BTC", price=100.0, change=1.0, change_percent=1.0, is_first=False)
        falling = MarketSnapshot(exchange="kucoin", symbol="BTC-USDT", display_name="BTC", price=100.0, change=-1.0, change_percent=-1.0, is_first=False)
        flat = MarketSnapshot(exchange="kucoin", symbol="BTC-USDT", display_name="BTC", price=100.0, change=0.0, change_percent=0.0, is_first=False)

        rising_context = CoinPriceBarApp._build_display_context(self.app, rising)
        falling_context = CoinPriceBarApp._build_display_context(self.app, falling)
        flat_context = CoinPriceBarApp._build_display_context(self.app, flat)

        self.assertEqual(rising_context["status"], "🟢")
        self.assertEqual(falling_context["status"], "🔴")
        self.assertEqual(flat_context["status"], "⚪")

    def test_render_text_supports_exchange_icon_placeholder(self):
        self.app.config.exchange_short_names = {"kucoin": "KC", "binance": "BN"}
        self.app.config.exchange_icons = {"kucoin": "🟢 ", "binance": "🟡 "}
        snapshot = MarketSnapshot(exchange="kucoin", symbol="BTC-USDT", display_name="BTC", price=100.0, change=1.0, change_percent=1.0, is_first=False)

        text = CoinPriceBarApp._render_text(self.app, snapshot, "{exchange_icon}{exchange}:{symbol} {price}")

        self.assertIn("🟢 KC:BTC 100.00", text)

    def test_panel_html_contains_load_config_script_without_escaped_quotes(self):
        config = AppConfig.default()
        panel = ConfigPanelServer(lambda: config, lambda: list(config.tickers), lambda payload: config)
        html = panel._build_html()
        self.assertIn("fetch('/api/config')", html)
        self.assertIn('<html lang="zh-CN">', html)
        self.assertNotIn('\\"', html)

    def test_panel_html_is_loaded_from_standalone_file(self):
        config = AppConfig.default()
        panel = ConfigPanelServer(lambda: config, lambda: list(config.tickers), lambda payload: config)
        html = panel._build_html()
        file_html = Path("/Users/aiden/IdeaProjects/github/CoinPriceBar/coinpricebar/panel.html").read_text(encoding="utf-8")
        self.assertEqual(html, file_html)

    def test_panel_html_contains_logo_fallback_support(self):
        config = AppConfig.default()
        panel = ConfigPanelServer(lambda: config, lambda: list(config.tickers), lambda payload: config)
        html = panel._build_html()
        self.assertIn("official-icon.logo-wide", html)
        self.assertIn("official-icon-fallback", html)
        self.assertIn("logo[.](png|svg|jpg|jpeg)$", html)

    def test_render_title_text_does_not_inline_exchange_icon(self):
        self.app.config.exchange_short_names = {"kucoin": "KC", "binance": "BN"}
        self.app.config.exchange_icons = {"kucoin": "[KC] ", "binance": "[BN] "}
        snapshot = MarketSnapshot(exchange="kucoin", symbol="BTC-USDT", display_name="BTC", price=100.0, change=1.0, change_percent=1.0, is_first=False)

        text = CoinPriceBarApp._render_text(self.app, snapshot, "{exchange}:{symbol} {price}", is_title=True)

        self.assertNotIn("[KC] ", text)
        self.assertIn("KC:BTC 100.00", text)

    def test_panel_html_contains_template_reference_sections(self):
        config = AppConfig.default()
        panel = ConfigPanelServer(lambda: config, lambda: list(config.tickers), lambda payload: config)
        html = panel._build_html()
        self.assertIn("id=\"template_variables\"", html)
        self.assertIn("id=\"style_options\"", html)
        self.assertIn("template-editor-layout", html)
        self.assertIn("template-editor-side", html)
        self.assertIn("id=\"custom_display_section\"", html)
        self.assertIn("custom-config-tabs", html)
        self.assertIn("data-custom-tab-button=\"exchange\"", html)
        self.assertIn("id=\"custom_tab_template\"", html)
        self.assertIn("id=\"display_fields_label\"", html)
        self.assertIn("id=\"display_fields_wrap\"", html)
        self.assertIn("id=\"ui_refresh_interval_label\"", html)
        self.assertIn("id=\"ui_refresh_interval_wrap\"", html)
        self.assertIn("id=\"performance_value_hint\"", html)
        self.assertIn("id=\"title_template\"", html)
        self.assertIn("id=\"menu_template\"", html)
        self.assertNotIn("id=\"advanced_template_editor\"", html)
        self.assertIn("data-apply-template", html)
        self.assertIn("data-variable-name", html)
        self.assertIn("function renderExchangeIcons", html)
        self.assertIn("function renderTemplateVariables", html)
        self.assertIn("function renderStyleOptions", html)
        self.assertIn("function applyTemplatePreset", html)
        self.assertIn("function activateCustomTab", html)
        self.assertIn("function setCustomSectionVisibility", html)
        self.assertIn("function setDisplayFieldsVisibility", html)
        self.assertIn("function setRefreshIntervalVisibility", html)
        self.assertIn("function commitTickerRowDomOrder", html)
        self.assertIn("Sortable.min.js", html)
        self.assertIn("let tickerSortable = null", html)
        self.assertIn("function initTickerSortable", html)
        self.assertIn("new window.Sortable", html)
        self.assertIn("handle: '.drag-handle'", html)
        self.assertIn("draggable: 'tr[data-key]'", html)
        self.assertIn("onEnd()", html)
        self.assertIn('class="drag-handle">☰</span>', html)
        self.assertIn('id="ticker_rows"', html)
        self.assertIn("function renderPerformanceValueHint", html)
        self.assertIn("function syncPerformanceModeUI", html)
        self.assertIn("function syncConditionalFieldVisibility", html)
        self.assertIn("document.getElementById('performance_mode').addEventListener('change', syncConditionalFieldVisibility)", html)
        self.assertIn("document.getElementById('ui_refresh_interval').addEventListener('input', syncPerformanceModeUI)", html)
        self.assertIn("performance_value_hint", html)
        self.assertIn("performance_custom_value_hint", html)
        self.assertIn("variable-browser", html)
        self.assertIn("possible_values", html)
        self.assertIn("variable-example-list", html)

    def test_sources_expose_local_icon_fallback(self):
        self.assertIsNotNone(KucoinPriceSource.get_local_icon_path())
        self.assertIsNotNone(BinancePriceSource.get_local_icon_path())

    def test_render_title_text_keeps_plain_text_when_exchange_icon_empty(self):
        self.app.config.exchange_short_names = {"kucoin": "KC", "binance": "BN"}
        self.app.config.exchange_icons = {"kucoin": "", "binance": ""}
        snapshot = MarketSnapshot(exchange="kucoin", symbol="BTC-USDT", display_name="BTC", price=100.0, change=1.0, change_percent=1.0, is_first=False)

        text = CoinPriceBarApp._render_text(self.app, snapshot, "{exchange}:{symbol} {price}", is_title=True)

        self.assertFalse(text.startswith("[KC] "))
        self.assertIn("KC:BTC 100.00", text)


if __name__ == "__main__":
    unittest.main()
