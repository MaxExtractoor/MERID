import '@testing-library/jest-dom';

// Mock constants to bypass import.meta in test environment
jest.mock('./config/constants', () => ({
  API_BASE_URL: 'http://127.0.0.1:8000',
  WS_URL: 'ws://127.0.0.1:8000',
  WS_PORTFOLIO_URL: 'ws://127.0.0.1:8000/ws/risk',
  API_ENDPOINTS: {
    PORTFOLIO_SUMMARY: '/api/v1/portfolio/summary',
    POSITIONS: '/api/v1/positions',
    ORDERS: '/api/v1/orders',
    FILLS: '/api/v1/fills',
    SUBMIT_ORDER: '/api/v1/orders/submit',
    CANCEL_ORDER: '/api/v1/orders/cancel',
    AGENTS: '/api/v1/agents',
    LOGS: '/api/v1/logs',
    RISK_SUMMARY: '/api/v1/risk/summary',
    PREDICTIONS: '/api/v1/predictions',
    RESEARCH: '/api/v1/research',
    KALSHI_MARKETS: '/api/v1/kalshi/markets',
    KALSHI_MARKET_DETAIL: (ticker: string) => `/api/v1/kalshi/markets/${ticker}`,
    KALSHI_CATALOG: '/api/v1/kalshi/catalog',
    KALSHI_CATALOG_REFRESH: '/api/v1/kalshi/catalog/refresh',
    KALSHI_POSITIONS: '/api/v1/kalshi/positions',
    KALSHI_ORDERS: '/api/v1/kalshi/orders',
    KALSHI_FILLS: '/api/v1/kalshi/fills',
    KALSHI_BALANCE: '/api/v1/kalshi/balance',
    KALSHI_PNL: '/api/v1/kalshi/pnl',
    KALSHI_RISK: '/api/v1/kalshi/risk',
    KALSHI_WS: '/api/v1/kalshi/ws',
    KALSHI_HEALTH: '/api/v1/kalshi/health',
    KALSHI_KILL_SWITCH: '/api/v1/kalshi/kill-switch',
    KALSHI_SIZING_METRICS: '/api/v1/kalshi/sizing-metrics',
    KALSHI_PNL_HISTORY: '/api/v1/kalshi/pnl-history',
    KALSHI_LIQUIDITY_ALERTS: '/api/v1/kalshi/liquidity-alerts',
    KALSHI_LIQUIDITY_HEALTH: (marketId: string) => `/api/v1/kalshi/liquidity-health/${marketId}`,
    KALSHI_EDGE: '/api/v1/kalshi/edge',
    KALSHI_RISK_EVENTS: '/api/v1/kalshi/risk/events',
    KALSHI_RISK_DOWNSIZE: '/api/v1/kalshi/risk/downsize',
    KALSHI_FAVORITES: '/api/v1/kalshi/favorites',
    KALSHI_FAVORITES_TOGGLE: '/api/v1/kalshi/favorites/toggle',
    KALSHI_VOLUME_ALERTS: '/api/v1/kalshi/volume-alerts',
    KALSHI_EXPORT: '/api/v1/kalshi/export',
    TRADE_MODE: '/api/v1/trade-mode',
    PAPER_TRADING_SUBMIT: '/api/v1/paper-trading/orders/submit',
  },
  STATUS_TYPES: {
    ONLINE: 'online',
    DEGRADED: 'degraded',
    OFFLINE: 'offline',
    GOOD: 'good',
    WARNING: 'warning',
    BAD: 'bad',
  },
  LOG_LEVELS: {
    ERROR: 'error',
    WARN: 'warn',
    INFO: 'info',
    DEBUG: 'debug',
  },
  CHART_COLORS: {
    PRIMARY: '#22c55e',
    DANGER: '#ef4444',
    WARNING: '#f59e0b',
    INFO: '#3b82f6',
    NEUTRAL: '#6b7280',
  },
  DEFAULTS: {
    SYMBOLS: ['BTC-USD', 'ETH-USD', 'SOL-USD', 'MATIC-USD'],
    VENUES: ['Coinbase', 'Kraken', 'Binance', 'Gemini'],
    ORDER_TYPES: ['MARKET', 'LIMIT', 'STOP', 'BRACKET'],
    SIDES: ['BUY', 'SELL'],
    POLLING_INTERVALS: {
      PORTFOLIO: 30000,
      POSITIONS: 5000,
      ORDERS: 3000,
      FILLS: 2000,
      STANDARD: 10000,
      SLOW: 30000,
      FAST_REFRESH: 15000,
      MEDIUM: 15000,
      BACKGROUND: 60000,
      RISK: 30000,
      RISK_ALERTS: 30000,
      AGENTS: 15000,
      SYSTEM_HEALTH: 60000,
      API_STATUS: 60000,
      LOGS: 10000,
      LOG_STATS: 60000,
      BACKTESTS: 30000,
      STALENESS: 15000,
      INFREQUENT: 120000,
      RARE: 300000,
    },
  },
  WS_EVENTS: {
    CONNECT: 'connect',
    DISCONNECT: 'disconnect',
    PRICE_UPDATE: 'price_update',
    ORDER_UPDATE: 'order_update',
    AGENT_UPDATE: 'agent_update',
  },
}));

// Mock IntersectionObserver
Object.defineProperty(global, 'IntersectionObserver', {
  writable: true,
  value: class IntersectionObserver {
    observe() { return undefined; }
    unobserve() { return undefined; }
    disconnect() { return undefined; }
    root = null;
    rootMargin = '';
    thresholds = [];
    takeRecords() { return []; }
  },
});

// Mock ResizeObserver
Object.defineProperty(global, 'ResizeObserver', {
  writable: true,
  value: class ResizeObserver {
    observe() { return undefined; }
    unobserve() { return undefined; }
    disconnect() { return undefined; }
  },
});

// Mock WebSocket
Object.defineProperty(global, 'WebSocket', {
  writable: true,
  value: class WebSocket {
    constructor(_url: string) {
      this.url = _url;
      setTimeout(() => {
        if (this.onopen) this.onopen(new Event('open'));
      }, 0);
    }
    send(data: string) {
      this.bufferedAmount = typeof data === 'string' ? data.length : 0;
    }
    close() {
      this.readyState = this.CLOSED;
      if (this.onclose) {
        this.onclose(new Event('close') as CloseEvent);
      }
    }
    onopen: ((event: Event) => void) | null = null;
    onclose: ((event: CloseEvent) => void) | null = null;
    onmessage: ((event: MessageEvent) => void) | null = null;
    onerror: ((event: Event) => void) | null = null;
    readonly CONNECTING = 0;
    readonly OPEN = 1;
    readonly CLOSING = 2;
    readonly CLOSED = 3;
    readyState = this.OPEN;
    url = '';
    protocol = '';
    binaryType = 'blob';
    bufferedAmount = 0;
    extensions = '';
  },
});

// Mock localStorage
const localStorageMock = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
  clear: jest.fn(),
  length: 0,
  key: jest.fn(),
};
Object.defineProperty(global, 'localStorage', {
  writable: true,
  value: localStorageMock,
});

// Mock fetch
Object.defineProperty(global, 'fetch', {
  writable: true,
  value: jest.fn(),
});
