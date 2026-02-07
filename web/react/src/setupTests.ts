import '@testing-library/jest-dom';

// Mock constants to bypass import.meta in test environment
jest.mock('./config/constants', () => ({
  API_BASE_URL: 'http://127.0.0.1:8000',
  WS_URL: 'ws://127.0.0.1:8000',
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
    constructor() {}
    observe() {}
    unobserve() {}
    disconnect() {}
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
    constructor() {}
    observe() {}
    unobserve() {}
    disconnect() {}
  },
});

// Mock WebSocket
Object.defineProperty(global, 'WebSocket', {
  writable: true,
  value: class WebSocket {
    constructor(_url: string) {
      setTimeout(() => {
        if (this.onopen) this.onopen(new Event('open'));
      }, 0);
    }
    send() {}
    close() {}
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
