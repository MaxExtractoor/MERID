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
export const WS_PORTFOLIO_URL = getEnv('VITE_WS_PORTFOLIO_URL', `ws://${window?.location?.host || '127.0.0.1:8000'}/ws/risk`);

// API Endpoints
export const API_ENDPOINTS = {
  // ── System ────────────────────────────────────────────────────
  SYSTEM_HEALTH: "/api/v1/system/health",
  SYSTEM_EXECUTION_GATE: "/api/v1/system/execution-gate",
  SYSTEM_MODE_SAFETY: "/api/v1/system/mode-safety",
  SYSTEM_PNL_CONSISTENCY: "/api/v1/system/pnl-consistency",
  SYSTEM_PRICE_FEED_STALENESS: "/api/v1/system/price-feed-staleness",
  SYSTEM_SESSION_LOG: "/api/v1/system/session-log",
  SYSTEM_SYMBOL_STATUS: "/api/v1/system/symbol-status",
  SYSTEM_FRESH_START: "/api/v1/system/fresh-start",
  SYSTEM_STOP: "/api/v1/monitoring/system/stop",
  SYSTEM_DECISIONS: "/api/v1/operator/decisions/recent",
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
  OPERATOR_ORDERS: "/api/v1/kalshi/orders",
  OPERATOR_AUDIT_TRAIL: "/api/v1/operator/audit-trail",
  TRADING_MODE_SET: "/api/v1/operator/trading-mode",
  GUARD_KILL: "/api/v1/operator/guard/kill",
  GUARD_UNKILL: "/api/v1/operator/guard/unkill",
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
  KALSHI_GRID_EXECUTION_HEALTH: "/api/v1/kalshi-grid/execution-health",
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

  // ── Order Groups ────────────────────────────────────────────────
  KALSHI_ORDER_GROUPS: "/api/v1/kalshi/order-groups",
  KALSHI_ORDER_GROUP_DETAIL: (groupId: string) => `/api/v1/kalshi/order-groups/${groupId}`,
  KALSHI_ORDER_GROUP_CREATE: "/api/v1/kalshi/order-groups",
  KALSHI_ORDER_GROUP_LIMIT: (groupId: string) => `/api/v1/kalshi/order-groups/${groupId}/limit`,
  KALSHI_ORDER_GROUP_TRIGGER: (groupId: string) => `/api/v1/kalshi/order-groups/${groupId}/trigger`,
  KALSHI_ORDER_GROUP_RESET: (groupId: string) => `/api/v1/kalshi/order-groups/${groupId}/reset`,
  KALSHI_ORDER_GROUP_DELETE: (groupId: string) => `/api/v1/kalshi/order-groups/${groupId}`,
  KALSHI_ORDER_GROUP_DASHBOARD: "/api/v1/kalshi/order-groups/dashboard",
  KALSHI_ORDER_GROUP_STREAM: "/api/v1/kalshi/order-groups/stream",
  KALSHI_BATCH_ORDERS: "/api/v1/kalshi/orders/batch",

  // ── Deployment Controller (paper → shadow → live) ─────────────────
  KALSHI_DEPLOYMENT_STATUS: "/api/v1/kalshi/deployment/status",
  KALSHI_DEPLOYMENT_PROMOTE_SHADOW: "/api/v1/kalshi/deployment/promote-shadow",
  KALSHI_DEPLOYMENT_PROMOTE_LIVE: "/api/v1/kalshi/deployment/promote-live",
  KALSHI_DEPLOYMENT_ROLLBACK: "/api/v1/kalshi/deployment/rollback",
  KALSHI_DEPLOYMENT_HALT: "/api/v1/kalshi/deployment/halt",
  KALSHI_DEPLOYMENT_TRANSITIONS: "/api/v1/kalshi/deployment/transitions",

  // ── Sentiment API (hashtag + news + FG) ───────────────────────────
  SENTIMENT_ASSET: (asset: string) => `/api/v1/sentiment/asset/${asset}`,
  SENTIMENT_ASSETS_ALL: "/api/v1/sentiment/assets",
  SENTIMENT_EVENT: (eventId: string) => `/api/v1/sentiment/event/${eventId}`,
  SENTIMENT_MARKET: (marketId: string) => `/api/v1/sentiment/market/${marketId}`,
  SENTIMENT_HASHTAGS: "/api/v1/sentiment/hashtags",
  SENTIMENT_HASHTAG_SIGNALS: "/api/v1/sentiment/hashtags/signals",
  SENTIMENT_NEWS: "/api/v1/sentiment/news",
  SENTIMENT_RISK_OVERLAY: (asset: string) => `/api/v1/sentiment/risk/${asset}`,
  SENTIMENT_MONITOR_STATUS: "/api/v1/sentiment/monitor/status",
  SENTIMENT_MONITOR_FORCE_CYCLE: "/api/v1/sentiment/monitor/force-cycle",
  SENTIMENT_MONITOR_FORCE_NEWS: "/api/v1/sentiment/monitor/force-news-cycle",

  // ── BTC 15m Risk Layer ─────────────────────────────────────────────
  KALSHI_RISK_BTC15M_EVALUATE: "/api/v1/kalshi/risk/btc15m/evaluate",
  KALSHI_RISK_BTC15M_STATUS: "/api/v1/kalshi/risk/btc15m/status",
  KALSHI_RISK_BTC15M_FEAR_GREED: "/api/v1/kalshi/risk/btc15m/fear-greed",
  KALSHI_RISK_BTC15M_RECORD_RESULT: "/api/v1/kalshi/risk/btc15m/record-result",
  KALSHI_RISK_DD_GUARD: "/api/v1/kalshi/risk/dd-guard",

  // ── Market Mood Bus ────────────────────────────────────────────────
  KALSHI_MOOD: (asset: string, timeframe: string) => `/api/v1/kalshi/mood/${asset}/${timeframe}`,
  KALSHI_MOOD_ALL: "/api/v1/kalshi/mood/all",
  KALSHI_MOOD_FEAR_GREED: (asset: string) => `/api/v1/kalshi/mood/fear-greed/${asset}`,

  // ── Swarm Consensus ────────────────────────────────────────────────
  KALSHI_CONSENSUS: (asset: string, timeframe: string) => `/api/v1/kalshi/consensus/${asset}/${timeframe}`,
  KALSHI_CONSENSUS_ALL: "/api/v1/kalshi/consensus/all",

  // ── Swarm Journal / Insights ───────────────────────────────────────
  KALSHI_INSIGHTS: "/api/v1/kalshi/insights",

  // ── Sentiment ────────────────────────────────────────────────────────
  KALSHI_SENTIMENT_TWITTER: (asset: string) => `/api/v1/kalshi/sentiment/twitter/${asset}`,
  KALSHI_SENTIMENT_REDDIT: (asset: string) => `/api/v1/kalshi/sentiment/reddit/${asset}`,
  KALSHI_SENTIMENT_UNIFIED: (asset: string) => `/api/v1/kalshi/sentiment/unified/${asset}`,
  KALSHI_SENTIMENT_MULTI: "/api/v1/kalshi/sentiment/multi",
  KALSHI_SENTIMENT_REFRESH: (asset: string) => `/api/v1/kalshi/sentiment/refresh/${asset}`,
  KALSHI_SENTIMENT_COMPARE: "/api/v1/kalshi/sentiment/compare",
  
  // ── SentimentBundle ──────────────────────────────────────────────────
  KALSHI_SENTIMENT_BUNDLE: (asset: string) => `/api/v1/kalshi/sentiment/bundle/${asset}`,
  KALSHI_SENTIMENT_BUNDLE_MULTI: "/api/v1/kalshi/sentiment/bundle-multi",
  KALSHI_SENTIMENT_DECIDE_BTC_15M: "/api/v1/kalshi/sentiment/decide-btc-15m",
  
  // ── Threshold Optimizer ─────────────────────────────────────────────
  KALSHI_SENTIMENT_OPTIMIZE_THRESHOLDS: (asset: string) => `/api/v1/kalshi/sentiment/optimize-thresholds/${asset}`,
  KALSHI_SENTIMENT_THRESHOLDS_STATUS: "/api/v1/kalshi/sentiment/thresholds/status",
  KALSHI_SENTIMENT_BACKTEST: (asset: string, days: number) => `/api/v1/kalshi/sentiment/backtest?asset=${asset}&days=${days}`,

  // ── CFGI Fear/Greed ──────────────────────────────────────────────────
  KALSHI_FEAR_GREED: (asset: string) => `/api/v1/kalshi/sentiment/fear-greed/${asset}`,
  KALSHI_FEAR_GREED_SUMMARY: "/api/v1/kalshi/sentiment/fear-greed/market-summary",
  
  // ── VADER Signal ─────────────────────────────────────────────────────
  KALSHI_VADER_SIGNAL: "/api/v1/kalshi/sentiment/vader/signal",
  KALSHI_VADER_KALSHI_ADJUSTMENT: "/api/v1/kalshi/sentiment/vader/kalshi-adjustment",
  
  // ── Twitter Streaming ────────────────────────────────────────────────
  KALSHI_TWITTER_STREAM_START: "/api/v1/kalshi/sentiment/twitter/stream/start",
  KALSHI_TWITTER_STREAM_STOP: "/api/v1/kalshi/sentiment/twitter/stream/stop",
  KALSHI_TWITTER_STREAM_ROLLING: (asset: string) => `/api/v1/kalshi/sentiment/twitter/stream/rolling/${asset}`,
  
  // ── Full Context ─────────────────────────────────────────────────────
  KALSHI_SENTIMENT_CONTEXT: (asset: string) => `/api/v1/kalshi/sentiment/context/${asset}`,

  // ── Lane Snapshot (live cached_sentiment from BTC15m lane) ───────────
  KALSHI_SENTIMENT_LANE_SNAPSHOT: "/api/v1/kalshi/sentiment/lane-snapshot",

  // ── Lane Control ─────────────────────────────────────────────────────
  KALSHI_LANE_STATUS:  "/api/v1/kalshi/lane/status",
  KALSHI_LANE_CONTROL: "/api/v1/kalshi/lane/control",
  KALSHI_LANE_METRICS: "/api/v1/kalshi/lane/metrics",

  // ── Cross-Timeframe Aggregator ────────────────────────────────────────
  XTF_SIGNAL: (asset: string) => `/api/v1/xtf/signal/${asset}`,
  XTF_SIGNALS_ALL: "/api/v1/xtf/signals",
  XTF_STATUS: "/api/v1/xtf/status",
  XTF_SYNC: "/api/v1/xtf/sync",

  // ── Auto Promoter ─────────────────────────────────────────────────────
  AUTO_PROMOTER_STATUS: "/api/v1/kalshi/deployment/auto-promoter/status",
  AUTO_PROMOTER_PROMOTIONS: "/api/v1/kalshi/deployment/auto-promoter/promotions",

  // ── System Config ─────────────────────────────────────────────────────
  CONFIG_RELOAD: "/api/v1/system/config-reload",

  // ── Correlation Risk (Sprint D) ──────────────────────────────────────
  CORRELATION_MATRIX: "/api/v1/kalshi/correlation/matrix",
  CORRELATION_FACTOR: "/api/v1/kalshi/correlation/factor",
  CORRELATION_CLUSTERS: "/api/v1/kalshi/correlation/clusters",

  // ── Swarm Bus (Sprint M) ─────────────────────────────────────────────
  SWARM_CRITIC_HISTORY: "/api/v1/kalshi/swarm/critic/history",
  SWARM_RECALIBRATION: "/api/v1/kalshi/swarm/recalibration",
  SWARM_EXECUTION_STATS: "/api/v1/kalshi/swarm/execution/stats",

  // ── Forecaster Metrics (Sprint A) ────────────────────────────────────
  METRICS_FORECASTERS: "/api/v1/kalshi/metrics/forecasters",
  METRICS_FORECASTER: (id: string) => `/api/v1/kalshi/metrics/forecaster/${id}`,
  METRICS_MARKET: (marketId: string) => `/api/v1/kalshi/metrics/markets/${marketId}`,
  METRICS_RESOLVER: "/api/v1/kalshi/metrics/resolver",

  // ── Portfolio & Orchestrator ──────────────────────────────────────────
  PORTFOLIO_SUMMARY: "/api/portfolio/summary",
  RISK_EXPOSURE: "/api/risk/exposure",
  ORCHESTRATOR_SUMMARY: "/api/v1/orchestrator/summary",

  // ── Trade Mode & Reconciliation ─────────────────────────────────────
  TRADE_MODE: "/api/v1/trade-mode",
  RECONCILIATION_RUN: "/api/v1/reconciliation/run",
  RECONCILIATION_STATUS: "/api/v1/reconciliation/status",

  // ── Audit Trail ─────────────────────────────────────────────────────
  AUDIT_TRAIL_SUMMARY: "/api/v1/audit-trail/summary",
  AUDIT_TRAIL_ENTRIES: "/api/v1/audit-trail/entries",

  // ── UI Sidebar Config ───────────────────────────────────────────────
  UI_SIDEBAR: "/api/v1/ui/sidebar",
  UI_MODE_INDICATOR: "/api/v1/ui/mode-indicator",
  UI_WORKFLOW: "/api/v1/ui/workflow",

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
