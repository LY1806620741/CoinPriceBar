# CoinPriceBar

[English](./README.en.md)

一个运行在 **macOS 菜单栏（Status Bar）** 的加密货币价格显示应用。  
基于 **Python + rumps + py2app** 构建，用于实时展示多交易所币价。

当前版本已支持 **KuCoin + Binance**，并支持通过配置文件控制显示数量、顺序和显示字段。

![alt text](docs/screenshot.png)
---

## ✨ 功能特性

- ✅ macOS 菜单栏常驻（不占 Dock）
- ✅ 多信息源插件化架构，便于继续扩展 OKX / Bybit 等交易所
- ✅ 已支持 **KuCoin** 与 **Binance** WebSocket 实时行情
- ✅ 可配置显示币种数量
- ✅ 可配置显示顺序
- ✅ 可配置显示项 / 标题模板 / 菜单模板
- ✅ Apple Silicon / Intel 双架构
- ✅ 一键下载安装（自动识别平台）


### ✅ 应用权限说明
- ❌ **不需要登录账号**
- ❌ **不需要管理员权限**
- ❌ **不读取本地文件**
- ❌ **不访问通讯录 / 相册 / 麦克风 / 摄像头**
- ❌ **不采集任何个人信息**


应用仅会进行以下操作：

- ✅ **访问网络**：从公开的交易所 WebSocket API 获取币种价格数据  
- ✅ **后台运行**：以菜单栏应用形式常驻运行

---

## 📊 支持的交易所

| 交易所 | 状态 |
|------|------|
| KuCoin | ✅ 已支持 |
| Binance | ✅ 已支持 |
| OKX | 🚧 可扩展 |
| Bybit | 🚧 可扩展 |

---

## ⚙️ 配置说明

程序首次启动会在项目根目录自动生成 `config.json`。

> `config.json` 现在是 **UI 配置**：只控制菜单栏显示方式，不负责定义交易所或交易对。
> 当前默认监控的交易所与交易对由 `coinpricebar/config.py` 内的 `DEFAULT_TICKERS` 管理。

示例：

```json
{
  "ui": {
    "max_visible": 4,
    "title_index": 0,
    "display_fields": ["exchange", "symbol", "price", "change_percent", "status"],
    "title_template": "{exchange}:{symbol} {price}",
    "menu_template": "{exchange}:{symbol} {price} ({change_percent})",
    "show_exchange_links": true,
    "tickers": [
      { "key": "kucoin::KCS-USDT", "visible": true, "order": 0, "pinned_title": true },
      { "key": "kucoin::BTC-USDT", "visible": true, "order": 1, "pinned_title": false },
      { "key": "binance::BTC-USDT", "visible": false, "order": 3, "pinned_title": false }
    ]
  }
}
```

### 配置项说明

- `max_visible`：最多显示多少个交易对
- `title_index`：哪一个交易对显示在菜单栏标题上（从 `0` 开始）
- `display_fields`：当模板字段无效时的降级显示项，支持：
  - `exchange`
  - `symbol`
  - `price`
  - `change`
  - `change_percent`
  - `status`
- `title_template`：菜单栏标题模板
- `menu_template`：下拉菜单每一项模板
- `show_exchange_links`：是否显示“打开交易所官网”入口
- `tickers`：UI 显示偏好，可配置每个默认监控项是否显示、显示顺序，以及是否置顶到菜单栏标题
- 菜单支持 **UI配置编辑**、**打开配置文件** 和 **重载UI配置**，修改 `config.json` 后可直接重载生效（仅影响 UI 显示，不会改动监控源）

### UI 行为说明

- `DEFAULT_TICKERS` 中的项目会持续订阅和接收数据
- `ui.tickers` 只决定“是否显示、显示顺序、谁显示在标题上”
- 即使某项当前不显示，也仍然保持监控，后续重新显示时能立即看到最新数据

### 监控项调整

如果你想修改默认监控项，请编辑 `coinpricebar/config.py` 中的 `DEFAULT_TICKERS`：

- 顺序 = 展示顺序
- 前 `max_visible` 个 = 实际显示数量
- 每项格式：`("交易所", "交易对", "显示名称")`

### 项目结构

- `KCSApp.py`：兼容入口
- `coinpricebar/main.py`：应用启动入口
- `coinpricebar/app.py`：菜单栏 UI 与监控调度
- `coinpricebar/config.py`：UI 配置与默认监控项
- `coinpricebar/sources/`：交易所插件

---

## 📦 下载与安装

### 使用 just 管理常用命令

如果本机已安装 `just`，推荐使用：

```bash
just
just install
just run
just test
just compile
just logs
```

如未安装 `just`，可在 macOS 上使用：

```bash
brew install just
```

### ✅ 一键安装（推荐）

```bash
bash -c "$(curl -fsSL https://github.com/LY1806620741/CoinPriceBar/releases/latest/download/install-macos.sh)"
```

### 本地运行

```bash
just install
just run
```

### 运行测试

```bash
just test
```

也可以运行单个测试模块：

```bash
just test-file tests.test_ui_render
```

当前标准测试位于 `tests/` 目录，覆盖：
- UI 涨跌渲染
- 多交易对菜单刷新

### 打包 `.app`

```bash
just build
```

---

## ⚠️ macOS 安全提示说明

首次打开应用时，macOS 可能会提示：

> **“Apple 无法验证 ‘CoinPriceBar’ 是否包含可能危害 Mac 安全或泄漏隐私的恶意软件。”**

这是因为本应用 **未通过 Apple Developer ID 签名和公证（Notarization）**，属于 macOS 的正常安全机制提示。

### 如何正常打开

1. 打开 **系统设置 → 隐私与安全性**，如果不知道在哪，可以执行：
```bash
open "x-apple.systempreferences:com.apple.preference.security?Privacy"
```
2. 在页面底部找到 CoinPriceBar
3. 点击 **仍要打开**
4. 再次确认即可

> 该操作只需进行一次，后续启动不会再次提示。

---

## 📌 安全声明

- 本项目为 **开源项目**
- 所有源码可在仓库中查看
- 应用不会在后台执行任何与币价展示无关的操作
- **本项目不构成任何投资建议**
