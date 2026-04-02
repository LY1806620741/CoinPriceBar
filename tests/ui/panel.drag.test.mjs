import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { JSDOM } from 'jsdom';

const panelHtml = await readFile(new URL('../../coinpricebar/panel.html', import.meta.url), 'utf8');

function buildState() {
  return {
    config: {
      ui: {
        language: 'zh-CN',
        max_visible: 4,
        title_index: 0,
        format_mode: 'custom',
        title_template: '{exchange}:{symbol} {price}',
        menu_template: '{exchange_full} {symbol} {price}',
        icon_style: 'official',
        display_fields: ['exchange', 'symbol', 'price'],
        show_exchange_links: true,
        performance_mode: 'balanced',
        ui_refresh_interval: 0.25,
        exchanges: {
          kucoin: { enabled: true },
          binance: { enabled: true },
        },
        exchange_short_names: {
          kucoin: 'KC',
          binance: 'BN',
        },
        exchange_icons: {
          kucoin: '',
          binance: '',
        },
      },
    },
    tickers: [
      { key: 'kucoin::BTC-USDT', exchange: 'kucoin', symbol: 'BTC-USDT', display_name: 'BTC', enabled: true, visible: true, order: 0, pinned_title: true },
      { key: 'binance::ETH-USDT', exchange: 'binance', symbol: 'ETH-USDT', display_name: 'ETH', enabled: true, visible: true, order: 1, pinned_title: false },
      { key: 'kucoin::KCS-USDT', exchange: 'kucoin', symbol: 'KCS-USDT', display_name: 'KCS', enabled: true, visible: true, order: 2, pinned_title: false },
    ],
    configPath: '/tmp/config.json',
    performancePresets: { stable: 0.5, balanced: 0.25, realtime: 0.1, custom: 0.25 },
    formatPresets: {
      short: { label: 'Short', title_template: '{exchange}:{symbol} {price}', menu_template: '{exchange}:{symbol} {price}' },
      long: { label: 'Long', title_template: '{exchange_full}:{symbol} {price}', menu_template: '{exchange_full}:{symbol} {price} {status}' },
      custom: { label: 'Custom', title_template: '{exchange}:{symbol} {price}', menu_template: '{exchange_full}:{symbol} {price}' },
    },
    templateExamples: [],
    templateVariableGroups: [],
    templateVariables: [],
    iconStyleOptions: { official: 'Official icons', text: 'Text icons' },
    iconPresets: {
      official: { kucoin: '', binance: '' },
      text: { kucoin: '[K]', binance: '[B]' },
    },
    officialExchangeIconUrls: { kucoin: '', binance: '' },
    languages: ['zh-CN', 'en-US'],
    exchanges: { kucoin: 'KuCoin', binance: 'Binance' },
    exchangeShortNames: { kucoin: 'KC', binance: 'BN' },
  };
}

async function bootPanel() {
  const state = buildState();
  let savedPayload = null;
  const sortableInstances = [];
  const dom = new JSDOM(panelHtml, {
    runScripts: 'dangerously',
    url: 'http://127.0.0.1:17321/',
    pretendToBeVisual: true,
    beforeParse(window) {
      window.Sortable = class FakeSortable {
        constructor(element, options) {
          this.element = element;
          this.options = options;
          sortableInstances.push(this);
        }

        destroy() {
          this.destroyed = true;
        }
      };
      window.fetch = async (url, options = {}) => {
        const urlText = String(url);
        if (urlText.includes('/api/symbols')) {
          return {
            ok: true,
            async json() {
              return { exchange: 'kucoin', symbols: ['BTC-USDT', 'ETH-USDT', 'KCS-USDT'] };
            },
          };
        }
        if ((options.method || 'GET').toUpperCase() === 'POST') {
          savedPayload = JSON.parse(options.body);
          state.tickers = savedPayload.ui.ticker_preferences.map((pref, index) => {
            const ticker = savedPayload.ui.tickers[index];
            return {
              key: pref.key,
              exchange: ticker.exchange,
              symbol: ticker.symbol,
              display_name: ticker.display_name,
              enabled: ticker.enabled,
              visible: pref.visible,
              order: pref.order,
              pinned_title: pref.pinned_title,
            };
          });
          return {
            ok: true,
            async json() {
              return { ok: true, config: state.config };
            },
          };
        }
        return {
          ok: true,
          async json() {
            return state;
          },
        };
      };
    },
  });

  if (typeof dom.window.applyState !== 'function') {
    throw new Error('panel applyState is not available');
  }
  dom.window.applyState(state);
  const renderedRows = dom.window.document.querySelectorAll('#ticker_rows tr[data-key]').length;
  assert.ok(renderedRows > 0, `expected ticker rows to render, got 0. html=${dom.window.document.getElementById('ticker_rows')?.innerHTML}`);
  assert.ok(sortableInstances.length > 0, 'expected Sortable to be initialized');
  return { dom, state, sortableInstances, getSavedPayload: () => savedPayload };
}

function keysFromDom(document) {
  return Array.from(document.querySelectorAll('#ticker_rows tr[data-key]'), row => String(row.dataset.key));
}

function simulateSortableReorder(sortableInstance, fromIndex, toIndex) {
  const rows = [...sortableInstance.element.querySelectorAll('tr[data-key]')];
  const moved = rows[fromIndex];
  const target = rows[toIndex];
  const insertBeforeNode = fromIndex < toIndex ? target.nextElementSibling : target;
  sortableInstance.element.insertBefore(moved, insertBeforeNode);
  sortableInstance.options.onEnd?.({ oldIndex: fromIndex, newIndex: toIndex });
}

test('panel drag reorder updates DOM order and collectPayload order', async () => {
  const { dom, sortableInstances } = await bootPanel();
  const { document } = dom.window;

  simulateSortableReorder(sortableInstances.at(-1), 0, 1);

  assert.deepEqual(keysFromDom(document), ['binance::ETH-USDT', 'kucoin::BTC-USDT', 'kucoin::KCS-USDT']);

  const payload = dom.window.collectPayload();
  assert.deepEqual(Array.from(payload.ui.tickers, item => `${item.exchange}::${item.symbol}`), ['binance::ETH-USDT', 'kucoin::BTC-USDT', 'kucoin::KCS-USDT']);
});

test('panel saveState posts reordered ticker payload', async () => {
  const { dom, sortableInstances, getSavedPayload } = await bootPanel();

  simulateSortableReorder(sortableInstances.at(-1), 0, 1);

  await dom.window.saveState();
  const savedPayload = getSavedPayload();
  assert.ok(savedPayload, 'expected save payload to be captured');
  assert.deepEqual(Array.from(savedPayload.ui.tickers, item => `${item.exchange}::${item.symbol}`), ['binance::ETH-USDT', 'kucoin::BTC-USDT', 'kucoin::KCS-USDT']);
});

test('panel sortable initialization is handle-only and table-row based', async () => {
  const { sortableInstances } = await bootPanel();
  const sortable = sortableInstances.at(-1);

  assert.equal(sortable.options.handle, '.drag-handle');
  assert.equal(sortable.options.draggable, 'tr[data-key]');
  assert.equal(typeof sortable.options.onEnd, 'function');
});

