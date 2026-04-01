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
    EXCHANGE_ICON_PRESETS,
    FORMAT_PRESETS,
    ICON_STYLE_OPTIONS,
    OFFICIAL_EXCHANGE_ICON_URLS,
    PERFORMANCE_PRESETS,
    SUPPORTED_EXCHANGES,
    SUPPORTED_LANGUAGES,
    TEMPLATE_EXAMPLES,
    TEMPLATE_VARIABLES,
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
            pref = prefs.get(ticker.key.lower()) or prefs.get(ticker.key)
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
            "formatPresets": FORMAT_PRESETS,
            "templateExamples": list(TEMPLATE_EXAMPLES),
            "templateVariables": list(TEMPLATE_VARIABLES),
            "iconStyleOptions": dict(ICON_STYLE_OPTIONS),
            "iconPresets": EXCHANGE_ICON_PRESETS,
            "officialExchangeIconUrls": OFFICIAL_EXCHANGE_ICON_URLS,
            "languages": sorted(SUPPORTED_LANGUAGES),
            "exchanges": SUPPORTED_EXCHANGES,
            "exchangeShortNames": config.exchange_short_names,
        }

    def _build_html(self) -> str:
        return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>CoinPriceBar UI 配置</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 24px; color: #222; }
    h1 { margin-bottom: 8px; }
    .hint { color: #666; margin-bottom: 18px; }
    .grid { display: grid; grid-template-columns: 180px 1fr; gap: 10px 14px; max-width: 1100px; align-items: center; }
    input[type='text'], input[type='number'], select, textarea { width: 100%; padding: 8px; box-sizing: border-box; }
    input[type='checkbox'], input[type='radio'] { transform: scale(1.05); }
    textarea { min-height: 72px; resize: vertical; }
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
    .drag-handle { cursor: grab; color: #888; font-size: 18px; user-select: none; }
    .section-title { margin-top: 28px; margin-bottom: 10px; }
    .small-input { width: 120px; }
    .examples { background: #f8f8f8; border-radius: 8px; padding: 10px 12px; }
    .examples code { display: block; margin: 4px 0; }
    .reference-box { background: #f8f8f8; border-radius: 8px; padding: 10px 12px; }
    .reference-box table { margin-top: 0; }
    .reference-box th, .reference-box td { border-bottom: 1px solid #ececec; padding: 6px 8px; font-size: 13px; }
    .preview-box { background: #111827; color: #f9fafb; border-radius: 10px; padding: 12px 14px; }
    .preview-row { display: flex; align-items: center; gap: 8px; min-height: 28px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .preview-label { color: #9ca3af; font-size: 12px; margin-bottom: 6px; }
    .official-icon { width: auto; height: 18px; max-width: 22px; object-fit: contain; vertical-align: middle; display: inline-block; }
    .official-icon.logo-wide { max-width: 72px; height: 18px; }
    .official-icon-fallback { display: inline-flex; align-items: center; justify-content: center; min-width: 22px; height: 18px; padding: 0 6px; border-radius: 5px; background: #374151; color: #fff; font-size: 11px; line-height: 1; }
  </style>
</head>
<body>
  <h1 id="title">CoinPriceBar UI 配置面板</h1>
  <div id="hint" class="hint">这里编辑的是 UI 展示配置与监控项配置。</div>
  <div class="grid">
    <label for="language" data-i18n="language">语言</label>
    <select id="language"></select>
    <label data-i18n="exchange_enable">启用交易所</label>
    <div id="exchange_flags" class="exchange-grid"></div>
    <label for="max_visible" data-i18n="max_visible">显示数量</label>
    <input id="max_visible" type="number" min="1" />
    <label for="format_mode" data-i18n="format_mode">格式模式</label>
    <div>
      <select id="format_mode"></select>
      <div id="format_hint" class="muted">短格式 / 长格式 / 自定义</div>
    </div>
    <label for="icon_style" data-i18n="icon_style">交易所图标</label>
    <select id="icon_style"></select>
    <label data-i18n="exchange_icons">交易所图标预览</label>
    <div id="exchange_icons" class="exchange-grid"></div>
    <label data-i18n="exchange_short_names">交易所短标识</label>
    <div id="exchange_short_names" class="exchange-grid"></div>
    <label for="title_template" data-i18n="title_template">标题模板</label>
    <textarea id="title_template"></textarea>
    <label for="menu_template" data-i18n="menu_template">菜单模板</label>
    <textarea id="menu_template"></textarea>
    <label data-i18n="template_examples">模板例子</label>
    <div id="template_examples" class="examples"></div>

    <label data-i18n="template_variables">变量列表</label>
    <div id="template_variables" class="reference-box"></div>

    <label data-i18n="style_options">样式列表</label>
    <div id="style_options" class="reference-box"></div>

    <label data-i18n="live_preview">实时预览</label>
    <div class="preview-box">
      <div class="preview-label" data-i18n="title_preview">标题预览</div>
      <div id="title_preview" class="preview-row"></div>
      <div style="height: 10px;"></div>
      <div class="preview-label" data-i18n="menu_preview">菜单预览</div>
      <div id="menu_preview" class="preview-row"></div>
    </div>

    <label for="display_fields" data-i18n="display_fields">降级字段</label>
    <input id="display_fields" type="text" />
    <label for="show_exchange_links" data-i18n="show_exchange_links">显示交易所链接</label>
    <input id="show_exchange_links" type="checkbox" />
    <label for="performance_mode" data-i18n="performance_mode">性能模式</label>
    <div>
      <select id="performance_mode"></select>
      <div id="performance_hint" class="muted">稳定 / 平衡 / 实时 / 自定义</div>
    </div>
    <label for="ui_refresh_interval" data-i18n="refresh_interval">自定义刷新频率（秒）</label>
    <div>
      <input id="ui_refresh_interval" type="number" min="0.05" step="0.01" class="small-input" />
      <div id="custom_hint" class="muted">当性能模式为“自定义”时生效</div>
    </div>
  </div>
  <h2 class="section-title" data-i18n="ticker_list">监控交易对配置</h2>
  <table>
    <thead>
      <tr>
        <th></th>
        <th data-i18n="enabled">启用监控</th>
        <th data-i18n="visible">显示</th>
        <th data-i18n="pinned_title">置顶标题</th>
        <th data-i18n="exchange">交易所</th>
        <th data-i18n="symbol">交易对</th>
        <th data-i18n="display_name">名称</th>
        <th data-i18n="remove">删除</th>
      </tr>
    </thead>
    <tbody id="ticker_rows"></tbody>
  </table>
  <div class="actions">
    <button id="add_ticker_btn" data-i18n="add_ticker">添加交易对</button>
    <button id="save_btn" data-i18n="save">保存并应用</button>
    <button id="reload_btn" data-i18n="reload">重新读取当前配置</button>
  </div>
  <div id="status" class="status"></div>
  <script>
    let current = null;
    let tickerRows = [];
    let symbolOptions = {};
    const I18N = {
      'zh-CN': {
        title: 'CoinPriceBar UI 配置面板', hint: '这里编辑的是 UI 展示配置与监控项配置。',
        language: '语言', exchange_enable: '启用交易所', exchange_short_names: '交易所短标识', exchange_icons: '交易所图标预览', max_visible: '显示数量',
        format_mode: '格式模式', icon_style: '交易所图标', title_template: '标题模板', menu_template: '菜单模板', template_examples: '模板例子',
        template_variables: '变量列表', style_options: '样式列表',
        live_preview: '实时预览', title_preview: '标题预览', menu_preview: '菜单预览',
        display_fields: '降级字段', show_exchange_links: '显示交易所链接', performance_mode: '性能模式',
        refresh_interval: '自定义刷新频率（秒）', ticker_list: '监控交易对配置', enabled: '启用监控', visible: '显示',
        pinned_title: '置顶标题', exchange: '交易所', symbol: '交易对', display_name: '名称', remove: '删除',
        add_ticker: '添加交易对', save: '保存并应用', reload: '重新读取当前配置',
        performance_hint: '稳定 / 平衡 / 实时 / 自定义', custom_hint: '当性能模式为“自定义”时生效', format_hint: '短格式 / 长格式 / 自定义',
        stable: '稳定', balanced: '平衡', realtime: '实时', custom: '自定义', short: '短格式', long: '长格式',
        none: '无图标', emoji: 'Emoji 图标', text: '文本图标', official: '官方图标', remove_btn: '删除',
        saved: '保存成功，已应用到状态栏。', loading: '加载中...', custom_only: '仅在自定义模式下可编辑模板。'
      },
      'en-US': {
        title: 'CoinPriceBar UI Config Panel', hint: 'Edit UI display settings and monitored tickers here.',
        language: 'Language', exchange_enable: 'Enabled exchanges', exchange_short_names: 'Exchange short labels', exchange_icons: 'Exchange icon preview', max_visible: 'Visible count',
        format_mode: 'Format mode', icon_style: 'Exchange icon', title_template: 'Title template', menu_template: 'Menu template', template_examples: 'Template examples',
        template_variables: 'Variables', style_options: 'Styles',
        live_preview: 'Live preview', title_preview: 'Title preview', menu_preview: 'Menu preview',
        display_fields: 'Fallback fields', show_exchange_links: 'Show exchange links', performance_mode: 'Performance mode',
        refresh_interval: 'Custom refresh interval (seconds)', ticker_list: 'Monitored tickers', enabled: 'Enabled', visible: 'Visible',
        pinned_title: 'Pin to title', exchange: 'Exchange', symbol: 'Symbol', display_name: 'Display name', remove: 'Remove',
        add_ticker: 'Add ticker', save: 'Save and apply', reload: 'Reload current config',
        performance_hint: 'Stable / Balanced / Realtime / Custom', custom_hint: 'Only used when performance mode is Custom', format_hint: 'Short / Long / Custom',
        stable: 'Stable', balanced: 'Balanced', realtime: 'Realtime', custom: 'Custom', short: 'Short', long: 'Long',
        none: 'No icon', emoji: 'Emoji icons', text: 'Text icons', official: 'Official icons', remove_btn: 'Remove',
        saved: 'Saved successfully and applied to the menu bar.', loading: 'Loading...', custom_only: 'Templates are editable only in Custom mode.'
      }
    };

    function tr(key) {
      const lang = document.getElementById('language')?.value || current?.config?.ui?.language || 'zh-CN';
      return (I18N[lang] && I18N[lang][key]) || key;
    }

    function setStatus(message, isError=false) {
      const el = document.getElementById('status');
      el.textContent = message || '';
      el.className = isError ? 'status error' : 'status';
    }

    function isColorDot(ch) {
      return ['🟢', '🔴', '🟡', '⚫'].includes(ch || '');
    }

    function withTrendSuffix(text, change) {
      text = String(text || '').trimEnd();
      if (change > 0) return `${text} 🟢`.trimEnd();
      if (change < 0) return `${text} 🔴`.trimEnd();
      return text;
    }

    function withStatusSuffix(text, status) {
      text = String(text || '').trimEnd();
      const chars = Array.from(text);
      const last = chars[chars.length - 1] || '';
      if (isColorDot(last)) {
        chars.pop();
        text = chars.join('').trimEnd();
      }
      return status ? `${text} ${status}`.trimEnd() : text;
    }

    function currentExchangeShortNames() {
      const values = {};
      document.querySelectorAll('[data-exchange-short]').forEach(input => {
        values[input.dataset.exchangeShort] = String(input.value || '').trim();
      });
      return values;
    }

    function collectExchangeIconsRaw() {
      const values = {};
      document.querySelectorAll('[data-exchange-icon]').forEach(input => {
        values[input.dataset.exchangeIcon] = String(input.value || '');
      });
      return values;
    }

    function buildOfficialIcon(exchange, shortLabel, label) {
      const url = current.officialExchangeIconUrls?.[exchange] || '';
      const isWideLogo = /logo\.(png|svg|jpg|jpeg)$/i.test(url);
      const className = `official-icon${isWideLogo ? ' logo-wide' : ''}`;
      if (!url) {
        return `<span class="official-icon-fallback">${shortLabel}</span>`;
      }
      return `<img class="${className}" src="${url}" alt="${label}" onerror="this.outerHTML='&lt;span class=&quot;official-icon-fallback&quot;&gt;${shortLabel}&lt;/span&gt;'">`;
    }

    function iconHtml(exchange) {
      const style = document.getElementById('icon_style').value;
      if (style === 'official') {
        const label = current.exchanges?.[exchange] || exchange.toUpperCase();
        const shortLabel = currentExchangeShortNames()[exchange] || exchange.toUpperCase();
        return buildOfficialIcon(exchange, shortLabel, label);
      }
      const icons = collectExchangeIconsRaw();
      return `<span>${icons[exchange] || ''}</span>`;
    }

    function previewContext() {
      const firstTicker = tickerRows[0] || { exchange: 'kucoin', symbol: 'BTC-USDT', display_name: 'BTC' };
      const exchange = String(firstTicker.exchange || 'kucoin').toLowerCase();
      const shortNames = currentExchangeShortNames();
      const exchangeShort = shortNames[exchange] || exchange.toUpperCase();
      const exchangeFull = current.exchanges?.[exchange] || exchange;
      const style = document.getElementById('icon_style').value;
      const icons = collectExchangeIconsRaw();
      const exchangeIcon = style === 'official' ? '' : (icons[exchange] || '');
      return {
        exchange: exchangeShort,
        exchange_short: exchangeShort,
        exchange_full: exchangeFull,
        exchange_icon: exchangeIcon,
        symbol: firstTicker.display_name || firstTicker.symbol || 'BTC',
        price: '67019.00',
        change: '↑+520.00',
        change_percent: '↑0.78%',
        status: '在线',
        __exchange: exchange,
        __change_value: 1,
      };
    }

    function formatTemplate(template, context) {
      try {
        return String(template || '').replace(/\{(exchange|exchange_short|exchange_full|exchange_icon|symbol|price|change|change_percent|status)\}/g, (_, key) => context[key] ?? '');
      } catch {
        return `${context.exchange} ${context.symbol} ${context.price}`;
      }
    }

    function renderOneToOnePreview() {
      const context = previewContext();
      const titleTemplate = document.getElementById('title_template').value;
      const menuTemplate = document.getElementById('menu_template').value;
      const titleRaw = formatTemplate(titleTemplate, context).trim() || `${context.exchange} ${context.symbol} ${context.price}`;
      const menuRaw = formatTemplate(menuTemplate, context).trim() || `${context.exchange} ${context.symbol} ${context.price}`;
      const titleText = withTrendSuffix(titleRaw, context.__change_value);
      const menuText = withStatusSuffix(withTrendSuffix(menuRaw, context.__change_value), context.status);
      const iconMarkup = iconHtml(context.__exchange);
      const officialPrefix = document.getElementById('icon_style').value === 'official' ? iconMarkup : '';
      document.getElementById('title_preview').innerHTML = `${officialPrefix}<span>${titleText}</span>`;
      document.getElementById('menu_preview').innerHTML = `${officialPrefix}<span>${menuText}</span>`;
    }

    function applyI18n() {
      document.getElementById('title').textContent = tr('title');
      document.getElementById('hint').textContent = tr('hint');
      document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = tr(el.dataset.i18n); });
      document.getElementById('performance_hint').textContent = tr('performance_hint');
      document.getElementById('custom_hint').textContent = tr('custom_hint');
      document.getElementById('format_hint').textContent = tr('format_hint');
      fillPerformanceModes(current.performancePresets, document.getElementById('performance_mode').value || current.config.ui.performance_mode || 'balanced');
      fillFormatModes(current.formatPresets, document.getElementById('format_mode').value || current.config.ui.format_mode || 'short');
      fillIconStyles(current.iconPresets, document.getElementById('icon_style').value || current.config.ui.icon_style || 'emoji');
      renderTemplateExamples(current.templateExamples || []);
      renderTemplateVariables(current.templateVariables || []);
      renderStyleOptions();
      renderExchangeIcons(current.exchanges, collectExchangeIconsRaw());
      renderTickerRows();
      syncFormatEditorState();
      renderOneToOnePreview();
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
        row.innerHTML = `<input type="checkbox" data-exchange="${key}" ${enabledMap?.[key]?.enabled !== false ? 'checked' : ''}> ${label}`;
        wrap.appendChild(row);
      });
    }

    function fillExchangeShortNames(exchanges, values) {
      const wrap = document.getElementById('exchange_short_names');
      wrap.innerHTML = '';
      Object.entries(exchanges).forEach(([key, label]) => {
        const row = document.createElement('label');
        row.className = 'inline';
        row.innerHTML = `${label} <input type="text" data-exchange-short="${key}" value="${(values && values[key]) || ''}" style="width: 96px;">`;
        wrap.appendChild(row);
      });
    }

    function fillPerformanceModes(presets, selectedMode) {
      const select = document.getElementById('performance_mode');
      select.innerHTML = '';
      Object.keys(presets).forEach(mode => {
        const opt = document.createElement('option');
        opt.value = mode;
        opt.textContent = tr(mode);
        opt.selected = mode === selectedMode;
        select.appendChild(opt);
      });
    }

    function fillFormatModes(presets, selectedMode) {
      const select = document.getElementById('format_mode');
      select.innerHTML = '';
      Object.keys(presets).forEach(mode => {
        const opt = document.createElement('option');
        opt.value = mode;
        opt.textContent = tr(mode);
        opt.selected = mode === selectedMode;
        select.appendChild(opt);
      });
    }

    function fillIconStyles(presets, selectedMode) {
      const select = document.getElementById('icon_style');
      select.innerHTML = '';
      Object.keys(presets).forEach(mode => {
        const opt = document.createElement('option');
        opt.value = mode;
        opt.textContent = tr(mode);
        opt.selected = mode === selectedMode;
        select.appendChild(opt);
      });
    }

    function renderTemplateExamples(examples) {
      const wrap = document.getElementById('template_examples');
      wrap.innerHTML = examples.map(example => `<code>${example}</code>`).join('');
    }

    function renderExchangeIcons(exchanges, values) {
      const wrap = document.getElementById('exchange_icons');
      wrap.innerHTML = '';
      const style = document.getElementById('icon_style')?.value || current?.config?.ui?.icon_style || 'official';
      const shortNames = currentExchangeShortNames();
      Object.entries(exchanges || {}).forEach(([key, label]) => {
        const row = document.createElement('label');
        row.className = 'inline';
        if (style === 'official') {
          const shortLabel = shortNames[key] || key.toUpperCase();
          row.innerHTML = `${label} ${buildOfficialIcon(key, shortLabel, label)}`;
        } else {
          row.innerHTML = `${label} <input type="text" data-exchange-icon="${key}" value="${(values && values[key]) || ''}" style="width: 96px;">`;
        }
        wrap.appendChild(row);
      });
    }

    function renderTemplateVariables(variables) {
      const wrap = document.getElementById('template_variables');
      wrap.innerHTML = `<table><thead><tr><th>变量</th><th>示例</th><th>说明</th></tr></thead><tbody>${(variables || []).map(item => `<tr><td><code>{${item.name}}</code></td><td>${item.example || ''}</td><td>${item.description || ''}</td></tr>`).join('')}</tbody></table>`;
    }

    function renderStyleOptions() {
      const wrap = document.getElementById('style_options');
      const formatRows = Object.entries(current.formatPresets || {}).map(([key, value]) => `<tr><td><strong>${key}</strong></td><td>${value.label || key}</td><td><code>${value.title_template || ''}</code><br><code>${value.menu_template || ''}</code></td></tr>`).join('');
      const iconRows = Object.entries(current.iconStyleOptions || {}).map(([key, value]) => `<tr><td><strong>${key}</strong></td><td>${value}</td><td>${key === 'official' ? '优先使用官方 Logo，失败回退' : '文本/emoji/空图标样式'}</td></tr>`).join('');
      wrap.innerHTML = `<div><div class="muted">格式模式</div><table><thead><tr><th>Key</th><th>名称</th><th>模板</th></tr></thead><tbody>${formatRows}</tbody></table></div><div style="height:10px"></div><div><div class="muted">图标样式</div><table><thead><tr><th>Key</th><th>名称</th><th>说明</th></tr></thead><tbody>${iconRows}</tbody></table></div>`;
    }

    function syncFormatEditorState() {
      const mode = document.getElementById('format_mode').value;
      const titleInput = document.getElementById('title_template');
      const menuInput = document.getElementById('menu_template');
      const editable = mode === 'custom';
      titleInput.readOnly = !editable;
      menuInput.readOnly = !editable;
      titleInput.style.opacity = editable ? '1' : '0.7';
      menuInput.style.opacity = editable ? '1' : '0.7';
      if (!editable && current?.formatPresets?.[mode]) {
        titleInput.value = current.formatPresets[mode].title_template;
        menuInput.value = current.formatPresets[mode].menu_template;
      }
      titleInput.title = editable ? '' : tr('custom_only');
      menuInput.title = editable ? '' : tr('custom_only');
      renderOneToOnePreview();
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
      return list;
    }

    async function populateSymbolDatalist(exchange) {
      const list = buildSymbolDatalist(exchange);
      list.innerHTML = '';
      const symbols = await ensureSymbols(exchange);
      symbols.forEach(symbol => {
        const opt = document.createElement('option');
        opt.value = symbol;
        list.appendChild(opt);
      });
    }

    function sortedTickerRows() {
      return [...tickerRows].sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
    }

    function normalizeOrders() {
      sortedTickerRows().forEach((row, index) => { row.order = index; });
    }

    function renderTickerRows() {
      const tbody = document.getElementById('ticker_rows');
      tbody.innerHTML = '';
      normalizeOrders();
      sortedTickerRows().forEach((row, index) => {
        const trEl = document.createElement('tr');
        trEl.draggable = true;
        trEl.dataset.key = row.key;
        trEl.innerHTML = `
          <td><span class="drag-handle">☰</span></td>
          <td><input type="checkbox" data-field="enabled" ${row.enabled ? 'checked' : ''}></td>
          <td><input type="checkbox" data-field="visible" ${row.visible ? 'checked' : ''}></td>
          <td><input type="radio" name="pinned_title" data-field="pinned_title" ${row.pinned_title ? 'checked' : ''}></td>
          <td>
            <select data-field="exchange">
              ${Object.entries(current.exchanges).map(([key, label]) => `<option value="${key}" ${row.exchange === key ? 'selected' : ''}>${label}</option>`).join('')}
            </select>
          </td>
          <td><input type="text" data-field="symbol" value="${row.symbol || ''}"></td>
          <td><input type="text" data-field="display_name" value="${row.display_name || ''}"></td>
          <td><button type="button" data-action="remove">${tr('remove_btn')}</button></td>
        `;

        trEl.querySelectorAll('[data-field]').forEach(input => {
          input.addEventListener('change', async (event) => {
            const field = event.target.dataset.field;
            if (field === 'enabled' || field === 'visible' || field === 'pinned_title') {
              row[field] = !!event.target.checked;
            } else {
              row[field] = event.target.value;
            }
            if (field === 'pinned_title' && row.pinned_title) {
              tickerRows.forEach(item => { if (item.key !== row.key) item.pinned_title = false; });
              renderTickerRows();
              return;
            }
            if (field === 'exchange') {
              row.exchange = String(event.target.value || '').toLowerCase();
              await populateSymbolDatalist(row.exchange);
              const symbolInput = trEl.querySelector('input[data-field="symbol"]');
              symbolInput?.setAttribute('list', `symbols-${row.exchange}`);
            }
            renderOneToOnePreview();
          });
        });

        const symbolInput = trEl.querySelector('input[data-field="symbol"]');
        if (symbolInput) {
          symbolInput.setAttribute('list', `symbols-${row.exchange}`);
          populateSymbolDatalist(row.exchange);
        }

        trEl.querySelector('[data-action="remove"]').addEventListener('click', () => {
          tickerRows = tickerRows.filter(item => item.key !== row.key);
          normalizeOrders();
          renderTickerRows();
          renderOneToOnePreview();
        });

        tbody.appendChild(trEl);
      });
    }

    function collectPayload() {
      const exchanges = {};
      document.querySelectorAll('[data-exchange]').forEach(input => {
        exchanges[input.dataset.exchange] = { enabled: !!input.checked };
      });
      const exchangeShortNames = {};
      document.querySelectorAll('[data-exchange-short]').forEach(input => {
        exchangeShortNames[input.dataset.exchangeShort] = String(input.value || '').trim();
      });
      const exchangeIcons = {};
      document.querySelectorAll('[data-exchange-icon]').forEach(input => {
        exchangeIcons[input.dataset.exchangeIcon] = String(input.value || '');
      });
      normalizeOrders();
      const orderedRows = sortedTickerRows();
      const pinnedIndex = orderedRows.findIndex(item => item.pinned_title);
      return {
        ui: {
          language: document.getElementById('language').value,
          max_visible: parseInt(document.getElementById('max_visible').value || '1', 10),
          title_index: pinnedIndex >= 0 ? pinnedIndex : 0,
          format_mode: document.getElementById('format_mode').value,
          title_template: document.getElementById('title_template').value,
          menu_template: document.getElementById('menu_template').value,
          icon_style: document.getElementById('icon_style').value,
          display_fields: String(document.getElementById('display_fields').value || '').split(',').map(x => x.trim()).filter(Boolean),
          show_exchange_links: !!document.getElementById('show_exchange_links').checked,
          performance_mode: document.getElementById('performance_mode').value,
          ui_refresh_interval: parseFloat(document.getElementById('ui_refresh_interval').value || '0.25'),
          exchanges,
          exchange_short_names: exchangeShortNames,
          exchange_icons: exchangeIcons,
          tickers: orderedRows.map(row => ({
            exchange: String(row.exchange || '').toLowerCase(),
            symbol: String(row.symbol || '').trim().toUpperCase(),
            display_name: String(row.display_name || '').trim(),
            enabled: !!row.enabled,
          })),
          ticker_preferences: orderedRows.map((row, index) => ({
            key: `${String(row.exchange || '').toLowerCase()}::${String(row.symbol || '').trim().toUpperCase()}`,
            visible: !!row.visible,
            order: index,
            pinned_title: !!row.pinned_title,
          })),
        }
      };
    }

    function applyIconPreset(style) {
      const preset = current.iconPresets?.[style] || {};
      renderExchangeIcons(current.exchanges, preset);
      renderOneToOnePreview();
    }

    function applyState(state) {
      current = state;
      const ui = state.config.ui;
      tickerRows = [...state.tickers].sort((a, b) => a.order - b.order);
      fillLanguages(state.languages, ui.language || 'zh-CN');
      fillExchangeFlags(state.exchanges, ui.exchanges || {});
      fillExchangeShortNames(state.exchanges, ui.exchange_short_names || state.exchangeShortNames || {});
      fillPerformanceModes(state.performancePresets, ui.performance_mode || 'balanced');
      fillFormatModes(state.formatPresets, ui.format_mode || 'short');
      fillIconStyles(state.iconPresets, ui.icon_style || 'official');
      renderExchangeIcons(state.exchanges, ui.exchange_icons || {});
      renderTemplateExamples(state.templateExamples || []);
      renderTemplateVariables(state.templateVariables || []);
      renderStyleOptions();
      document.getElementById('max_visible').value = ui.max_visible || 1;
      document.getElementById('title_template').value = ui.title_template || '';
      document.getElementById('menu_template').value = ui.menu_template || '';
      document.getElementById('display_fields').value = (ui.display_fields || []).join(', ');
      document.getElementById('show_exchange_links').checked = !!ui.show_exchange_links;
      document.getElementById('ui_refresh_interval').value = ui.ui_refresh_interval || 0.25;
      applyI18n();
      renderOneToOnePreview();
    }

    async function loadState() {
      setStatus(tr('loading'));
      const res = await fetch('/api/config');
      const state = await res.json();
      applyState(state);
      setStatus('');
    }

    async function saveState() {
      try {
        const payload = collectPayload();
        const res = await fetch('/api/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok || !data.ok) {
          throw new Error(data.error || 'Save failed');
        }
        setStatus(tr('saved'));
        await loadState();
      } catch (error) {
        setStatus(String(error), true);
      }
    }

    document.getElementById('language').addEventListener('change', applyI18n);
    document.getElementById('format_mode').addEventListener('change', syncFormatEditorState);
    document.getElementById('icon_style').addEventListener('change', (event) => applyIconPreset(event.target.value));
    document.getElementById('title_template').addEventListener('input', renderOneToOnePreview);
    document.getElementById('menu_template').addEventListener('input', renderOneToOnePreview);
    document.getElementById('max_visible').addEventListener('input', renderOneToOnePreview);
    document.getElementById('save_btn').addEventListener('click', saveState);
    document.getElementById('reload_btn').addEventListener('click', loadState);
    document.getElementById('add_ticker_btn').addEventListener('click', () => {
      const exchange = Object.keys(current.exchanges)[0] || 'kucoin';
      tickerRows.push({
        key: `new-${Date.now()}`,
        exchange,
        symbol: '',
        display_name: '',
        enabled: true,
        visible: true,
        order: tickerRows.length,
        pinned_title: tickerRows.length === 0,
      });
      renderTickerRows();
      renderOneToOnePreview();
    });

    loadState();
  </script>
</body>
</html>
"""
