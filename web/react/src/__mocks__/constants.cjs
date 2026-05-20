/**
 * Jest mock for config/constants
 */
'use strict';

function getChartColors(isDark) {
  return {
    AXIS_TICK: '#64748b',
    GRID_STROKE: isDark ? '#334155' : '#e2e8f0',
    TOOLTIP_BG: isDark ? '#0f172a' : '#ffffff',
    TOOLTIP_BORDER: isDark ? '#334155' : '#e2e8f0',
    TOOLTIP_LABEL: isDark ? '#e2e8f0' : '#1e293b',
    BAR_BASE: isDark ? '#1e293b' : '#f1f5f9',
  };
}

var CHART_COLORS = {
  GREEN: '#22c55e',
  RED: '#ef4444',
  AMBER: '#f59e0b',
  INDIGO: '#6366f1',
  SLATE_600: '#475569',
};

var API_BASE_URL = 'http://127.0.0.1:8011';
var WS_URL = 'ws://127.0.0.1:8011/ws/trades';
var WS_PORTFOLIO_URL = 'ws://127.0.0.1:8011/ws/risk';
var AUTH_TOKEN_KEY = 'merid-access';

var API_ENDPOINTS = {
  SYSTEM_HEALTH: '/api/v1/system/health',
  SYSTEM_EXECUTION_GATE: '/api/v1/system/execution-gate',
  SYSTEM_STOP: '/api/v1/monitoring/system/stop',
  CONFIG_RELOAD: '/api/v1/system/config-reload',
  RISK_PROTECTIONS: '/api/risk/protections',
  RISK_SUMMARY: '/api/v1/risk/summary',
  RISK_HALT_STATUS: '/api/v1/risk/halt-status',
  RISK_STALENESS: '/api/v1/risk/staleness',
  OPERATOR_KILL_SWITCH_STATUS: '/api/v1/operator/kill-switch-status',
  OPERATOR_EMERGENCY_STOP: '/api/v1/operator/emergency-stop',
  OPERATOR_RESET_KILL_SWITCH: '/api/v1/operator/reset-kill-switch',
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
  KALSHI_GRID_PORTFOLIO: '/api/v1/kalshi-grid/portfolio',
  KALSHI_GRID_SESSION: '/api/v1/kalshi-grid/session',
  KALSHI_GRID_PAUSE: '/api/v1/kalshi-grid/pause',
  KALSHI_GRID_HEALTH: '/api/v1/kalshi-grid/health',
  KALSHI_GRID_SENTIMENT: '/api/v1/kalshi-grid/sentiment',
  KALSHI_MARKETS: '/api/v1/kalshi/markets',
  KALSHI_MARKET_DETAIL: function(ticker) { return `/api/v1/kalshi/markets/${ticker}`; },
  KALSHI_CATALOG: '/api/v1/kalshi/catalog',
  KALSHI_CATALOG_REFRESH: '/api/v1/kalshi/catalog/refresh',
  KALSHI_CONSENSUS_SIGNALS: '/api/v1/kalshi/consensus-signals',
  KALSHI_PUBLISH_PIPELINE: '/api/v1/kalshi/publish-pipeline',
  KALSHI_PUBLISH_PIPELINE_TRIGGER: '/api/v1/kalshi/publish-pipeline/trigger',
  KALSHI_FAVORITES: '/api/v1/kalshi/favorites',
  KALSHI_FAVORITES_TOGGLE: '/api/v1/kalshi/favorites/toggle',
  KALSHI_CATEGORIES: '/api/v1/kalshi/categories',
  KALSHI_KILL_SWITCH: '/api/v1/kalshi/kill-switch',
  KALSHI_CIRCUIT_BREAKER: '/api/v1/resilience/breakers',
  KALSHI_LATENCY: '/api/metrics/latency',
  KALSHI_ORDER_ERRORS: '/api/v1/kalshi/order-errors',
  KALSHI_SIZING_METRICS: '/api/v1/kalshi/sizing-metrics',
  KALSHI_PNL_HISTORY: '/api/v1/kalshi/pnl-history',
  KALSHI_LIQUIDITY_ALERTS: '/api/v1/kalshi/liquidity-alerts',
  KALSHI_LIQUIDITY_HEALTH: function(marketId) { return `/api/v1/kalshi/liquidity-health/${marketId}`; },
  KALSHI_ORDERBOOK: function(ticker) { return `/api/v1/kalshi/markets/${ticker}/orderbook`; },
  KALSHI_ORDERBOOK_STREAM: function(ticker) { return `/api/v1/kalshi/markets/${ticker}/orderbook/stream`; },
  KALSHI_EDGE: '/api/v1/kalshi/edge',
  KALSHI_RISK_EVENTS: '/api/v1/kalshi/risk/events',
  KALSHI_RISK_DOWNSIZE: '/api/v1/kalshi/risk/downsize',
  RECONCILIATION_STATUS: '/api/v1/reconciliation/status',
  RISK_CIRCUIT_BREAKER_RESET: '/api/v1/operator/reset-kill-switch',
  RISK_KILL_SWITCH: function(action) { return action === 'enable' ? '/api/v1/operator/guard/kill' : '/api/v1/operator/guard/unkill'; },
  GUARD_KILL: '/api/v1/operator/guard/kill',
  GUARD_UNKILL: '/api/v1/operator/guard/unkill',
  DEV_SWARM_PAUSE: '/api/dev-swarm/pause',
  DEV_SWARM_RESUME: '/api/dev-swarm/resume',
  TRADING_MODE_SET: '/api/v1/operator/trading-mode',
  KALSHI_SENTIMENT_LANE_SNAPSHOT: '/api/v1/kalshi/sentiment/lane-snapshot',
  KALSHI_SENTIMENT_BUNDLE: function(asset) { return `/api/v1/kalshi/sentiment/bundle/${asset}`; },
  KALSHI_FAVORITES: '/api/v1/kalshi/favorites',
  KALSHI_FAVORITES_TOGGLE: '/api/v1/kalshi/favorites/toggle',
  KALSHI_VOLUME_ALERTS: '/api/v1/kalshi/volume-alerts',
  KALSHI_EXPORT: '/api/v1/kalshi/export',
  KALSHI_CATEGORIES: '/api/v1/kalshi/categories',
  KALSHI_ORDER_CANCEL: function(orderId) { return `/api/v1/kalshi/orders/${orderId}`; },
  KALSHI_ORDERS_BATCH_CANCEL: '/api/v1/kalshi/orders',
  KALSHI_ORDER_GROUPS: '/api/v1/kalshi/order-groups',
  KALSHI_ORDER_GROUP_DETAIL: function(groupId) { return `/api/v1/kalshi/order-groups/${groupId}`; },
  KALSHI_ORDER_GROUP_CREATE: '/api/v1/kalshi/order-groups',
  KALSHI_ORDER_GROUP_LIMIT: function(groupId) { return `/api/v1/kalshi/order-groups/${groupId}/limit`; },
  KALSHI_ORDER_GROUP_TRIGGER: function(groupId) { return `/api/v1/kalshi/order-groups/${groupId}/trigger`; },
  KALSHI_ORDER_GROUP_RESET: function(groupId) { return `/api/v1/kalshi/order-groups/${groupId}/reset`; },
  KALSHI_ORDER_GROUP_DELETE: function(groupId) { return `/api/v1/kalshi/order-groups/${groupId}`; },
  KALSHI_ORDER_GROUP_DASHBOARD: '/api/v1/kalshi/order-groups/dashboard',
  KALSHI_ORDER_GROUP_STREAM: '/api/v1/kalshi/order-groups/stream',
  KALSHI_BATCH_ORDERS: '/api/v1/kalshi/orders/batch',
};

var STATUS_TYPES = {
  ONLINE: 'online',
  DEGRADED: 'degraded',
  OFFLINE: 'offline',
  GOOD: 'good',
  WARNING: 'warning',
  BAD: 'bad',
};

var LOG_LEVELS = {
  ERROR: 'error',
  WARN: 'warn',
  INFO: 'info',
  DEBUG: 'debug',
};

var DEFAULTS = {
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
};

var WS_EVENTS = {
  PRICE_TICK: 'price_tick',
  ORDER_UPDATE: 'order_update',
  FILL_UPDATE: 'fill_update',
  AGENT_UPDATE: 'agent_update',
};

module.exports = {
  __esModule: true,
  getChartColors: getChartColors,
  CHART_COLORS: CHART_COLORS,
  API_BASE_URL: API_BASE_URL,
  WS_URL: WS_URL,
  WS_PORTFOLIO_URL: WS_PORTFOLIO_URL,
  AUTH_TOKEN_KEY: AUTH_TOKEN_KEY,
  API_ENDPOINTS: API_ENDPOINTS,
  STATUS_TYPES: STATUS_TYPES,
  LOG_LEVELS: LOG_LEVELS,
  DEFAULTS: DEFAULTS,
  WS_EVENTS: WS_EVENTS,
};
