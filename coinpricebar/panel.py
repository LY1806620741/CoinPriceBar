import json
import logging
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from .config import AppConfig, DEFAULT_CONFIG_PATH, TickerConfig, get_default_tickers, load_app_config


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
                if self.path in {"/", "/index.html"}:
                    self._send_html(server._build_html())
                    return
                if self.path == "/api/config":
                    self._send_json(server._serialize_state())
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
                    "visible": True if pref is None else pref.visible,
                    "order": index if pref is None else pref.order,
                    "pinned_title": False if pref is None else pref.pinned_title,
                }
            )
        return {
            "config": self._serialize_config(config),
            "tickers": items,
            "configPath": str(DEFAULT_CONFIG_PATH),
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
    .grid { display: grid; grid-template-columns: 180px 1fr; gap: 10px 14px; max-width: 860px; align-items: center; }
    input[type='text'], input[type='number'] { width: 100%; padding: 8px; box-sizing: border-box; }
    table { border-collapse: collapse; width: 100%; margin-top: 18px; }
    th, td { border-bottom: 1px solid #e5e5e5; padding: 8px; text-align: left; }
    .actions { margin-top: 20px; display: flex; gap: 12px; }
    button { padding: 10px 16px; cursor: pointer; }
    .status { margin-top: 12px; color: #0a7; }
    .error { color: #c33; }
  </style>
</head>
<body>
  <h1>CoinPriceBar UI 配置面板</h1>
  <div class=\"hint\">这里编辑的是 UI 展示配置。监控源仍然来自默认的交易对列表。</div>
  <div class=\"grid\">
    <label for=\"max_visible\">显示数量</label><input id=\"max_visible\" type=\"number\" min=\"1\" />
    <label for=\"title_index\">标题索引</label><input id=\"title_index\" type=\"number\" min=\"0\" />
    <label for=\"title_template\">标题模板</label><input id=\"title_template\" type=\"text\" />
    <label for=\"menu_template\">菜单模板</label><input id=\"menu_template\" type=\"text\" />
    <label for=\"display_fields\">降级字段</label><input id=\"display_fields\" type=\"text\" />
    <label for=\"show_exchange_links\">显示交易所链接</label><input id=\"show_exchange_links\" type=\"checkbox\" />
  </div>

  <h2>显示项配置</h2>
  <table>
    <thead>
      <tr><th>显示</th><th>置顶标题</th><th>顺序</th><th>交易所</th><th>交易对</th><th>名称</th></tr>
    </thead>
    <tbody id=\"ticker_rows\"></tbody>
  </table>

  <div class=\"actions\">
    <button id=\"save_btn\">保存并应用</button>
    <button id=\"reload_btn\">重新读取当前配置</button>
  </div>
  <div id=\"status\" class=\"status\"></div>

  <script>
    let current = null;
    async function loadState() {
      const res = await fetch('/api/config');
      current = await res.json();
      const ui = current.config.ui;
      document.getElementById('max_visible').value = ui.max_visible;
      document.getElementById('title_index').value = ui.title_index;
      document.getElementById('title_template').value = ui.title_template;
      document.getElementById('menu_template').value = ui.menu_template;
      document.getElementById('display_fields').value = ui.display_fields.join(',');
      document.getElementById('show_exchange_links').checked = !!ui.show_exchange_links;
      const tbody = document.getElementById('ticker_rows');
      tbody.innerHTML = '';
      current.tickers.sort((a, b) => a.order - b.order).forEach((ticker, index) => {
        const row = document.createElement('tr');
        row.innerHTML = `
          <td><input type=\"checkbox\" data-field=\"visible\" data-key=\"${ticker.key}\" ${ticker.visible ? 'checked' : ''}></td>
          <td><input type=\"radio\" name=\"pinned_title\" data-field=\"pinned_title\" data-key=\"${ticker.key}\" ${ticker.pinned_title ? 'checked' : ''}></td>
          <td><input type=\"number\" min=\"0\" value=\"${ticker.order}\" data-field=\"order\" data-key=\"${ticker.key}\" style=\"width:70px\"></td>
          <td>${ticker.exchange}</td>
          <td>${ticker.symbol}</td>
          <td>${ticker.display_name || ''}</td>`;
        tbody.appendChild(row);
      });
      setStatus(`已读取配置：${current.configPath}`);
    }

    function setStatus(msg, isError = false) {
      const el = document.getElementById('status');
      el.textContent = msg;
      el.className = isError ? 'status error' : 'status';
    }

    function collectPayload() {
      const tickers = [];
      document.querySelectorAll('#ticker_rows input').forEach(input => {
        const key = input.dataset.key;
        let ticker = tickers.find(item => item.key === key);
        if (!ticker) {
          ticker = { key, visible: false, pinned_title: false, order: 0 };
          tickers.push(ticker);
        }
        if (input.dataset.field === 'visible') ticker.visible = input.checked;
        if (input.dataset.field === 'pinned_title') ticker.pinned_title = input.checked;
        if (input.dataset.field === 'order') ticker.order = Number(input.value || 0);
      });
      return {
        ui: {
          max_visible: Number(document.getElementById('max_visible').value || 1),
          title_index: Number(document.getElementById('title_index').value || 0),
          title_template: document.getElementById('title_template').value,
          menu_template: document.getElementById('menu_template').value,
          display_fields: document.getElementById('display_fields').value.split(',').map(v => v.trim()).filter(Boolean),
          show_exchange_links: document.getElementById('show_exchange_links').checked,
          tickers,
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

    document.getElementById('save_btn').addEventListener('click', saveState);
    document.getElementById('reload_btn').addEventListener('click', loadState);
    loadState().catch(err => setStatus(err.message, true));
  </script>
</body>
</html>
"""

