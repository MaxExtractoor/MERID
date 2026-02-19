// MERID Configuration Constants

// Environment-based URLs - fallback for non-Vite environments (Jest)
const getEnv = (key: string, fallback: string): string => {
  try {
    const metaEnv = (import.meta as { env?: Record<string, string | undefined> }).env;
    return metaEnv?.[key] ?? fallback;
  } catch {
    return fallback;
  }
};

export const API_BASE_URL = getEnv('VITE_API_BASE', "");
export const WS_URL = getEnv('VITE_WS_URL', `ws://${window?.location?.host || '127.0.0.1:8000'}/ws/trades`);
export const WS_PORTFOLIO_URL = getEnv('VITE_WS_PORTFOLIO_URL', `ws://${window?.location?.host || '127.0.0.1:8000'}/ws/portfolio`);

// API Endpoints
export const API_ENDPOINTS = {
  // ── System ────────────────────────────────────────────────────
  SYSTEM_HEALTH: "/api/v1/system/health",
  SYSTEM_EXECUTION_GATE: "/api/v1/system/execution-gate",
  SYSTEM_STOP: "/api/v1/monitoring/system/stop",
  SYSTEM_DECISIONS: "/api/v1/system/decisions/recent",
  TELEMETRY: "/api/v1/telemetry",

  // ── Risk & Protections ────────────────────────────────────────
  RISK_PROTECTIONS: "/api/risk/protections",
  RISK_CIRCUIT_BREAKER_RESET: "/api/risk/circuit-breaker/reset",
  RISK_KILL_SWITCH: (action: string) => `/api/risk/kill-switch/${action}`,
  RISK_SUMMARY: "/api/v1/risk/summary",
  RISK_HALT_STATUS: "/api/v1/risk/halt-status",
  RISK_STALENESS: "/api/v1/risk/staleness",
  RISK_HALT: "/api/v1/risk/halt",
  RISK_RESUME: "/api/v1/risk/resume",
  LIVE_REFRESH: "/api/v1/live/refresh",

  // ── Notifications ─────────────────────────────────────────────
  NOTIFICATIONS: "/api/v1/notifications",
  NOTIFICATIONS_READ_ALL: "/api/v1/notifications/read-all",
  NOTIFICATIONS_TELEGRAM_LOG: "/api/v1/notifications/telegram/log",
  NOTIFICATION_READ: (id: string) => `/api/v1/notifications/${id}/read`,

  // ── User / Settings ───────────────────────────────────────────
  USER_PROFILE: "/api/v1/user/profile",
  USER_SETTINGS: "/api/v1/user/settings",

  // ── Logs ──────────────────────────────────────────────────────
  LOGS: "/api/v1/logs",
  LOGS_STATS: "/api/v1/logs/stats",
  LOGS_CLEAR: "/api/v1/logs/clear",

  // ── Operator Dashboard ────────────────────────────────────────
  OPERATOR_SUMMARY: "/api/v1/operator/summary",
  OPERATOR_KILL_SWITCH_STATUS: "/api/v1/operator/kill-switch-status",
  OPERATOR_RISK_STATE: "/api/v1/operator/risk-state",
  OPERATOR_AGENT_ACTIVITY: "/api/v1/operator/agent-activity",
  OPERATOR_EMERGENCY_STOP: "/api/v1/operator/emergency-stop",
  OPERATOR_RESET_KILL_SWITCH: "/api/v1/operator/reset-kill-switch",
  OPERATOR_ORDERS: "/api/v1/orders",
  OPERATOR_AUDIT_TRAIL: "/api/operator/audit-trail",
  TRADING_MODE_SET: "/api/v1/trading-mode/mode",
  GUARD_KILL: "/api/v1/loop/guard/kill",
  GUARD_UNKILL: "/api/v1/loop/guard/unkill",
  DEV_SWARM_PAUSE: "/api/dev-swarm/pause",
  DEV_SWARM_RESUME: "/api/dev-swarm/resume",
  DEV_SWARM_SHUTDOWN: "/api/dev-swarm/shutdown",
  PRIME_STATUS: "/api/v1/prime/status",
  DATA_FRESHNESS: "/api/v1/data/freshness",
  SIGNALS_ALERTS_HISTORY: "/api/v1/signals/alerts/history",
  EXPLAINABILITY_DECISIONS: "/api/v1/explainability/decisions",
  PIPELINE_VENUES: "/api/v1/pipeline/venues",
  PIPELINE_VENUE_TOGGLE: (action: string) => `/api/v1/pipeline/venue/${action}`,
  PIPELINE_VENUE_MODE: "/api/v1/pipeline/venue-mode",

  // ── Paper Ladder ──────────────────────────────────────────────
  PAPER_LADDER_STATUS: "/api/v1/paper-ladder/status",
  PAPER_LADDER_SEED_ALL: "/api/v1/paper-ladder/seed-all",

  // ── Kalshi Agent Grid ─────────────────────────────────────────
  KALSHI_GRID_STATUS: "/api/v1/kalshi-grid/status",
  KALSHI_GRID_MATRIX: "/api/v1/kalshi-grid/matrix",
  KALSHI_GRID_AGENTS: "/api/v1/kalshi-grid/agents",
  KALSHI_GRID_AGENT_SIGNALS: (name: string) => `/api/v1/kalshi-grid/agents/${name}/signals`,
  KALSHI_GRID_AGENT_ORDERS: (name: string) => `/api/v1/kalshi-grid/agents/${name}/orders`,
  KALSHI_GRID_FILLS: "/api/v1/kalshi-grid/fills",
  KALSHI_GRID_PORTFOLIO: "/api/v1/kalshi-grid/portfolio",
  KALSHI_GRID_SESSION: "/api/v1/kalshi-grid/session",
  KALSHI_GRID_START: "/api/v1/kalshi-grid/start",
  KALSHI_GRID_STOP: "/api/v1/kalshi-grid/stop",
  KALSHI_GRID_PAUSE: "/api/v1/kalshi-grid/pause",
  KALSHI_GRID_RESUME: "/api/v1/kalshi-grid/resume",
  KALSHI_GRID_AGENT_PAUSE: (name: string) => `/api/v1/kalshi-grid/agents/${name}/pause`,
  KALSHI_GRID_AGENT_RESUME: (name: string) => `/api/v1/kalshi-grid/agents/${name}/resume`,
  KALSHI_GRID_KILL_SWITCH_RESET: "/api/v1/kalshi-grid/kill-switch/reset",
  KALSHI_GRID_HEALTH: "/api/v1/kalshi-grid/health",
  KALSHI_GRID_MODE: "/api/v1/kalshi-grid/mode",
  KALSHI_GRID_SENTIMENT: "/api/v1/kalshi-grid/sentiment",

  // ── Kalshi Agent Performance ──────────────────────────────────
  KALSHI_GRID_PERFORMANCE_AGENTS: "/api/v1/kalshi-grid/performance/agents",
  KALSHI_GRID_PERFORMANCE_AGENT: (agentId: string) => `/api/v1/kalshi-grid/performance/agents/${agentId}`,
  KALSHI_GRID_PERFORMANCE_SUMMARY: "/api/v1/kalshi-grid/performance/summary",
  KALSHI_GRID_PERFORMANCE_TOP: "/api/v1/kalshi-grid/performance/top",
  KALSHI_GRID_PERFORMANCE_EXPORT: "/api/v1/kalshi-grid/performance/export",
  KALSHI_GRID_PERFORMANCE_CALIBRATION: "/api/v1/kalshi-grid/performance/calibration",

  // ── Kalshi Deep Integration ───────────────────────────────────
  KALSHI_MARKETS: "/api/v1/kalshi/markets",
  KALSHI_MARKET_DETAIL: (ticker: string) => `/api/v1/kalshi/markets/${ticker}`,
  KALSHI_CATALOG: "/api/v1/kalshi/catalog",
  KALSHI_CATALOG_REFRESH: "/api/v1/kalshi/catalog/refresh",
  KALSHI_POSITIONS: "/api/v1/kalshi/positions",
  KALSHI_ORDERS: "/api/v1/kalshi/orders",
  KALSHI_FILLS: "/api/v1/kalshi/fills",
  KALSHI_BALANCE: "/api/v1/kalshi/balance",
  KALSHI_PNL: "/api/v1/kalshi/pnl",
  KALSHI_RISK: "/api/v1/kalshi/risk",
  KALSHI_HEALTH: "/api/v1/kalshi/health",
  KALSHI_KILL_SWITCH: "/api/v1/kalshi/kill-switch",
  KALSHI_ORDERBOOK: (ticker: string) => `/api/v1/kalshi/markets/${ticker}/orderbook`,
  KALSHI_EVENT: (event: string) => `/api/v1/kalshi/events/${event}`,
  KALSHI_EXPORT: "/api/v1/kalshi/export",
  KALSHI_VOLUME_CHANGES: "/api/v1/kalshi/volume-changes",
  KALSHI_VOLUME_HISTORY: (ticker: string) => `/api/v1/kalshi/volume-history/${ticker}`,
  KALSHI_VOLUME_SMOOTHED: (ticker: string) => `/api/v1/kalshi/volume-history/${ticker}/smoothed`,
  KALSHI_VOLUME_ANOMALIES: "/api/v1/kalshi/volume-anomalies",
  KALSHI_VOLUME_ALERTS: "/api/v1/kalshi/volume-alerts",
  KALSHI_SIZING_METRICS: "/api/v1/kalshi/sizing-metrics",
  KALSHI_PNL_HISTORY: "/api/v1/kalshi/pnl-history",
  KALSHI_LIQUIDITY_ALERTS: "/api/v1/kalshi/liquidity-alerts",
  KALSHI_LIQUIDITY_HEALTH: (marketId: string) => `/api/v1/kalshi/liquidity-health/${marketId}`,
  KALSHI_EDGE: "/api/v1/kalshi/edge",
  KALSHI_RISK_EVENTS: "/api/v1/kalshi/risk/events",
  KALSHI_RISK_DOWNSIZE: "/api/v1/kalshi/risk/downsize",
  KALSHI_CONSENSUS_SIGNALS: "/api/v1/kalshi/consensus-signals",
  KALSHI_NEWS_SIGNALS: "/api/v1/kalshi/news-signals",
  KALSHI_PUBLISH_PIPELINE: "/api/v1/kalshi/publish-pipeline",
  KALSHI_PUBLISH_PIPELINE_TRIGGER: "/api/v1/kalshi/publish-pipeline/trigger",
  KALSHI_FAVORITES: "/api/v1/kalshi/favorites",
  KALSHI_FAVORITES_TOGGLE: "/api/v1/kalshi/favorites/toggle",
  KALSHI_CATEGORIES: "/api/v1/kalshi/categories",
  KALSHI_ORDER_CANCEL: (orderId: string) => `/api/v1/kalshi/orders/${orderId}`,
  KALSHI_ORDER_AMEND: (orderId: string) => `/api/v1/kalshi/orders/${orderId}`,
  KALSHI_ORDERS_BATCH_CANCEL: "/api/v1/kalshi/orders",

} as const;

// WebSocket Events
export const WS_EVENTS = {
  // Price data
  PRICE_TICK: "price_tick",

  // Order updates
  ORDER_UPDATE: "order_update",
  FILL_UPDATE: "fill_update",

  // System updates
  AGENT_UPDATE: "agent_update",
} as const;

// Auth
export const AUTH_TOKEN_KEY = "merid-access";

// Default Values
export const DEFAULTS = {
  PAGE_SIZE: 25,
  POLLING_INTERVALS: {
    PORTFOLIO: 10000, // 10 seconds
    POSITIONS: 15000, // 15 seconds
    ORDERS: 15000,   // 15 seconds
    AGENTS: 15000,   // 15 seconds
    RISK: 30000,     // 30 seconds
    RISK_ALERTS: 30000, // 30 seconds
    SYSTEM_HEALTH: 60000, // 60 seconds
    API_STATUS: 60000, // 60 seconds
    LOGS: 10000,     // 10 seconds
    LOG_STATS: 60000, // 60 seconds
    BACKTESTS: 30000, // 30 seconds
    STALENESS: 15000,      // 15 seconds
    SIMULATION: 30000,     // 30 seconds
    FAST_REFRESH: 15000,   // 15 seconds
    STANDARD: 10000,       // 10 seconds
    MEDIUM: 15000,         // 15 seconds
    SLOW: 30000,           // 30 seconds
    EXPLAINABILITY: 30000, // 30 seconds
    BACKGROUND: 60000,     // 60 seconds
    INFREQUENT: 120000,    // 2 minutes
    RARE: 300000,          // 5 minutes
    SENTIMENT: 30000,      // 30 seconds
  },
  TIMEOUTS: {
    DEBOUNCE: 50,         // 50ms debounce
    UI_FEEDBACK: 500,     // 500ms UI feedback delay
    TOAST: 3000,          // 3s toast/notification
    STATUS_RESET: 5000,   // 5s status message reset
  },
  KALSHI_SIDES: ["yes", "no"],
  KALSHI_ACTIONS: ["buy", "sell"],
  KALSHI_ORDER_TYPES: ["limit", "market"],
} as const;

// Status Types
export const STATUS_TYPES = {
  ONLINE: "online",
  DEGRADED: "degraded", 
  OFFLINE: "offline",
  GOOD: "good",
  WARNING: "warning",
  BAD: "bad",
} as const;

// Log Levels
export const LOG_LEVELS = {
  ERROR: "error",
  WARN: "warn",
  INFO: "info",
  DEBUG: "debug",
} as const;

