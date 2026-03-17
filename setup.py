# setup.py
from setuptools import setup
from pathlib import Path
import os

# ---------------- 基础信息 ----------------
APP = ["KCSApp.py"]
APP_NAME = "CoinPriceBar"  # .app 名称
BUNDLE_ID = "com.ly1806620741.CoinPriceBar"  # Bundle ID（唯一）
VERSION = os.getenv("APP_VERSION", "1.0.0")

ICON_FILE = "icon.icns"

RESOURCES_DIR = Path("resources")
data_files = []
if RESOURCES_DIR.exists():
    # 将 resources 下的所有文件打包进 .app 的 Resources 目录
    resources = [str(p) for p in RESOURCES_DIR.rglob("*") if p.is_file()]
    data_files = [("", resources)]

# ---------------- py2app 选项 ----------------
OPTIONS = {
    "argv_emulation": False,
    # 应用属性（Info.plist）
    "plist": {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSUIElement": True,
        "LSBackgroundOnly": True,
        "NSHighResolutionCapable": True,
        # 'NSAppTransportSecurity': {'NSAllowsArbitraryLoads': True},
    },
    "iconfile": ICON_FILE if Path(ICON_FILE).exists() else None,
    # 体积优化
    "strip": True,  # 去符号表，减小体积
    "optimize": 2,  # 仅生成优化字节码
    "includes": [
        "rumps",
        "PyObjCTools",
        "AppKit",
        "Foundation",
        "kucoin_universal_sdk",
    ],
    "excludes": [
        "tkinter",
        "turtle",
        "idlelib",
        "lib2to3",
        "distutils",
        "pydoc",
        "ensurepip",
        "test",
        "unittest",
        "sqlite3",
        "dbm",
    ],
    "packages": [
        "kucoin_universal_sdk",
    ],
}

setup(
    app=APP,
    name=APP_NAME,
    data_files=data_files,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
