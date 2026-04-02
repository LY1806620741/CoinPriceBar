import tempfile
import unittest
from pathlib import Path
from queue import Queue

from coinpricebar.app import CoinPriceBarApp
from coinpricebar.config import AppConfig, TickerConfig, UITickerPreference
from coinpricebar.sources.base import MarketSnapshot


class DummyItem:
    def __init__(self, title: str = ""):
        self.title = title


class DummyApp:
    pass


class FalsyDummyItem(DummyItem):
    def __bool__(self):
        return False


class NativeMenuItemStub:
    def __init__(self):
        self.image = None

    def setImage_(self, image):
        self.image = image


class MenuItemWithNativeStub(DummyItem):
    def __init__(self, title: str = ""):
        super().__init__(title)
        self._menuitem = NativeMenuItemStub()


class MultiTickerUpdateTests(unittest.TestCase):
    def setUp(self):
        self.app = DummyApp()
        self.app.config = AppConfig.default()
        self.app.config.title_template = "{exchange}:{symbol} {price} {change_percent}"
        self.app.config.menu_template = "{exchange}:{symbol} {price} {change_percent}"
        self.app.config.exchange_short_names = {"kucoin": "KC", "binance": "BN"}
        self.app.active_tickers = [
            TickerConfig(exchange="kucoin", symbol="BTC-USDT", display_name="BTC"),
            TickerConfig(exchange="binance", symbol="ETH-USDT", display_name="ETH"),
        ]
        self.app.title_ticker_index = 0
        self.app.price_menu_items = {
            self.app.active_tickers[0].key: DummyItem("Kucoin:BTC: 加载中..."),
            self.app.active_tickers[1].key: DummyItem("Binance:ETH: 加载中..."),
        }
        self.app.snapshots = {
            self.app.active_tickers[0].key: MarketSnapshot(exchange="kucoin", symbol="BTC-USDT", display_name="BTC", price=100, change=2, change_percent=2, is_first=False),
            self.app.active_tickers[1].key: MarketSnapshot(exchange="binance", symbol="ETH-USDT", display_name="ETH", price=50, change=-1, change_percent=-2, is_first=False),
        }
        self.app.title = "加载中..."
        self.app._quitting = False
        self.app.status_by_exchange = {}
        self.app.ui_queue = Queue()
        self.app._menu_label = lambda exchange: "KuCoin" if exchange == "kucoin" else exchange.title()
        self.app._exchange_short_label = lambda exchange: CoinPriceBarApp._exchange_short_label(self.app, exchange)
        self.app._format_change = lambda snapshot: CoinPriceBarApp._format_change(self.app, snapshot)
        self.app._build_display_context = lambda snapshot: CoinPriceBarApp._build_display_context(self.app, snapshot)
        self.app._render_text = lambda snapshot, template, is_title=False: CoinPriceBarApp._render_text(self.app, snapshot, template, is_title)
        self.app._refresh_snapshot_ui = lambda key: CoinPriceBarApp._refresh_snapshot_ui(self.app, key)
        self.app._process_ui_queue = lambda _=None: CoinPriceBarApp._process_ui_queue(self.app, _)
        self.app._set_title_icon = lambda exchange: setattr(self.app, "_last_title_icon_exchange", exchange)

    def test_refresh_snapshot_updates_title_and_second_menu_item(self):
        CoinPriceBarApp._refresh_snapshot_ui(self.app, self.app.active_tickers[0].key)
        CoinPriceBarApp._refresh_snapshot_ui(self.app, self.app.active_tickers[1].key)

        self.assertIn("BTC", self.app.title)
        self.assertIn("↑", self.app.title)
        self.assertNotIn("加载中", self.app.title)

        second_title = self.app.price_menu_items[self.app.active_tickers[1].key].title
        self.assertIn("ETH", second_title)
        self.assertIn("↓", second_title)
        self.assertNotIn("加载中", second_title)

    def test_visible_tickers_follow_config_ticker_sequence_instead_of_pref_order(self):
        self.app.all_tickers = [
            TickerConfig(exchange="binance", symbol="ETH-USDT", display_name="ETH"),
            TickerConfig(exchange="kucoin", symbol="BTC-USDT", display_name="BTC"),
        ]
        self.app.config.max_visible = 2
        self.app.config.ticker_preferences = {
            "kucoin::btc-usdt": UITickerPreference(key="kucoin::btc-usdt", visible=True, order=0, pinned_title=False),
            "binance::eth-usdt": UITickerPreference(key="binance::eth-usdt", visible=True, order=1, pinned_title=True),
        }
        self.app._get_ticker_preference = lambda ticker: CoinPriceBarApp._get_ticker_preference(self.app, ticker)

        visible = CoinPriceBarApp._visible_tickers(self.app)

        self.assertEqual([ticker.key for ticker in visible], ["binance::ETH-USDT", "kucoin::BTC-USDT"])

    def test_price_update_flow_replaces_loading_state_for_visible_item(self):
        target_key = self.app.active_tickers[1].key
        snapshot = self.app.snapshots[target_key]
        snapshot.price = 0.0
        snapshot.change = 0.0
        snapshot.change_percent = 0.0
        snapshot.is_first = True
        self.app.price_menu_items[target_key].title = "Binance:ETH: 加载中..."

        CoinPriceBarApp._refresh_snapshot_ui(self.app, target_key)
        self.assertIn("加载中", self.app.price_menu_items[target_key].title)

        snapshot.price = 51.25
        snapshot.change = 1.25
        snapshot.change_percent = 2.5
        snapshot.is_first = False

        CoinPriceBarApp._refresh_snapshot_ui(self.app, target_key)
        updated = self.app.price_menu_items[target_key].title
        self.assertIn("51.25", updated)
        self.assertIn("↑", updated)
        self.assertNotIn("加载中", updated)

    def test_on_price_update_enqueues_refresh_and_updates_visible_menu_item(self):
        target_ticker = self.app.active_tickers[1]
        target_key = target_ticker.key
        snapshot = self.app.snapshots[target_key]
        snapshot.price = 0.0
        snapshot.change = 0.0
        snapshot.change_percent = 0.0
        snapshot.is_first = True
        self.app.price_menu_items[target_key].title = "Binance:ETH: 加载中..."

        CoinPriceBarApp._on_price_update(self.app, "binance", "ETH-USDT", 66.66)
        self.assertGreaterEqual(self.app.ui_queue.qsize(), 1)

        self.app._process_ui_queue()

        updated = self.app.price_menu_items[target_key].title
        self.assertIn("66.66", updated)
        self.assertNotIn("加载中", updated)

    def test_process_ui_queue_executes_deferred_refresh(self):
        target_key = self.app.active_tickers[1].key
        snapshot = self.app.snapshots[target_key]
        snapshot.price = 52.34
        snapshot.change = 2.34
        snapshot.change_percent = 4.68
        snapshot.is_first = False
        self.app.price_menu_items[target_key].title = "Binance:ETH: 加载中..."
        self.app.ui_queue.put(lambda: CoinPriceBarApp._refresh_snapshot_ui(self.app, target_key))

        self.app._process_ui_queue()

        updated = self.app.price_menu_items[target_key].title
        self.assertIn("ETH", updated)
        self.assertIn("52.34", updated)
        self.assertNotIn("加载中", updated)

    def test_refresh_updates_even_if_menu_item_is_falsy(self):
        target_key = self.app.active_tickers[1].key
        self.app.price_menu_items[target_key] = FalsyDummyItem("Binance:ETH: 加载中...")
        snapshot = self.app.snapshots[target_key]
        snapshot.price = 77.77
        snapshot.change = 3.33
        snapshot.change_percent = 4.47
        snapshot.is_first = False

        CoinPriceBarApp._refresh_snapshot_ui(self.app, target_key)

        updated = self.app.price_menu_items[target_key].title
        self.assertIn("77.77", updated)
        self.assertNotIn("加载中", updated)

    def test_apply_menu_item_icon_sets_native_image_when_available(self):
        item = MenuItemWithNativeStub("BTC")
        original_builder = CoinPriceBarApp._build_menu_icon
        try:
            CoinPriceBarApp._build_menu_icon = staticmethod(lambda exchange: object())
            CoinPriceBarApp._apply_menu_item_icon(self.app, item, "kucoin")
            self.assertIsNotNone(item._menuitem.image)
        finally:
            CoinPriceBarApp._build_menu_icon = original_builder

    def test_apply_menu_item_icon_prefers_cached_logo(self):
        item = MenuItemWithNativeStub("BTC")
        original_loader = CoinPriceBarApp._load_cached_exchange_icon
        original_builder = CoinPriceBarApp._build_menu_icon
        try:
            CoinPriceBarApp._load_cached_exchange_icon = staticmethod(lambda exchange: object())
            CoinPriceBarApp._build_menu_icon = staticmethod(lambda exchange: None)
            CoinPriceBarApp._apply_menu_item_icon(self.app, item, "kucoin")
            self.assertIsNotNone(item._menuitem.image)
        finally:
            CoinPriceBarApp._load_cached_exchange_icon = original_loader
            CoinPriceBarApp._build_menu_icon = original_builder

    def test_apply_menu_item_icon_falls_back_when_logo_missing(self):
        item = MenuItemWithNativeStub("BTC")
        fallback_icon = object()
        original_loader = CoinPriceBarApp._load_cached_exchange_icon
        original_builder = CoinPriceBarApp._build_menu_icon
        try:
            CoinPriceBarApp._load_cached_exchange_icon = staticmethod(lambda exchange: None)
            CoinPriceBarApp._build_menu_icon = staticmethod(lambda exchange: fallback_icon)
            CoinPriceBarApp._apply_menu_item_icon(self.app, item, "kucoin")
            self.assertIs(item._menuitem.image, fallback_icon)
        finally:
            CoinPriceBarApp._load_cached_exchange_icon = original_loader
            CoinPriceBarApp._build_menu_icon = original_builder

    def test_icon_cache_path_uses_exchange_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            from coinpricebar import app as app_module
            original_dir = app_module.ICON_CACHE_DIR
            try:
                app_module.ICON_CACHE_DIR = Path(tmp)
                path = CoinPriceBarApp._icon_cache_path("kucoin")
                self.assertEqual(path.parent, Path(tmp))
                self.assertTrue(path.name.startswith("kucoin"))
                self.assertIn(path.suffix, {".png", ".ico", ".img"})
            finally:
                app_module.ICON_CACHE_DIR = original_dir

    def test_load_cached_exchange_icon_uses_standardized_cache_file(self):
        original_download = CoinPriceBarApp._download_exchange_icon
        original_is_valid = CoinPriceBarApp._is_valid_cache_file
        try:
            CoinPriceBarApp._download_exchange_icon = staticmethod(lambda exchange: Path("/tmp/fake-logo.menu.png"))
            CoinPriceBarApp._is_valid_cache_file = staticmethod(lambda _path: True)

            class FakeImage:
                pass

            class FakeNSImageFactory:
                def alloc(self):
                    return self
                def initWithContentsOfFile_(self, _path):
                    return FakeImage()

            from coinpricebar import app as app_module
            original_nsimage = app_module.NSImage
            app_module.NSImage = FakeNSImageFactory()
            try:
                loaded = CoinPriceBarApp._load_cached_exchange_icon("kucoin")
                self.assertIsNotNone(loaded)
            finally:
                app_module.NSImage = original_nsimage
        finally:
            CoinPriceBarApp._download_exchange_icon = original_download
            CoinPriceBarApp._is_valid_cache_file = original_is_valid

    def test_is_valid_cache_file_detects_non_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "kucoin.menu.png"
            file_path.write_bytes(b"abc")
            self.assertTrue(CoinPriceBarApp._is_valid_cache_file(file_path))
            empty_path = Path(tmp) / "empty.menu.png"
            empty_path.write_bytes(b"")
            self.assertFalse(CoinPriceBarApp._is_valid_cache_file(empty_path))


if __name__ == "__main__":
    unittest.main()
