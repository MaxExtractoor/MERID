import '@testing-library/jest-dom';

// Mock constants to bypass import.meta in test environment
jest.mock('./config/constants', () => ({
  API_BASE_URL: 'http://127.0.0.1:8000',
  WS_URL: 'ws://127.0.0.1:8000/ws/trades',
  WS_PORTFOLIO_URL: 'ws://127.0.0.1:8000/ws/portfolio',
  AUTH_TOKEN_KEY: 'merid-access',
  API_ENDPOINTS: {
    SYSTEM_HEALTH: '/api/v1/system/health',
    SYSTEM_EXECUTION_GATE: '/api/v1/system/execution-gate',
    SYSTEM_STOP: '/api/v1/monitoring/system/stop',
    RISK_PROTECTIONS: '/api/risk/protections',
    RISK_SUMMARY: '/api/v1/risk/summary',
    RISK_HALT_STATUS: '/api/v1/risk/halt-status',
    RISK_STALENESS: '/api/v1/risk/staleness',
    NOTIFICATIONS: '/api/v1/notifications',
    LOGS: '/api/v1/logs',
    LOGS_STATS: '/api/v1/logs/stats',
    OPERATOR_SUMMARY: '/api/v1/operator/summary',
    OPERATOR_RISK_STATE: '/api/v1/operator/risk-state',
    OPERATOR_AGENT_ACTIVITY: '/api/v1/operator/agent-activity',
    DATA_FRESHNESS: '/api/v1/data/freshness',
    SIGNALS_ALERTS_HISTORY: '/api/v1/signals/alerts/history',
    EXPLAINABILITY_DECISIONS: '/api/v1/explainability/decisions',
    PIPELINE_VENUES: '/api/v1/pipeline/venues',
    PAPER_LADDER_STATUS: '/api/v1/paper-ladder/status',
    KALSHI_GRID_STATUS: '/api/v1/kalshi-grid/status',
    KALSHI_GRID_MODE: '/api/v1/kalshi-grid/mode',
    KALSHI_GRID_FILLS: '/api/v1/kalshi-grid/fills',
    KALSHI_GRID_HEALTH: '/api/v1/kalshi-grid/health',
    KALSHI_GRID_SENTIMENT: '/api/v1/kalshi-grid/sentiment',
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
    KALSHI_CATEGORIES: '/api/v1/kalshi/categories',
    KALSHI_ORDER_CANCEL: (orderId: string) => `/api/v1/kalshi/orders/${orderId}`,
    KALSHI_ORDERS_BATCH_CANCEL: '/api/v1/kalshi/orders',
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
  DEFAULTS: {
    PAGE_SIZE: 25,
    POLLING_INTERVALS: {
      PORTFOLIO: 10000,
      POSITIONS: 15000,
      ORDERS: 15000,
      AGENTS: 15000,
      RISK: 30000,
      RISK_ALERTS: 30000,
      SYSTEM_HEALTH: 60000,
      API_STATUS: 60000,
      LOGS: 10000,
      LOG_STATS: 60000,
      BACKTESTS: 30000,
      STALENESS: 15000,
      SIMULATION: 30000,
      FAST_REFRESH: 15000,
      STANDARD: 10000,
      MEDIUM: 15000,
      SLOW: 30000,
      EXPLAINABILITY: 30000,
      BACKGROUND: 60000,
      INFREQUENT: 120000,
      RARE: 300000,
      SENTIMENT: 30000,
    },
    TIMEOUTS: {
      DEBOUNCE: 50,
      UI_FEEDBACK: 500,
      TOAST: 3000,
      STATUS_RESET: 5000,
    },
    KALSHI_SIDES: ['yes', 'no'],
    KALSHI_ACTIONS: ['buy', 'sell'],
    KALSHI_ORDER_TYPES: ['limit', 'market'],
  },
  WS_EVENTS: {
    PRICE_TICK: 'price_tick',
    ORDER_UPDATE: 'order_update',
    FILL_UPDATE: 'fill_update',
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
