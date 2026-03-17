# -*- coding: utf-8 -*-
import logging
import threading
import time
import queue
import traceback
import webbrowser
from typing import Optional, List, Dict
import os

import rumps
from kucoin_universal_sdk.api import DefaultClient
from kucoin_universal_sdk.generate.spot.spot_public import SpotPublicWS, TickerEvent
from kucoin_universal_sdk.model import (
    ClientOptionBuilder,
    WebSocketClientOptionBuilder,
    GLOBAL_API_ENDPOINT,
    GLOBAL_FUTURES_API_ENDPOINT,
    GLOBAL_BROKER_API_ENDPOINT,
    WebSocketEvent,
)

from Foundation import NSObject
from AppKit import NSApp

# ===================== 可调常量 =====================
LOG_CONFIG = {
    "level": logging.INFO,
    "format": "%(asctime)s %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
    "datefmt": "%Y-%m-%d %H:%M:%S",
    "handlers": [
        logging.FileHandler("kucoin_status.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
}

KUCOIN_URLS = {
    "home": "https://www.kucoin.com/",
    "spot_trade": "https://www.kucoin.com/trade/{}-{}",
}

UI_UPDATE_INTERVAL = 0.1          # UI队列处理间隔（秒）
THREAD_JOIN_TIMEOUT = 2           # 线程退出等待时间（秒）
HARD_EXIT_DELAY_SEC = 2           # 强退兜底延时（秒）
ENABLE_HARD_EXIT_FALLBACK = False # 是否启用强退兜底（仅最后手段，默认关闭）

# ===================== 日志初始化 =====================
logging.basicConfig(**LOG_CONFIG)


# ===================== 小工具 =====================
def is_emoji(char: str) -> bool:
    """判断单个字符是否是任意Emoji"""
    if len(char) != 1:
        return False
    code = ord(char)
    return (
        (0x1F600 <= code <= 0x1F64F)  # 表情符号
        or (0x1F300 <= code <= 0x1F5FF)  # 符号/图标
        or (0x1F680 <= code <= 0x1F6FF)  # 交通/工具
        or (0x1F700 <= code <= 0x1F77F)  # 几何符号
        or (0x2600 <= code <= 0x26FF)    # 杂项符号
    )

def is_color_dot(char: str) -> bool:
    """判断单个字符是否是颜色圆点Emoji（🟢/🔴/🟡/🟠/🔵/⚫等）"""
    if len(char) != 1:
        return False
    dot_ranges = [
        (0x1F534, 0x1F535),  # 🔴 🔵
        (0x1F7E0, 0x1F7E2),  # 🟠 🟡 🟢
        (0x26AB, 0x26AB),    # ⚫
    ]
    code = ord(char)
    return any(start <= code <= end for start, end in dot_ranges)

def _dump_threads(tag: str):
    names = [(t.name, t.daemon) for t in threading.enumerate()]
    logging.info(f"[{tag}] Threads: {names}")


# ===================== 主线程退出调度器（统一使用 NSApp.terminate_） =====================
class Terminator(NSObject):
    def terminate_(self, _):
        # 必须在主线程调用
        NSApp.terminate_(None)

terminator = Terminator.alloc().init()


# ===================== 业务：KuCoin 价格监控 =====================
class KucoinPriceMonitor:
    """KuCoin价格监控核心类（纯业务逻辑，与UI解耦）"""

    def __init__(self, update_callback, status_callback, cleanup_callback=None):
        self.running = False
        self.lock = threading.Lock()
        self.client: Optional[DefaultClient] = None
        self.spot_ws: Optional[SpotPublicWS] = None
        self.update_callback = update_callback
        self.status_callback = status_callback
        # cleanup_callback 不再在 start() 的 finally 中调用，避免与 UI 侧退出相互重入
        self.cleanup_callback = cleanup_callback

        self.app_status = {
            WebSocketEvent.EVENT_CONNECTED: "",
            WebSocketEvent.EVENT_DISCONNECTED: "⚫",
            WebSocketEvent.EVENT_TRY_RECONNECT: "🟡",
        }

    def _init_client(self) -> bool:
        """初始化客户端（返回是否成功）"""
        try:
            client_option = (
                ClientOptionBuilder()
                .set_key(os.getenv("API_KEY", ""))
                .set_secret(os.getenv("API_SECRET", ""))
                .set_passphrase(os.getenv("API_PASSPHRASE", ""))
                .set_websocket_client_option(
                    WebSocketClientOptionBuilder()
                    .with_event_callback(self._ws_event_callback)
                    .with_reconnect_attempts(2)  # 运行时会在 stop() 里尝试调为 0
                    .build()
                )
                .set_spot_endpoint(GLOBAL_API_ENDPOINT)
                .set_futures_endpoint(GLOBAL_FUTURES_API_ENDPOINT)
                .set_broker_endpoint(GLOBAL_BROKER_API_ENDPOINT)
                .build()
            )
            self.client = DefaultClient(client_option)
            logging.info("KuCoin客户端初始化成功")
            return True
        except Exception as e:
            logging.error(f"客户端初始化失败: {str(e)}\n{traceback.format_exc()}")
            return False

    def _ws_event_callback(self, event_type: WebSocketEvent, msg: str, err: str):
        """
        SDK原生WS事件回调（仅监听，不处理重连）
        """
        if event_type in self.app_status.keys():
            logging.info(f"SDK WS事件触发: {event_type} | 附加数据: {msg}")
            # 推送状态到UI
            try:
                self.status_callback(self.app_status.get(event_type, ""))
            except Exception:
                # 回调可能在退出阶段被熄火
                pass

    def _ticker_callback(self, topic: str, subject: str, data: TickerEvent) -> None:
        """价格回调（仅传递核心数据）"""
        try:
            symbol = topic.split(":")[-1]
            price = float(data.price)
            self.update_callback(symbol, price)
        except Exception as e:
            logging.error(f"回调处理失败: {str(e)}\n{traceback.format_exc()}")

    def start(self, spot_symbols: List[str]) -> None:
        """启动监控（运行在独立线程）"""
        with self.lock:
            if self.running:
                return
            self.running = True

        if not self.client and not self._init_client():
            # 反馈错误到 UI
            try:
                self.update_callback("ERROR", 0.0)
            except Exception:
                pass
            return

        try:
            ws_service = self.client.ws_service()
            self.spot_ws = ws_service.new_spot_public_ws()
            self.spot_ws.start()
            logging.info(
                f"订阅成功，ID: {self.spot_ws.ticker(spot_symbols, self._ticker_callback)}"
            )
            _dump_threads("WS started")

            while self.running:
                time.sleep(UI_UPDATE_INTERVAL)
        except Exception as e:
            logging.error(f"监控启动失败: {str(e)}\n{traceback.format_exc()}")
            try:
                self.update_callback("ERROR", 0.0)
            except Exception:
                pass
        finally:
            # 不在这里触发 UI 侧的退出；清理由 UI 的退出流程统一调度
            pass

    def stop(self) -> None:
        """停止监控（原子操作 + 关闭重连 + 限时后台收尾）"""
        with self.lock:
            if not self.running:
                return
            self.running = False

        ws = self.spot_ws
        self.spot_ws = None

        if ws:
            try:
                # 1) 尝试运行时关闭自动重连（根据 SDK 能力择一/多项，不存在则忽略）
                try:
                    if hasattr(ws, "disable_reconnect"):
                        ws.disable_reconnect()
                    elif hasattr(ws, "set_reconnect_attempts"):
                        ws.set_reconnect_attempts(0)
                    elif hasattr(ws, "client_option"):
                        # 某些 SDK 对象上可能挂了 option，可尝试置 0
                        try:
                            ws.client_option.reconnect_attempts = 0
                        except Exception:
                            pass
                except Exception as e:
                    logging.warning(f"关闭重连开关失败或无此API: {e}")

                # 2) 只调用一次 stop/close，放到后台线程并限时等待
                def _stop_ws():
                    try:
                        if hasattr(ws, "close"):
                            ws.close()
                        elif hasattr(ws, "shutdown"):
                            ws.shutdown()
                        else:
                            ws.stop()
                    except Exception as _e:
                        logging.error(f"停止WS失败: {_e}\n{traceback.format_exc()}")

                t = threading.Thread(target=_stop_ws, daemon=True, name="WS-Stopper")
                t.start()
                t.join(timeout=THREAD_JOIN_TIMEOUT)
                if t.is_alive():
                    logging.warning("WebSocket停止未在超时内完成，将继续后台收尾")
                else:
                    logging.info("WebSocket已停止")
            except Exception as e:
                logging.error(f"停止WS异常: {e}\n{traceback.format_exc()}")

        # 3) service 层如果有 close()，也一并关闭（消灭可能的定时器/管理器）
        try:
            if self.client and hasattr(self.client, "ws_service"):
                svc = self.client.ws_service()
                if hasattr(svc, "close"):
                    svc.close()
        except Exception as e:
            logging.warning(f"关闭 ws_service 失败或无此API: {e}")


# ===================== UI：状态栏应用 =====================
class CoinPriceBarApp(rumps.App):
    """状态栏应用类（仅处理UI逻辑）"""

    def __init__(self, name="KuCoin 价格", spot_symbols: List[str] = ["BTC-USDT"]):
        super().__init__(name, quit_button=None)
        self.spot_symbols = spot_symbols
        self.price_cache: Dict[str, tuple] = {s: (0.0, 0.0, True) for s in spot_symbols}
        self.ui_queue = queue.Queue()
        self.monitor_thread: Optional[threading.Thread] = None
        self.price_monitor = KucoinPriceMonitor(
            self._on_price_update, self._on_status_update, cleanup_callback=None
        )
        self.status = ""
        self._quitting = False  # 退出总开关（防重入 + 回调熄火）

        self._init_menu()
        self._start_ui_timer()
        self._start_monitor_thread()

    # ---------- 菜单 ----------
    def _init_menu(self):
        """初始化菜单（结构化）"""
        self.menu.add(rumps.MenuItem("KuCoin官网", callback=self._open_kucoin_home))
        self.menu.add(rumps.separator)

        self.price_menu_items: Dict[str, rumps.MenuItem] = {}
        for symbol in self.spot_symbols:
            item = rumps.MenuItem(
                title=f"{symbol}: 加载中...",
                callback=lambda _, s=symbol: self._open_trade_page(s),
            )
            self.price_menu_items[symbol] = item
            self.menu.add(item)

        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("退出", callback=self._cleanup_and_quit))

    # ---------- 线程/定时器 ----------
    def _start_ui_timer(self):
        """启动UI队列处理定时器"""
        self.ui_timer = rumps.Timer(self._process_ui_queue, UI_UPDATE_INTERVAL)
        self.ui_timer.start()

    def _start_monitor_thread(self):
        """启动监控线程（守护模式）"""
        if not self.monitor_thread:
            self.monitor_thread = threading.Thread(
                target=self.price_monitor.start,
                args=(self.spot_symbols,),
                daemon=True,               # 守护线程，避免卡进程退出
                name="Monitor",
            )
            self.monitor_thread.start()
            logging.info("监控线程已启动")

    # ---------- 回调：业务 -> UI ----------
    def _on_price_update(self, symbol: str, price: float):
        """价格更新回调（业务逻辑→UI队列）"""
        if self._quitting:
            return

        if symbol == "ERROR":
            self.ui_queue.put(lambda: self._update_ui_error())
            return

        cached_price, _, is_first = self.price_cache[symbol]
        if not is_first and abs(price - cached_price) < 0.0001:
            return

        change = price - cached_price if not is_first else 0.0
        self.price_cache[symbol] = (price, change, False)
        self.ui_queue.put(lambda: self._update_ui(symbol, price, change))

    def _on_status_update(self, status: str):
        """状态更新回调（业务逻辑→UI队列）"""
        if self._quitting:
            return
        if self.status == status:
            return
        self.ui_queue.put(lambda: self._on_status_update_main(status))

    # ---------- UI 更新 ----------
    def _on_status_update_main(self, status: str):
        self.status = status
        title = self.title or ""
        if title and is_color_dot(title[-1]):
            self.title = title[:-1] + status
        else:
            self.title = title + status

        for symbol, item in self.price_menu_items.items():
            t = item.title or ""
            if t and is_color_dot(t[-1]):
                item.title = t[:-1] + status
            else:
                item.title = t + status

    def _process_ui_queue(self, _=None):
        """主线程处理UI队列（批量执行）"""
        try:
            while not self.ui_queue.empty():
                task = self.ui_queue.get_nowait()
                # 退出阶段直接丢弃队列任务，避免在退出中还去动 UI
                if self._quitting:
                    continue
                if callable(task):
                    task()
        except Exception as e:
            logging.error(f"处理UI任务失败: {str(e)}\n{traceback.format_exc()}")

    def _update_ui(self, symbol: str, price: float, change: float):
        """更新单个交易对UI"""
        price_str = f"{price:.2f}"
        change_percent = (change / price * 100) if price != 0 else 0.0

        # 更新主标题（仅第一个交易对）
        if symbol == self.spot_symbols[0]:
            if change > 0:
                self.title = f"{symbol}: {price_str} 🟢"
            elif change < 0:
                self.title = f"{symbol}: {price_str} 🔴"
            else:
                self.title = f"{symbol}: {price_str}"

        # 更新菜单项
        if symbol in self.price_menu_items:
            item = self.price_menu_items[symbol]
            if change > 0:
                item.title = f"{symbol}: {price_str} (↑{change_percent:.2f}%) 🟢"
            elif change < 0:
                item.title = f"{symbol}: {price_str} (↓{abs(change_percent):.2f}%) 🔴"
            else:
                item.title = f"{symbol}: {price_str}"

    def _update_ui_error(self):
        """更新UI为错误状态"""
        self.title = "KuCoin: 监控异常"
        for item in self.price_menu_items.values():
            item.title = f"{item.title.split(':')[0]}: 监控异常"

    # ---------- 打开链接 ----------
    def _open_kucoin_home(self, _):
        """打开KuCoin官网"""
        self._open_url(KUCOIN_URLS["home"], "官网")

    def _open_trade_page(self, symbol: str):
        """打开交易对页面"""
        try:
            base, quote = symbol.split("-")
            trade_url = KUCOIN_URLS["spot_trade"].format(base, quote)
            self._open_url(trade_url, f"{symbol}交易页面")
        except Exception as e:
            logging.error(f"构造交易URL失败: {str(e)}")
            rumps.alert("错误", f"无法打开{symbol}交易页面")

    def _open_url(self, url: str, desc: str):
        """通用打开URL方法（统一异常处理）"""
        try:
            webbrowser.open_new_tab(url)
            logging.info(f"打开{desc}: {url}")
        except Exception as e:
            logging.error(f"打开{desc}失败: {str(e)}\n{traceback.format_exc()}")
            rumps.alert("错误", f"无法打开{desc}，请检查浏览器设置")

    # ---------- 退出/清理 ----------
    def _cleanup_and_quit(self, _):
        """安全退出（非阻塞主线程版本，带防重入 + 回调熄火）"""
        if self._quitting:
            return
        self._quitting = True
        logging.info("开始退出应用（非阻塞清理）...")
        _dump_threads("Quit requested")

        # 轻量 UI 提示，不做耗时操作
        try:
            self.title = "正在退出…"
        except Exception:
            pass

        def _do_cleanup_then_quit():
            try:
                # 1) 停掉 UI 定时器（轻操作）
                try:
                    if hasattr(self, "ui_timer"):
                        self.ui_timer.stop()
                except Exception:
                    pass

                # 2) 停止监控（可能耗时）——后台进行
                try:
                    self.price_monitor.stop()
                except Exception as e:
                    logging.error(f"停止监控失败: {e}\n{traceback.format_exc()}")

                # 3) 等待监控线程结束（最多 THREAD_JOIN_TIMEOUT 秒）
                try:
                    if self.monitor_thread and self.monitor_thread.is_alive():
                        self.monitor_thread.join(timeout=THREAD_JOIN_TIMEOUT)
                except Exception:
                    pass

                logging.info("资源清理完成")
                _dump_threads("Cleanup done")
            finally:
                # 4) 由主线程执行“真正退出”
                terminator.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "terminate:", None, False
                )

                # 5) 最后兜底：如仍未退出（极少数 SDK 线程顽固），延迟强退
                if ENABLE_HARD_EXIT_FALLBACK:
                    def _hard_kill():
                        time.sleep(HARD_EXIT_DELAY_SEC)
                        logging.critical("优雅退出可能未完成，执行 os._exit(0) 兜底")
                        os._exit(0)
                    threading.Thread(target=_hard_kill, daemon=True, name="HardExit").start()

        threading.Thread(target=_do_cleanup_then_quit, daemon=True, name="Cleanup-Worker").start()

    def run(self):
        """重写run方法（兜底停定时器）"""
        try:
            super().run()
        finally:
            try:
                if hasattr(self, "ui_timer"):
                    self.ui_timer.stop()
            except Exception:
                pass


# ===================== 入口函数 =====================
def main():
    os.environ["PYTHONIOENCODING"] = "utf-8"

    try:
        logging.info("启动KuCoin状态栏应用...")
        app = CoinPriceBarApp(spot_symbols=["KCS-USDT", "BTC-USDT", "ETH-USDT"])
        app.run()
    except Exception as e:
        logging.critical(f"应用启动失败: {str(e)}\n{traceback.format_exc()}")
        rumps.alert("应用崩溃", f"错误详情：{str(e)}\n请查看日志文件 kucoin_status.log")


if __name__ == "__main__":
    main()