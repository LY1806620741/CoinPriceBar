import unittest
from queue import Queue

from coinpricebar.app import CoinPriceBarApp
from coinpricebar.config import AppConfig, TickerConfig
from coinpricebar.sources.base import MarketSnapshot


class DummyItem:
    def __init__(self, title: str = ""):
        self.title = title


class DummyApp:
    pass


class FalsyDummyItem(DummyItem):
    def __bool__(self):
        return False


class MultiTickerUpdateTests(unittest.TestCase):
    def setUp(self):
        self.app = DummyApp()
        self.app.config = AppConfig.default()
        self.app.config.title_template = "{exchange}:{symbol} {price} {change_percent}"
        self.app.config.menu_template = "{exchange}:{symbol} {price} {change_percent}"
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
        self.app._menu_label = lambda exchange: exchange.title()
        self.app._format_change = lambda snapshot: CoinPriceBarApp._format_change(self.app, snapshot)
        self.app._build_display_context = lambda snapshot: CoinPriceBarApp._build_display_context(self.app, snapshot)
        self.app._render_text = lambda snapshot, template, is_title=False: CoinPriceBarApp._render_text(self.app, snapshot, template, is_title)
        self.app._refresh_snapshot_ui = lambda key: CoinPriceBarApp._refresh_snapshot_ui(self.app, key)

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

        updated = self.app.price_menu_items[target_key].title
        self.assertIn("66.66", updated)
        self.assertNotIn("加载中", updated)

    def test_process_ui_queue_executes_deferred_refresh(self):
        target_key = self.app.active_tickers[1].key
        self.app._process_ui_queue = lambda _=None: CoinPriceBarApp._process_ui_queue(self.app, _)
        self.app.price_menu_items[target_key].title = "Binance:ETH: 加载中..."
        self.app.ui_queue.put(lambda: CoinPriceBarApp._refresh_snapshot_ui(self.app, target_key))

        self.app._process_ui_queue()

        updated = self.app.price_menu_items[target_key].title
        self.assertIn("ETH", updated)
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


if __name__ == "__main__":
    unittest.main()
