# CryptoTickerBar

一个简单的运行在 **macOS 菜单栏（Status Bar）** 的 **加密货币价格显示应用**。  
基于 **Python + rumps + py2app** 构建，用于实时展示主流币种价格。

当前版本以 **KuCoin** 作为数据源

![alt text](docs/screenshot.png)
---

## ✨ 功能特性

- ✅ macOS 菜单栏常驻（不占 Dock）
- ✅ 实时显示币种价格（如 BTC / ETH / USDT）
- ✅ 支持 WebSocket 实时拉取
- ✅ Apple Silicon / Intel 双架构
- ✅ 一键下载安装（自动识别平台）

---

## 📊 支持的交易所

| 交易所 | 状态 |
|------|------|
| KuCoin | ✅ 已支持 |
| Binance | 🚧 不支持 |
| OKX | 🚧 不支持 |
| Bybit | 🚧 不支持 |

---

## 📦 下载与安装

### ✅ 一键安装（推荐）

```bash
bash -c "$(curl -fsSL https://github.com/LY1806620741/CoinPriceBar/releases/latest/download/install-macos.sh)"
```