import '@testing-library/jest-dom';

// Mock constants to bypass import.meta in test environment.
// Mirrors the pruned src/config/constants.ts — keep in sync with its exports.
jest.mock('./config/constants', () => ({
  API_BASE_URL: 'http://127.0.0.1:8011',
  AUTH_TOKEN_KEY: 'merid-access',
  CHART_COLORS: {
    GREEN: '#22c55e',
    RED: '#ef4444',
    YELLOW: '#eab308',
    BLUE: '#3b82f6',
    PURPLE: '#a855f7',
    ORANGE: '#f97316',
    WHITE: '#ffffff',
    GRAY: '#6b7280',
  },
  API_ENDPOINTS: {
    SYSTEM_HEALTH: '/api/v1/health',
    KALSHI_MARKETS: '/api/v1/kalshi/markets',
    KALSHI_POSITIONS: '/api/v1/kalshi/positions',
    KALSHI_ORDERS: '/api/v1/kalshi/orders',
    KALSHI_FILLS: '/api/v1/kalshi/fills',
    KALSHI_BALANCE: '/api/v1/kalshi/balance',
    KALSHI_PNL: '/api/v1/kalshi/pnl',
  },
  DEFAULTS: {
    POLLING_INTERVALS: {
      FAST: 5000,
      FAST_REFRESH: 5000,
      STANDARD: 10000,
      SLOW: 30000,
      BACKGROUND: 60000,
    },
    TIMEOUTS: {
      DEBOUNCE: 50,
      TOAST: 3000,
      STATUS_RESET: 5000,
    },
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
