import json
import logging
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlparse

from .config import (
    AppConfig,
    DEFAULT_CONFIG_PATH,
    PERFORMANCE_PRESETS,
    SUPPORTED_EXCHANGES,
    SUPPORTED_LANGUAGES,
    TickerConfig,
)
from .sources import BinancePriceSource, KucoinPriceSource


class ConfigPanelServer:
    def __init__(
        self,
        get_config: Callable[[], AppConfig],
        get_tickers: Callable[[], list[TickerConfig]],
        save_config: Callable[[dict], AppConfig],
    ):
        self.get_config = get_config
        self.get_tickers = get_tickers
        self.save_config = save_config
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.port: int | None = None
        self.symbol_cache: dict[str, tuple[float, list[str]]] = {}
        self.symbol_cache_ttl = 300.0

    def _get_symbol_provider(self, exchange: str):
        return {
            "kucoin": KucoinPriceSource,
            "binance": BinancePriceSource,
        }.get(exchange.lower())

    def _list_symbols(self, exchange: str) -> list[str]:
        exchange = exchange.lower()
        now = time.monotonic()
        cached = self.symbol_cache.get(exchange)
        if cached and now - cached[0] < self.symbol_cache_ttl:
            return cached[1]
        provider = self._get_symbol_provider(exchange)
        if not provider:
            return []
        try:
            symbols = provider(lambda *_: None, lambda *_: None).list_symbols()
        except Exception as e:
            logging.warning(f"获取 {exchange} 交易对列表失败: {e}")
            symbols = []
        self.symbol_cache[exchange] = (now, symbols)
        return symbols

    def start(self) -> None:
        if self.httpd:
            return
        server = self

        class Handler(BaseHTTPRequestHandler):
            def _send_json(self, payload: dict, status: int = 200):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_html(self, content: str):
                body = content.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path in {"/", "/index.html"}:
                    self._send_html(server._build_html())
                    return
                if parsed.path == "/api/config":
                    self._send_json(server._serialize_state())
                    return
                if parsed.path == "/api/symbols":
                    exchange = parse_qs(parsed.query).get("exchange", [""])[0]
                    self._send_json({"exchange": exchange, "symbols": server._list_symbols(exchange)})
                    return
                self._send_json({"error": "Not found"}, status=404)

            def do_POST(self):
                if self.path != "/api/config":
                    self._send_json({"error": "Not found"}, status=404)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                try:
                    payload = json.loads(raw)
                    config = server.save_config(payload)
                    self._send_json({"ok": True, "config": server._serialize_config(config)})
                except Exception as e:
                    logging.error(f"保存 UI 配置失败: {e}")
                    self._send_json({"ok": False, "error": str(e)}, status=400)

            def log_message(self, format, *args):
                return

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="ConfigPanelServer")
        self.thread.start()
        logging.info(f"UI 配置面板已启动: http://127.0.0.1:{self.port}")

    def stop(self) -> None:
        if not self.httpd:
            return
        self.httpd.shutdown()
        self.httpd.server_close()
        self.httpd = None
        self.port = None

    def open(self) -> None:
        self.start()
        webbrowser.open_new_tab(f"http://127.0.0.1:{self.port}")

    def _serialize_config(self, config: AppConfig) -> dict:
        from .config import _serialize_default_config
        return _serialize_default_config(config)

    def _serialize_state(self) -> dict:
        config = self.get_config()
        tickers = self.get_tickers()
        prefs = config.ticker_preferences
        items = []
        for index, ticker in enumerate(tickers):
            pref = prefs.get(ticker.key.lower()) or prefs.get(ticker.key) or None
            items.append(
                {
                    "key": ticker.key,
                    "exchange": ticker.exchange,
                    "symbol": ticker.symbol,
                    "display_name": ticker.display_name,
                    "enabled": ticker.enabled,
                    "visible": True if pref is None else pref.visible,
                    "order": index if pref is None else pref.order,
                    "pinned_title": False if pref is None else pref.pinned_title,
                }
            )
        return {
            "config": self._serialize_config(config),
            "tickers": items,
            "configPath": str(DEFAULT_CONFIG_PATH),
            "performancePresets": PERFORMANCE_PRESETS,
            "languages": sorted(SUPPORTED_LANGUAGES),
            "exchanges": SUPPORTED_EXCHANGES,
        }

    def _build_html(self) -> str:
        return """<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>CoinPriceBar UI 配置</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 24px; color: #222; }
    h1 { margin-bottom: 8px; }
    .hint { color: #666; margin-bottom: 18px; }
    .grid { display: grid; grid-template-columns: 180px 1fr; gap: 10px 14px; max-width: 960px; align-items: center; }
    input[type='text'], input[type='number'], select { width: 100%; padding: 8px; box-sizing: border-box; }
    input[type='checkbox'], input[type='radio'] { transform: scale(1.1); }
    table { border-collapse: collapse; width: 100%; margin-top: 18px; }
    th, td { border-bottom: 1px solid #e5e5e5; padding: 8px; text-align: left; vertical-align: middle; }
    tr.dragging { opacity: 0.4; }
    .actions { margin-top: 20px; display: flex; gap: 12px; flex-wrap: wrap; }
    button { padding: 10px 16px; cursor: pointer; }
    .status { margin-top: 12px; color: #0a7; }
    .error { color: #c33; }
    .muted { color: #777; font-size: 12px; }
    .inline { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    .exchange-grid { display: flex; gap: 18px; flex-wrap: wrap; }
    .drag-handle { cursor: grab; color: #888; font-size: 18px; }
    .section-title { margin-top: 28px; margin-bottom: 10px; }
  </style>
</head>
<body>
  <h1 id=\"title\">CoinPriceBar UI 配置面板</h1>
  <div id=\"hint\" class=\"hint\">这里编辑的是 UI 展示配置与监控项配置。</div>
  <div class=\"grid\">
    <label for=\"language\" data-i18n=\"language\">语言</label>
    <select id=\"language\"></select>

    <label data-i18n=\"exchange_enable\">启用交易所</label>
    <div id=\"exchange_flags\" class=\"exchange-grid\"></div>

    <label for=\"max_visible\" data-i18n=\"max_visible\">显示数量</label><input id=\"max_visible\" type=\"number\" min=\"1\" />
    <label for=\"title_index\" data-i18n=\"title_index\">标题索引</label><input id=\"title_index\" type=\"number\" min=\"0\" />
    <label for=\"title_template\" data-i18n=\"title_template\">标题模板</label><input id=\"title_template\" type=\"text\" />
    <label for=\"menu_template\" data-i18n=\"menu_template\">菜单模板</label><input id=\"menu_template\" type=\"text\" />
    <label for=\"display_fields\" data-i18n=\"display_fields\">降级字段</label><input id=\"display_fields\" type=\"text\" />
    <label for=\"show_exchange_links\" data-i18n=\"show_exchange_links\">显示交易所链接</label><input id=\"show_exchange_links\" type=\"checkbox\" />
    <label for=\"performance_mode\" data-i18n=\"performance_mode\">性能模式</label>
    <div>
      <select id=\"performance_mode\"></select>
      <div id=\"performance_hint\" class=\"muted\">稳定 / 平衡 / 实时 / 自定义</div>
    </div>
    <label for=\"ui_refresh_interval\" data-i18n=\"refresh_interval\">自定义刷新频率（秒）</label>
    <div>
      <input id=\"ui_refresh_interval\" type=\"number\" min=\"0.05\" step=\"0.01\" />
      <div id=\"custom_hint\" class=\"muted\">当性能模式为“自定义”时生效</div>
    </div>
  </div>

  <h2 class=\"section-title\" data-i18n=\"ticker_list\">监控交易对配置</h2>
  <table>
    <thead>
      <tr>
        <th></th>
        <th data-i18n=\"enabled\">启用监控</th>
        <th data-i18n=\"visible\">显示</th>
        <th data-i18n=\"pinned_title\">置顶标题</th>
        <th data-i18n=\"exchange\">交易所</th>
        <th data-i18n=\"symbol\">交易对</th>
        <th data-i18n=\"display_name\">名称</th>
        <th data-i18n=\"remove\">删除</th>
      </tr>
    </thead>
    <tbody id=\"ticker_rows\"></tbody>
  </table>

  <div class=\"actions\">
    <button id=\"add_ticker_btn\" data-i18n=\"add_ticker\">添加交易对</button>
    <button id=\"save_btn\" data-i18n=\"save\">保存并应用</button>
    <button id=\"reload_btn\" data-i18n=\"reload\">重新读取当前配置</button>
  </div>
  <div id=\"status\" class=\"status\"></div>

  <script>
    let current = null;
    let tickerRows = [];
    let symbolOptions = {};
    const I18N = {
      'zh-CN': {
        title: 'CoinPriceBar UI 配置面板', hint: '这里编辑的是 UI 展示配置与监控项配置。',
        language: '语言', exchange_enable: '启用交易所', max_visible: '显示数量', title_index: '标题索引',
        title_template: '标题模板', menu_template: '菜单模板', display_fields: '降级字段',
        show_exchange_links: '显示交易所链接', performance_mode: '性能模式', refresh_interval: '自定义刷新频率（秒）',
        ticker_list: '监控交易对配置', enabled: '启用监控', visible: '显示', pinned_title: '置顶标题', exchange: '交易所',
        symbol: '交易对', display_name: '名称', remove: '删除', add_ticker: '添加交易对', save: '保存并应用', reload: '重新读取当前配置',
        performance_hint: '稳定 / 平衡 / 实时 / 自定义', custom_hint: '当性能模式为“自定义”时生效',
        stable: '稳定', balanced: '平衡', realtime: '实时', custom: '自定义', remove_btn: '删除',
      },
      'en-US': {
        title: 'CoinPriceBar UI Config Panel', hint: 'Edit UI display settings and monitored tickers here.',
        language: 'Language', exchange_enable: 'Enabled exchanges', max_visible: 'Visible count', title_index: 'Title index',
        title_template: 'Title template', menu_template: 'Menu template', display_fields: 'Fallback fields',
        show_exchange_links: 'Show exchange links', performance_mode: 'Performance mode', refresh_interval: 'Custom refresh interval (seconds)',
        ticker_list: 'Monitored tickers', enabled: 'Enabled', visible: 'Visible', pinned_title: 'Pin to title', exchange: 'Exchange',
        symbol: 'Symbol', display_name: 'Name', remove: 'Remove', add_ticker: 'Add ticker', save: 'Save & apply', reload: 'Reload config',
        performance_hint: 'Stable / Balanced / Realtime / Custom', custom_hint: 'Only used when performance mode is Custom',
        stable: 'Stable', balanced: 'Balanced', realtime: 'Realtime', custom: 'Custom', remove_btn: 'Remove',
      }
    };

    function tr(key) {
      const lang = document.getElementById('language').value || current?.config?.ui?.language || 'zh-CN';
      return (I18N[lang] && I18N[lang][key]) || key;
    }

    function applyI18n() {
      document.getElementById('title').textContent = tr('title');
      document.getElementById('hint').textContent = tr('hint');
      document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = tr(el.dataset.i18n); });
      document.getElementById('performance_hint').textContent = tr('performance_hint');
      document.getElementById('custom_hint').textContent = tr('custom_hint');
      fillPerformanceModes(current.performancePresets, document.getElementById('performance_mode').value || current.config.ui.performance_mode || 'balanced');
      renderTickerRows();
    }

    function fillLanguages(languages, selected) {
      const select = document.getElementById('language');
      select.innerHTML = '';
      languages.forEach(lang => {
        const opt = document.createElement('option');
        opt.value = lang;
        opt.textContent = lang;
        opt.selected = lang === selected;
        select.appendChild(opt);
      });
    }

    function fillExchangeFlags(exchanges, enabledMap) {
      const wrap = document.getElementById('exchange_flags');
      wrap.innerHTML = '';
      Object.entries(exchanges).forEach(([key, label]) => {
        const row = document.createElement('label');
        row.className = 'inline';
        row.innerHTML = `<input type=\"checkbox\" data-exchange=\"${key}\" ${enabledMap?.[key]?.enabled !== false ? 'checked' : ''}> ${label}`;
        wrap.appendChild(row);
      });
    }

    function fillPerformanceModes(presets, selectedMode) {
      const select = document.getElementById('performance_mode');
      select.innerHTML = '';
      Object.keys(presets).forEach(key => {
        const opt = document.createElement('option');
        opt.value = key;
        opt.textContent = `${tr(key)}${presets[key] ? ` (${presets[key]}s)` : ''}`;
        opt.selected = key === selectedMode;
        select.appendChild(opt);
      });
    }

    function enableCustomRefreshInput() {
      document.getElementById('ui_refresh_interval').disabled = document.getElementById('performance_mode').value !== 'custom';
    }

    async function ensureSymbols(exchange) {
      exchange = String(exchange || '').toLowerCase();
      if (!exchange) return [];
      if (symbolOptions[exchange]) return symbolOptions[exchange];
      const res = await fetch(`/api/symbols?exchange=${encodeURIComponent(exchange)}`);
      const data = await res.json();
      symbolOptions[exchange] = data.symbols || [];
      return symbolOptions[exchange];
    }

    function buildSymbolDatalist(exchange) {
      const id = `symbols-${exchange}`;
      let list = document.getElementById(id);
      if (!list) {
        list = document.createElement('datalist');
        list.id = id;
        document.body.appendChild(list);
      }
      list.innerHTML = (symbolOptions[exchange] || []).slice(0, 500).map(symbol => `<option value=\"${symbol}\"></option>`).join('');
      return id;
    }

    async function refreshSymbolInput(row) {
      const item = JSON.parse(row.dataset.item);
      await ensureSymbols(item.exchange);
      const input = row.querySelector('input[data-field="symbol"]');
      input.setAttribute('list', buildSymbolDatalist(item.exchange));
    }

    function attachDragHandlers(row) {
      row.draggable = true;
      row.addEventListener('dragstart', () => row.classList.add('dragging'));
      row.addEventListener('dragend', () => {
        row.classList.remove('dragging');
        syncRowOrder();
      });
      row.addEventListener('dragover', event => {
        event.preventDefault();
        const tbody = document.getElementById('ticker_rows');
        const dragging = tbody.querySelector('.dragging');
        if (!dragging || dragging === row) return;
        const rect = row.getBoundingClientRect();
        const insertAfter = event.clientY > rect.top + rect.height / 2;
        tbody.insertBefore(dragging, insertAfter ? row.nextSibling : row);
      });
    }

    function syncRowOrder() {
      const rows = [...document.querySelectorAll('#ticker_rows tr')];
      tickerRows = rows.map((row, index) => ({ ...JSON.parse(row.dataset.item), order: index }));
      renderTickerRows(false);
    }

    function renderTickerRows(reset = true) {
      const tbody = document.getElementById('ticker_rows');
      if (reset) tickerRows = [...tickerRows].sort((a, b) => a.order - b.order);
      tbody.innerHTML = '';
      tickerRows.forEach((ticker, index) => {
        const row = document.createElement('tr');
        row.dataset.item = JSON.stringify({ ...ticker, order: index });
        row.innerHTML = `
          <td class=\"drag-handle\">☰</td>
          <td><input type=\"checkbox\" data-field=\"enabled\" ${ticker.enabled ? 'checked' : ''}></td>
          <td><input type=\"checkbox\" data-field=\"visible\" ${ticker.visible ? 'checked' : ''}></td>
          <td><input type=\"radio\" name=\"pinned_title\" data-field=\"pinned_title\" ${ticker.pinned_title ? 'checked' : ''}></td>
          <td><select data-field=\"exchange\">${Object.entries(current.exchanges).map(([key, label]) => `<option value=\"${key}\" ${ticker.exchange === key ? 'selected' : ''}>${label}</option>`).join('')}</select></td>
          <td><input type=\"text\" data-field=\"symbol\" value=\"${ticker.symbol || ''}\" autocomplete=\"off\"></td>
          <td><input type=\"text\" data-field=\"display_name\" value=\"${ticker.display_name || ''}\"></td>
          <td><button type=\"button\" data-action=\"remove\">${tr('remove_btn')}</button></td>`;
        attachDragHandlers(row);
        refreshSymbolInput(row);
        row.querySelectorAll('input,select').forEach(input => {
          input.addEventListener('change', async () => {
            const field = input.dataset.field;
            const item = JSON.parse(row.dataset.item);
            if (field === 'enabled' || field === 'visible' || field === 'pinned_title') item[field] = input.checked;
            else item[field] = input.value;
            row.dataset.item = JSON.stringify(item);
            if (field === 'exchange') await refreshSymbolInput(row);
            if (field === 'pinned_title' && input.checked) {
              document.querySelectorAll('#ticker_rows input[data-field="pinned_title"]').forEach(other => {
                if (other !== input) other.checked = false;
                const otherRow = other.closest('tr');
                const otherItem = JSON.parse(otherRow.dataset.item);
                if (other !== input) otherItem.pinned_title = false;
                otherRow.dataset.item = JSON.stringify(otherItem);
              });
            }
            syncRowOrder();
          });
        });
        row.querySelector('[data-action="remove"]').addEventListener('click', () => {
          tickerRows.splice(index, 1);
          tickerRows = tickerRows.map((item, idx) => ({ ...item, order: idx }));
          renderTickerRows();
        });
        tbody.appendChild(row);
      });
    }

    async function loadState() {
      const res = await fetch('/api/config');
      current = await res.json();
      const ui = current.config.ui;
      fillLanguages(current.languages, ui.language || 'zh-CN');
      fillExchangeFlags(current.exchanges, ui.exchanges || {});
      document.getElementById('max_visible').value = ui.max_visible;
      document.getElementById('title_index').value = ui.title_index;
      document.getElementById('title_template').value = ui.title_template;
      document.getElementById('menu_template').value = ui.menu_template;
      document.getElementById('display_fields').value = ui.display_fields.join(',');
      document.getElementById('show_exchange_links').checked = !!ui.show_exchange_links;
      fillPerformanceModes(current.performancePresets, ui.performance_mode || 'balanced');
      document.getElementById('ui_refresh_interval').value = ui.ui_refresh_interval;
      tickerRows = current.tickers.map((ticker, index) => ({ ...ticker, order: ticker.order ?? index }));
      enableCustomRefreshInput();
      applyI18n();
      setStatus(`已读取配置：${current.configPath}`);
    }

    function setStatus(msg, isError = false) {
      const el = document.getElementById('status');
      el.textContent = msg;
      el.className = isError ? 'status error' : 'status';
    }

    function collectPayload() {
      syncRowOrder();
      const tickers = tickerRows.map(item => ({
        exchange: item.exchange,
        symbol: item.symbol,
        display_name: item.display_name,
        enabled: !!item.enabled,
      }));
      const ticker_preferences = tickerRows.map((item, index) => ({
        key: `${String(item.exchange).toLowerCase()}::${String(item.symbol).trim().toUpperCase().replaceAll('_', '-')}`,
        visible: !!item.visible,
        pinned_title: !!item.pinned_title,
        order: index,
      }));
      const exchanges = {};
      document.querySelectorAll('#exchange_flags input[data-exchange]').forEach(input => {
        exchanges[input.dataset.exchange] = { enabled: input.checked };
      });
      return {
        ui: {
          language: document.getElementById('language').value,
          max_visible: Number(document.getElementById('max_visible').value || 1),
          title_index: Number(document.getElementById('title_index').value || 0),
          title_template: document.getElementById('title_template').value,
          menu_template: document.getElementById('menu_template').value,
          display_fields: document.getElementById('display_fields').value.split(',').map(v => v.trim()).filter(Boolean),
          show_exchange_links: document.getElementById('show_exchange_links').checked,
          performance_mode: document.getElementById('performance_mode').value,
          ui_refresh_interval: Number(document.getElementById('ui_refresh_interval').value || 0.25),
          exchanges,
          tickers,
          ticker_preferences,
        }
      };
    }

    async function saveState() {
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(collectPayload())
      });
      const data = await res.json();
      if (!data.ok) {
        setStatus(data.error || '保存失败', true);
        return;
      }
      setStatus('保存成功，菜单栏 UI 已刷新');
      await loadState();
    }

    document.getElementById('language').addEventListener('change', applyI18n);
    document.getElementById('performance_mode').addEventListener('change', () => { enableCustomRefreshInput(); applyI18n(); });
    document.getElementById('add_ticker_btn').addEventListener('click', () => {
      tickerRows.push({ exchange: 'kucoin', symbol: 'BTC-USDT', display_name: '', enabled: true, visible: true, pinned_title: false, order: tickerRows.length });
      renderTickerRows();
    });
    document.getElementById('save_btn').addEventListener('click', saveState);
    document.getElementById('reload_btn').addEventListener('click', loadState);
    loadState().catch(err => setStatus(err.message, true));
  </script>
</body>
</html>
"""
