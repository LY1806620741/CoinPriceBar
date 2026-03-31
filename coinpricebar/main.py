import os
import traceback

import rumps

from .app import CoinPriceBarApp, logging
from .config import get_default_tickers, load_app_config


def main():
    os.environ["PYTHONIOENCODING"] = "utf-8"
    try:
        config = load_app_config()
        logging.info("启动 CoinPriceBar 状态栏应用...")
        app = CoinPriceBarApp(config=config, tickers=get_default_tickers())
        app.run()
    except Exception as e:
        logging.critical(f"应用启动失败: {e}\n{traceback.format_exc()}")
        rumps.alert("应用崩溃", f"错误详情：{str(e)}\n请查看日志文件 kucoin_status.log")


if __name__ == "__main__":
    main()

