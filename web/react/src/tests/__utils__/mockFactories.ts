/**
 * Centralized test mock factories to ensure consistency across tests.
 * Import these factories instead of redefining mocks in each test file.
 */

/**
 * Get standard mock constants for jest.mock() calls
 */
export function getMockConstants() {
  return {
    API_BASE_URL: 'http://localhost:8000',
    AUTH_TOKEN_KEY: 'merid-access',
    API_ENDPOINTS: {
      // System
      SYSTEM_HEALTH: '/api/v1/system/health',
      SYSTEM_EXECUTION_GATE: '/api/v1/system/execution-gate',
      LOOP_LIVE_READINESS: '/api/v1/loop/live-readiness',
      
      // Risk
      RISK_PROTECTIONS: '/api/v1/operator/risk-state',
      RISK_CIRCUIT_BREAKER_RESET: '/api/v1/operator/reset-kill-switch',
      
      // Kalshi
      KALSHI_POSITIONS: '/api/v1/kalshi/positions',
      KALSHI_ORDERS: '/api/v1/kalshi/orders',
      KALSHI_GRID_MODE: '/api/v1/kalshi-grid/mode',
      KALSHI_GRID_STATUS: '/api/v1/kalshi-grid/status',
      KALSHI_HEALTH: '/api/v1/kalshi/health',
      KALSHI_BALANCE: '/api/v1/kalshi/balance',
      KALSHI_RISK_DOWNSIZE: '/api/v1/kalshi/risk/downsize',
      
      // Operator
      OPERATOR_EMERGENCY_STOP: '/api/v1/operator/emergency-stop',
      OPERATOR_RESET_KILL_SWITCH: '/api/v1/operator/reset-kill-switch',
      
      // Markets
      KALSHI_MARKETS: '/api/v1/kalshi/markets',
      KALSHI_CATALOG: '/api/v1/kalshi/catalog',
    },
    DEFAULTS: {
      POLLING_INTERVALS: {
        FAST_REFRESH: 5000,
        STANDARD: 10000,
        MEDIUM: 20000,
        SLOW: 30000,
      },
      TIMEOUTS: {
        FETCH: 10000,
        TOAST: 3000,
      },
    },
    RETRY_DEFAULTS: {
      COUNT: 3,
      DELAY_MS: 1000,
      MAX_RECONNECT_ATTEMPTS: 10,
      MAX_RECONNECT_DELAY_MS: 30000,
      FETCH_TIMEOUT_MS: 10000,
    },
    CACHE_TTL: {
      DEFAULT: 5 * 60 * 1000,
      RECONCILIATION: 2 * 60 * 1000,
      DECISIONS: 10 * 60 * 1000,
      AUDIT: 30 * 60 * 1000,
      ANALYTICS: 5 * 60 * 1000,
    },
    HEALTH_STATUS: {
      HEALTHY: 'healthy',
      DEGRADED: 'degraded',
      UNHEALTHY: 'unhealthy',
    },
    AGENT_STATUS: {
      RUNNING: 'running',
      PAUSED: 'paused',
      STOPPED: 'stopped',
    },
  };
}

/**
 * Factory for creating mock API responses
 */
export function createMockApiResponse<T>(data: T, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 200 && status < 300 ? 'OK' : 'Error',
    json: async () => data,
    text: async () => JSON.stringify(data),
  };
}

/**
 * Factory for creating mock system health data
 */
export function createMockSystemHealth(overrides = {}) {
  return {
    status: 'healthy',
    timestamp: Date.now(),
    environment: 'test',
    incident_flag: false,
    services: {
      kalshi: { status: 'connected', last_check: Date.now() },
      database: { status: 'connected', last_check: Date.now() },
    },
    ...overrides,
  };
}

/**
 * Factory for creating mock PnL data
 */
export function createMockPnLSummary(overrides = {}) {
  return {
    today_pnl: 150.5,
    today_pnl_pct: 1.5,
    mtm_pnl: 200.0,
    max_drawdown: -50.0,
    max_drawdown_pct: -0.5,
    limit_daily_loss: 10000,
    limit_utilization_pct: 15,
    ...overrides,
  };
}

/**
 * Factory for creating mock risk protections data
 */
export function createMockRiskProtections(overrides = {}) {
  return {
    timestamp: new Date().toISOString(),
    circuit_breaker: {
      state: 'CLOSED',
      state_color: 'green',
      error_count: 0,
      window_seconds: 60,
      threshold: 5,
      last_error_at: null,
      opened_at: null,
      cooldown_seconds: 300,
      half_open_successes: 0,
    },
    lockdown: {
      trading_suite_enabled: true,
      global_mode: 'paper',
      spectator_mode: false,
      lockdown_reason: null,
    },
    risk_limits: {
      max_daily_loss_usd: 10000,
      current_daily_pnl: 150.5,
      daily_loss_utilization_pct: 15,
      max_per_symbol_exposure_usd: 5000,
      max_open_orders: 100,
      current_open_orders: 5,
    },
    recent_events: [],
    ...overrides,
  };
}

/**
 * Factory for creating mock Kalshi position data
 */
export function createMockKalshiPosition(overrides = {}) {
  return {
    ticker: 'BTC-2024-01-01',
    side: 'yes',
    count: 100,
    avg_price_cents: 55,
    ...overrides,
  };
}

/**
 * Factory for creating mock Kalshi order data
 */
export function createMockKalshiOrder(overrides = {}) {
  return {
    order_id: 'order-123',
    ticker: 'BTC-2024-01-01',
    side: 'yes',
    action: 'buy',
    status: 'open',
    count: 50,
    price_cents: 55,
    ...overrides,
  };
}

/**
 * Setup function for standard mocks in test files
 */
export function setupStandardMocks() {
  // Mock localStorage
  const localStorageMock = {
    getItem: jest.fn(),
    setItem: jest.fn(),
    removeItem: jest.fn(),
    clear: jest.fn(),
  };
  Object.defineProperty(window, 'localStorage', {
    value: localStorageMock,
    writable: true,
  });

  // Mock fetch
  global.fetch = jest.fn();

  // Mock console methods to reduce noise
  jest.spyOn(console, 'error').mockImplementation(() => {});
  jest.spyOn(console, 'warn').mockImplementation(() => {});

  return {
    localStorage: localStorageMock,
  };
}

/**
 * Cleanup function for standard mocks
 */
export function cleanupStandardMocks() {
  jest.restoreAllMocks();
}
