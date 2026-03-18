# CryptoTickerBar

A lightweight **macOS menu bar app** for displaying **cryptocurrency prices** in real time.  
Built with **Python + rumps + py2app**.

The current version uses **KuCoin** as the data source.  
Support for **Binance / OKX / Bybit** is planned.

![alt text](docs/screenshot.png)

---

## ✨ Features

- ✅ Native macOS menu bar app (no Dock icon)
- ✅ Real‑time crypto price display (BTC / ETH / USDT)
- ✅ WebSocket‑based updates
- ✅ Apple Silicon & Intel builds
- ✅ One‑line installer

---


### ✅ Permissions

The application:

- ❌ Does NOT require login
- ❌ Does NOT require administrator privileges
- ❌ Does NOT access local files
- ❌ Does NOT access contacts, photos, microphone, or camera
- ❌ Does NOT collect any personal data

It only performs the following actions:

- ✅ **Network access**: fetches public price data from exchange APIs
- ✅ **Background execution**: runs as a menu bar app

---

## 📊 Supported Exchanges

| Exchange | Status |
|--------|--------|
| KuCoin | ✅ Supported |
| Binance | 🚧 Planned |
| OKX | 🚧 Planned |
| Bybit | 🚧 Planned |

---

## 📦 Install

### One‑line installer (recommended)

```bash
bash -c "$(curl -fsSL https://github.com/LY1806620741/CoinPriceBar/releases/latest/download/install-macos.sh)"
```

### ⚠️ macOS Security Warning

On first launch, macOS may show the following message:

> **“Apple cannot verify that ‘CoinPriceBar’ is free from malware.”**

This is expected behavior for applications that are **not signed or notarized by Apple**.

#### How to open the app:

1. Open **System Settings → Privacy & Security** , If you don't know where to start, you can quickly open the settings with the following commands
```bash
open "x-apple.systempreferences:com.apple.preference.security?Privacy"
```
2. Locate CoinPriceBar at the bottom
3. Click **Open Anyway**
4. Confirm once more

> This only needs to be done once.
---


### 📌 Security Notice

- This is an **open-source project**
- All source code is publicly available
- The app performs no actions beyond price display
- **This project does not provide financial advice**

Advanced users are welcome to build the app from source.