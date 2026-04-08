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
        title_index: 0,
        format_mode: 'custom',
        title_template: '{exchange}:{symbol} {price}',
        title_template_multi: '{symbol} {price}',
        title_separator: ' · ',
        menu_template: '{exchange_full} {symbol} {price}',
        icon_style: 'official',
        display_fields: ['exchange', 'symbol', 'price'],
        show_exchange_links: true,
        performance_mode: 'balanced',
        ui_refresh_interval: 0.25,
        exchanges: {
          kucoin: { enabled: true },
          binance: { enabled: true },
          web3: { enabled: true },
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
      short: { label: 'Short', title_template: '{exchange}:{symbol} {price}', title_template_multi: '{symbol} {price}', menu_template: '{exchange}:{symbol} {price}' },
      long: { label: 'Long', title_template: '{exchange_full}:{symbol} {price}', title_template_multi: '{exchange} {symbol} {price}', menu_template: '{exchange_full}:{symbol} {price} {status}' },
      custom: { label: 'Custom', title_template: '{exchange}:{symbol} {price}', title_template_multi: '{symbol} {price}', menu_template: '{exchange_full}:{symbol} {price}' },
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
    exchanges: { kucoin: 'KuCoin', binance: 'Binance', web3: 'Web3' },
    exchangeShortNames: { kucoin: 'KC', binance: 'BN' },
    sourceSchemas: {
      kucoin: { symbol_placeholder: 'BTC-USDT', symbol_help: '', examples: ['BTC-USDT'] },
      binance: { symbol_placeholder: 'ETH-USDT', symbol_help: '', examples: ['ETH-USDT'] },
      web3: {
        symbol_placeholder: 'DEX:UNISWAP:ETHEREUM:0xTOKEN:WETH',
        symbol_help: '支持 CoinGecko / PAIR / DEX 三种格式，DEX 示例：DEX:UNISWAP:ETHEREUM:0xTOKEN:WETH',
        examples: ['ETH-USD', 'PAIR:ETHEREUM:0xPAIR', 'DEX:UNISWAP:ETHEREUM:0xTOKEN:WETH'],
        editor: {
          modes: [
            { value: 'token', label: 'CoinGecko Token' },
            { value: 'pair', label: 'Exact Pair' },
            { value: 'dex', label: 'DEX Market' },
          ],
          chains: ['ethereum', 'base'],
          dexes: ['auto', 'uniswap'],
          quote_examples: ['WETH', 'USDC', 'USDT'],
        },
      },
    },
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
        if (urlText.includes('/api/web3/candidates')) {
          return {
            ok: true,
            async json() {
              return {
                ok: true,
                candidates: [
                  {
                    chain: 'ethereum',
                    dex: 'uniswap',
                    base_symbol: 'KCS',
                    quote_symbol: 'USDC',
                    liquidity_usd: 250000,
                    price_usd: 8.47,
                    trade_url: 'https://app.uniswap.org/explore/tokens/ethereum/0xf34960d9d60be18cc1d5afc1a6f012a723a28811?inputCurrency=0xf34960d9d60be18cc1d5afc1a6f012a723a28811&outputCurrency=0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                    suggested_pair_symbol: 'PAIR:ETHEREUM:0X658069E3647FAAC148845A68C36831ECDE99134D',
                    suggested_dex_symbol: 'DEX:UNISWAP:ETHEREUM:0XF34960D9D60BE18CC1D5AFC1A6F012A723A28811:USDC',
                  },
                ],
              };
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

test('panel title preview and payload support multiple pinned title rows', async () => {
  const { dom } = await bootPanel();
  const secondPinned = dom.window.document.querySelectorAll('input[data-field="pinned_title"]')[1];
  assert.ok(secondPinned, 'expected second pinned-title checkbox to exist');

  secondPinned.checked = true;
  secondPinned.dispatchEvent(new dom.window.Event('change', { bubbles: true }));

  const titlePreview = dom.window.document.getElementById('title_preview')?.textContent || '';
  assert.match(titlePreview, /BTC/);
  assert.match(titlePreview, /ETH/);
  assert.match(titlePreview, /·/);
  assert.doesNotMatch(titlePreview, /KC:/);

  const payload = dom.window.collectPayload();
  assert.equal(payload.ui.title_template_multi, '{symbol} {price}');
  assert.equal(payload.ui.title_separator, ' · ');
  assert.equal(payload.ui.ticker_preferences.filter(item => item.pinned_title).length, 2);
});

test('panel sortable initialization is handle-only and table-row based', async () => {
  const { sortableInstances } = await bootPanel();
  const sortable = sortableInstances.at(-1);

  assert.equal(sortable.options.handle, '.drag-handle');
  assert.equal(sortable.options.draggable, 'tr[data-key]');
  assert.equal(typeof sortable.options.onEnd, 'function');
});

test('panel updates symbol placeholder and help for web3 exchange rows', async () => {
  const { dom } = await bootPanel();
  const row = dom.window.document.querySelector('#ticker_rows tr[data-key]');
  assert.ok(row, 'expected at least one ticker row');

  const exchangeSelect = row.querySelector('select[data-field="exchange"]');
  exchangeSelect.value = 'web3';
  exchangeSelect.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  await new Promise(resolve => setTimeout(resolve, 0));

  const symbolInput = row.querySelector('input[data-field="symbol"]');
  const help = row.querySelector('[data-symbol-help]');
  assert.equal(symbolInput.placeholder, 'DEX:UNISWAP:ETHEREUM:0xTOKEN:WETH');
  assert.match(help.textContent || '', /DEX:UNISWAP/);
});

test('panel web3 builder composes dex symbol into the shared symbol input', async () => {
  const { dom } = await bootPanel();
  const row = dom.window.document.querySelector('#ticker_rows tr[data-key]');
  assert.ok(row, 'expected at least one ticker row');

  const exchangeSelect = row.querySelector('select[data-field="exchange"]');
  exchangeSelect.value = 'web3';
  exchangeSelect.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  await new Promise(resolve => setTimeout(resolve, 0));

  row.querySelector('[data-web3-field="mode"]').value = 'dex';
  row.querySelector('[data-web3-field="mode"]').dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  row.querySelector('[data-web3-field="dex_market"]').value = 'uniswap';
  row.querySelector('[data-web3-field="dex_market"]').dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  row.querySelector('[data-web3-field="dex_chain"]').value = 'ethereum';
  row.querySelector('[data-web3-field="dex_chain"]').dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  row.querySelector('[data-web3-field="dex_token_address"]').value = '0xf34960d9d60be18cc1d5afc1a6f012a723a28811';
  row.querySelector('[data-web3-field="dex_token_address"]').dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  row.querySelector('[data-web3-field="dex_quote"]').value = 'USDC';
  row.querySelector('[data-web3-field="dex_quote"]').dispatchEvent(new dom.window.Event('input', { bubbles: true }));

  const symbolInput = row.querySelector('input[data-field="symbol"]');
  assert.equal(symbolInput.value, 'DEX:UNISWAP:ETHEREUM:0XF34960D9D60BE18CC1D5AFC1A6F012A723A28811:USDC');
});

test('panel web3 candidate pools expose trade links and can write back pair symbols', async () => {
  const { dom } = await bootPanel();
  const row = dom.window.document.querySelector('#ticker_rows tr[data-key]');
  assert.ok(row, 'expected at least one ticker row');

  const exchangeSelect = row.querySelector('select[data-field="exchange"]');
  exchangeSelect.value = 'web3';
  exchangeSelect.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  await new Promise(resolve => setTimeout(resolve, 0));

  row.querySelector('[data-web3-field="mode"]').value = 'dex';
  row.querySelector('[data-web3-field="mode"]').dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  row.querySelector('[data-web3-field="dex_token_address"]').value = '0xf34960d9d60be18cc1d5afc1a6f012a723a28811';
  row.querySelector('[data-web3-field="dex_token_address"]').dispatchEvent(new dom.window.Event('input', { bubbles: true }));

  row.querySelector('[data-web3-fetch-candidates]').dispatchEvent(new dom.window.Event('click', { bubbles: true }));
  await new Promise(resolve => setTimeout(resolve, 0));

  const tradeLink = row.querySelector('[data-web3-trade-link="0"]');
  assert.ok(tradeLink, 'expected candidate trade link to render');
  assert.equal(tradeLink.getAttribute('href'), 'https://app.uniswap.org/explore/tokens/ethereum/0xf34960d9d60be18cc1d5afc1a6f012a723a28811?inputCurrency=0xf34960d9d60be18cc1d5afc1a6f012a723a28811&outputCurrency=0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48');
  assert.equal(tradeLink.getAttribute('target'), '_blank');

  row.querySelector('[data-web3-use-pair="0"]').dispatchEvent(new dom.window.Event('click', { bubbles: true }));
  const symbolInput = row.querySelector('input[data-field="symbol"]');
  assert.equal(symbolInput.value, 'PAIR:ETHEREUM:0X658069E3647FAAC148845A68C36831ECDE99134D');
});

