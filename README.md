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


### ✅ 应用权限说明
- ❌ **不需要登录账号**
- ❌ **不需要管理员权限**
- ❌ **不读取本地文件**
- ❌ **不访问通讯录 / 相册 / 麦克风 / 摄像头**
- ❌ **不采集任何个人信息**


应用仅会进行以下操作：

- ✅ **访问网络**：从公开的交易所 API 获取币种价格数据  
- ✅ **后台运行**：以菜单栏应用形式常驻运行

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


### ⚠️ macOS 安全提示说明

首次打开应用时，macOS 可能会提示：

> **“Apple 无法验证 ‘CoinPriceBar’ 是否包含可能危害 Mac 安全或泄漏隐私的恶意软件。”**

这是因为本应用 **未通过 Apple Developer ID 签名和公证（Notarization）**，属于 macOS 的正常安全机制提示。

#### 如何正常打开：

1. 打开 **系统设置 → 隐私与安全性** , 如果不知道在哪可以通过下面命令快速打开设置
```bash
open "x-apple.systempreferences:com.apple.preference.security?Privacy"
```
2. 在页面底部找到 CoinPriceBar
3. 点击 **仍要打开**
4. 再次确认即可

> 该操作只需进行一次，后续启动不会再次提示。


### 📌 安全声明

- 本项目为 **开源项目**
- 所有源码可在仓库中查看
- 应用不会在后台执行任何与币价展示无关的操作
- **本项目不构成任何投资建议**

如果你对安全性有更高要求，欢迎自行从源码构建应用。