// MERID Configuration Constants

// Environment-based URLs - fallback for non-Vite environments (Jest)
const getEnv = (key: string, fallback: string): string => {
  try {
    const meta = (globalThis as any).import?.meta;
    return meta?.env?.[key] ?? fallback;
  } catch {
    return fallback;
  }
};

export const API_BASE_URL = getEnv('VITE_API_BASE', "http://localhost:8011");

// T-034: Warn if API_BASE_URL is empty in production
if (!API_BASE_URL && typeof window !== 'undefined') {
  try {
    const meta = (globalThis as any).import?.meta;
    if (meta?.env?.PROD) {
      console.error("CRITICAL: VITE_API_BASE not set in production! All API calls will use relative URLs.");
    }
  } catch { /* non-Vite environment */ }
}
export const WS_URL = getEnv('VITE_WS_URL', 'ws://localhost:8011/ws/trades');
export const WS_PORTFOLIO_URL = getEnv('VITE_WS_PORTFOLIO_URL', 'ws://localhost:8011/ws/risk');

// API Endpoints
export const API_ENDPOINTS = {
  // ── System ────────────────────────────────────────────────────
  SYSTEM_HEALTH: "/api/v1/system/health",
  SYSTEM_EXECUTION_GATE: "/api/v1/system/execution-gate",
  LOOP_EXECUTION_STATUS: "/api/v1/loop/execution/status",
  LOOP_EXECUTION_TOGGLE: "/api/v1/loop/execution/toggle",
  LOOP_LIVE_READINESS: "/api/v1/loop/live-readiness",
  LOOP_TICK_LOG: "/api/v1/loop/tick-log",
  LOOP_STATUS: "/api/v1/loop/status",
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
  RISK_PROTECTIONS: "/api/v1/operator/risk-state",
  RISK_CIRCUIT_BREAKER_RESET: "/api/v1/operator/reset-kill-switch",
  RISK_KILL_SWITCH: (action: string) => action === 'enable' ? '/api/v1/operator/guard/kill' : '/api/v1/operator/guard/unkill',
  RISK_SUMMARY: "/api/v1/risk/summary",
  RISK_HALT_STATUS: "/api/v1/risk/halt-status",
  RISK_STALENESS: "/api/v1/risk/staleness",
  RISK_HALT: "/api/v1/risk/halt",
  RISK_RESUME: "/api/v1/risk/resume",
  RISK_ALERTS: "/api/v1/risk/alerts",
  RISK_POSITION_LIMITS: "/api/v1/risk/position-limits",
  RISK_AGENTS: "/api/v1/risk/agents",
  RISK_AGENT_EQUITY_HISTORY: (agentId: string) => `/api/v1/risk/agents/${agentId}/equity-history`,
  RISK_AGENT_DRAWDOWN_HISTORY: (agentId: string) => `/api/v1/risk/agents/${agentId}/drawdown-history`,
  RISK_AGENT_METRICS: (agentId: string) => `/api/v1/risk/agents/${agentId}/metrics`,

  // ── Pipeline ─────────────────────────────────────────────────
  PIPELINE_PNL: (venue: string) => `/api/v1/pipeline/venues/${venue}/pnl`,

  // ── Paper Trading ─────────────────────────────────────────────
  PAPER_TRADING_PORTFOLIO: (portfolioId: string) => `/api/v1/paper-trading/${portfolioId}`,

  // ── Notifications ─────────────────────────────────────────────
  NOTIFICATIONS: "/api/v1/notifications",
  NOTIFICATIONS_READ_ALL: "/api/v1/notifications/read-all",
  NOTIFICATIONS_TELEGRAM_LOG: "/api/v1/notifications/telegram/log",
  NOTIFICATION_READ: (id: string) => `/api/v1/notifications/${id}/read`,

  // ── Social Bots (X / Reddit / Telegram) ─────────────────────
  X_BOT_STATUS: "/api/x/status",
  X_BOT_POST: "/api/x/post",
  TELEGRAM_BOT_STATUS: "/api/v1/notifications/telegram/status",
  TELEGRAM_SEND_ALERT: "/api/v1/notifications/telegram/send",

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
  PRIME_STATUS: "/api/v1/swarm/prime-screen/state",
  DATA_FRESHNESS: "/api/v1/data/freshness",
  SIGNALS_ALERTS_HISTORY: "/api/v1/signals/alerts/history",
  PM_ALERTS: "/api/v1/prediction-markets/alerts",
  PM_ALERT_ACKNOWLEDGE: (alertId: string) => `/api/v1/prediction-markets/alerts/${alertId}/acknowledge`,
  EXPLAINABILITY_DECISIONS: "/api/v1/explainability/decisions",
  PIPELINE_VENUES: "/api/v1/pipeline/venues",
  PIPELINE_VENUE_TOGGLE: (action: string) => `/api/v1/pipeline/venue/${action}`,
  PIPELINE_VENUE_MODE: "/api/v1/pipeline/venue/mode",

  // ── Paper Ladder ──────────────────────────────────────────────
  PAPER_LADDER_STATUS: "/api/v1/paper-ladder/status",
  PAPER_LADDER_SEED_ALL: "/api/v1/paper-ladder/seed-all",

  // ── Pre-Scale Monitoring ─────────────────────────────────────
  MONITORING_PRE_SCALE_HEALTH: "/api/v1/monitoring/pre-scale-health",
  MONITORING_RISK_EVENTS: "/api/v1/monitoring/risk-events",
  MONITORING_AUDIT_CHAIN_VERIFY: "/api/v1/monitoring/audit-chain/verify",
  MONITORING_TAINTED_PATHS: "/api/v1/monitoring/tainted-paths",

  // ── Kalshi Agent Grid ─────────────────────────────────────────
  KALSHI_GRID_STATUS: "/api/v1/kalshi-grid/status",
  KALSHI_GRID_MATRIX: "/api/v1/kalshi-grid/matrix",
  KALSHI_GRID_AGENTS: "/api/v1/kalshi-grid/agents",
  KALSHI_GRID_AGENT: (name: string) => `/api/v1/kalshi-grid/agents/${name}`,
  KALSHI_GRID_AGENT_SIGNALS: (name: string) => `/api/v1/kalshi-grid/agents/${name}/signals`,
  KALSHI_GRID_AGENT_ORDERS: (name: string) => `/api/v1/kalshi-grid/agents/${name}/orders`,
  KALSHI_GRID_FILLS: "/api/v1/kalshi-grid/fills",
  KALSHI_GRID_PNL: "/api/v1/kalshi-grid/pnl",
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
  KALSHI_GRID_CANARY_TRADE: "/api/v1/kalshi-grid/canary-trade",

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
  KALSHI_DISCOVER_HEALTH: "/api/v1/kalshi/discover-health",
  KALSHI_SWARM_GRID: "/api/v1/kalshi/swarm/grid",
  KALSHI_SWARM_HEALTH: "/api/v1/kalshi/swarm/health",
  KALSHI_SENTIMENT_PNL_ATTRIBUTION: "/api/v1/kalshi/sentiment/pnl-attribution",
  KALSHI_SENTIMENT_PNL: "/api/v1/kalshi/sentiment/pnl",
  KALSHI_KILL_SWITCH: "/api/v1/kalshi/kill-switch",
  KALSHI_CIRCUIT_BREAKER: "/api/v1/resilience/breakers",
  KALSHI_LATENCY: "/api/metrics/latency",
  KALSHI_ORDER_ERRORS: "/api/v1/kalshi/order-errors",
  KALSHI_ORDERBOOK: (ticker: string) => `/api/v1/kalshi/markets/${ticker}/orderbook`,
  KALSHI_ORDERBOOK_STREAM: (ticker: string) => `/api/v1/kalshi/markets/${ticker}/orderbook/stream`,
  KALSHI_EVENT: (event: string) => `/api/v1/kalshi/events/${event}`,
  KALSHI_EXPORT: "/api/v1/kalshi/export",
  KALSHI_VOLUME_CHANGES: "/api/v1/kalshi/volume-changes",
  KALSHI_VOLUME_HISTORY: (ticker: string) => `/api/v1/kalshi/volume-history/${ticker}`,
  KALSHI_VOLUME_SMOOTHED: (ticker: string) => `/api/v1/kalshi/volume-history/${ticker}/smoothed`,
  KALSHI_VOLUME_ANOMALIES: "/api/v1/kalshi/volume-anomalies",
  KALSHI_VOLUME_ALERTS: "/api/v1/kalshi/volume-alerts",
  KALSHI_SIZING_METRICS: "/api/v1/kalshi/sizing-metrics",
  KALSHI_CONTINUOUS_TRADER_STATUS: "/api/v1/kalshi/continuous-trader/status",
  KALSHI_CONTINUOUS_TRADER_STOP: "/api/v1/kalshi/continuous-trader/stop",
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
  SENTIMENT_HASHTAG_SIGNALS: "/api/v1/sentiment/hashtags/signals",
  SENTIMENT_MONITOR_STATUS: "/api/v1/sentiment/monitor/status",

  // ── BTC 15m Risk Layer ─────────────────────────────────────────────
  KALSHI_RISK_BTC15M_STATUS: "/api/v1/kalshi/risk/btc15m/status",

  // ── P0 Guardrails (Crypto Spot → Kalshi Safety) ─────────────────
  KALSHI_P0_GUARDRAILS_STATUS: "/api/v1/kalshi/guardrails/p0-status",

  // ── Market Mood Bus ────────────────────────────────────────────────
  KALSHI_MOOD: (asset: string, timeframe: string) => `/api/v1/kalshi/mood/${asset}/${timeframe}`,
  KALSHI_MOOD_ALL: "/api/v1/kalshi/mood/all",
  KALSHI_MOOD_FEAR_GREED: (asset: string) => `/api/v1/kalshi/mood/fear-greed/${asset}`,

  // ── Swarm Consensus ────────────────────────────────────────────────
  KALSHI_CONSENSUS: (asset: string, timeframe: string) => `/api/v1/kalshi/consensus/${asset}/${timeframe}`,
  KALSHI_CONSENSUS_ALL: "/api/v1/kalshi/consensus/all",

  // ── Swarm Journal / Insights ───────────────────────────────────────
  KALSHI_INSIGHTS: "/api/v1/kalshi/insights",
  KALSHI_RISK_INSIGHTS: "/api/v1/kalshi/risk/insights",

  // ── SentimentBundle ──────────────────────────────────────────────────
  KALSHI_SENTIMENT_BUNDLE: (asset: string) => `/api/v1/kalshi/sentiment/bundle/${asset}`,

  // ── Lane Snapshot (live cached_sentiment from BTC15m lane) ───────────
  KALSHI_SENTIMENT_LANE_SNAPSHOT: "/api/v1/kalshi/sentiment/lane-snapshot",

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
  KALSHI_METRICS_RESOLVE_ALL: "/api/v1/kalshi/metrics/resolve-all",
  KALSHI_METRICS_ORDER_INVARIANTS: "/api/v1/kalshi/metrics/order-invariants",
  KALSHI_METRICS_HEDGE: "/api/v1/kalshi/metrics/hedge",
  KALSHI_METRICS_SIGNAL_STATE: "/api/v1/kalshi/metrics/signal-state",
  KALSHI_METRICS_CYCLE_DRAWDOWN: "/api/v1/kalshi/metrics/cycle-drawdown",
  KALSHI_CYCLE_DRAWDOWN_RESET: "/api/v1/kalshi/metrics/cycle-drawdown/reset",

  // ── Prediction Consensus & Debate (Sprint 8) ────────────────────────
  PREDICTION_CONSENSUS_SUMMARY: "/api/v1/prediction/consensus/summary",
  PREDICTION_CONSENSUS_PLANS: "/api/v1/prediction/consensus/plans",
  PREDICTION_CONSENSUS_OPINIONS: "/api/v1/prediction/consensus/opinions",
  PREDICTION_DEBATES: "/api/v1/prediction/consensus/debates",
  PREDICTION_DEBATE_DETAIL: (id: string) => `/api/v1/prediction/consensus/debates/${id}`,
  PREDICTION_DEBATE_METRICS: "/api/v1/prediction/consensus/debate-metrics",
  PREDICTION_TEAMS: "/api/v1/prediction/consensus/teams",
  PREDICTION_LEADERBOARD: "/api/v1/prediction/consensus/leaderboard",
  PREDICTION_REWARDS: (agentId: string) => `/api/v1/prediction/consensus/rewards/${agentId}`,
  PREDICTION_BADGES: (agentId: string) => `/api/v1/prediction/consensus/badges/${agentId}`,
  PREDICTION_METRICS: "/api/v1/prediction/metrics",

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

  // ── Risk / Sentiment-Vol API (canonical) ────────────────────────────
  SENTIMENT_VOL_ASSETS: "/api/v1/risk/sentiment-vol/assets",
  SENTIMENT_VOL_ASSET: (asset: string) => `/api/v1/risk/sentiment-vol/asset/${asset}`,
  SENTIMENT_VOL_SUMMARY: "/api/v1/risk/sentiment-vol/summary",
  SENTIMENT_VOL_ALERTS: "/api/v1/risk/sentiment-vol/alerts",
  SENTIMENT_VOL_HEALTH: "/api/v1/risk/sentiment-vol/health",
  SENTIMENT_VOL_CONFIG: "/api/v1/risk/sentiment-vol/config",

  // ── Debate Data ───────────────────────────────────────────────────
  DEBATE_ALERTS: "/debates/alerts",
  DEBATE_CORRELATION: "/debates/correlation",
  DEBATE_HISTORICAL_CONTRIBUTION: "/debates/historical-contribution",
  DEBATE_ROLLUPS: "/debates/rollups",
  KALSHI_DEBATE_STATS: "/debates/health/overview",

  // ── Crypto Spot vs Kalshi ─────────────────────────────────────────
  CRYPTO_SPOT_VS_KALSHI: "/api/v1/crypto/spot-vs-kalshi",

  // ── Kalshi Crypto & Execution Telemetry ───────────────────────────
  KALSHI_CRYPTO_RTI: "/api/v1/kalshi-grid/crypto/rti",
  KALSHI_EQUITY_SERIES: "/api/v1/operator/equity-series",
  KALSHI_EXECUTION_TELEMETRY: "/api/v1/kalshi-grid/performance/execution",

  // ── Lane Status ───────────────────────────────────────────────────
  LANE_STATUS: "/api/v1/kalshi/lane/status",

  // ── Notification Status & Recent Alerts ───────────────────────────
  NOTIFICATION_STATUS: "/api/v1/notifications/status",
  NOTIFICATION_RECENT_ALERTS: "/api/v1/notifications/recent-alerts",

  // ── Risk Alert Acknowledge ────────────────────────────────────────
  RISK_ALERT_ACKNOWLEDGE: (alertId: string) => `/api/v1/risk/alerts/${alertId}/acknowledge`,
  RISK_ALERTS_ACKNOWLEDGE_ALL: "/api/v1/risk/alerts/acknowledge-all",

  // ── Swarm Verdicts ────────────────────────────────────────────────
  SWARM_VERDICTS: "/api/v1/kalshi/swarm/verdicts",

  // ── Crypto Alert Router ───────────────────────────────────────────
  CRYPTO_ALERTS_STATUS: "/api/v1/alerts/crypto/status",
  CRYPTO_ALERTS_METRICS: "/api/v1/alerts/crypto/metrics",

  // ── Spot/Kalshi Basis Tracker ─────────────────────────────────────
  SPOT_BASIS: "/api/v1/kalshi/spot-basis",
  SPOT_BASIS_STATS: "/api/v1/kalshi/spot-basis/stats",

  // ── Calibration Tracker (Brier score + per-cell metrics) ─────────
  CALIBRATION_STATS: "/api/v1/kalshi/calibration/stats",
  CALIBRATION_WEIGHTS: "/api/v1/kalshi/calibration/weights",
  CALIBRATION_FORECASTERS: "/api/v1/kalshi/calibration/forecasters",
  CALIBRATION_UNRESOLVED: "/api/v1/kalshi/calibration/unresolved",
  CALIBRATION_RESOLVE: "/api/v1/kalshi/calibration/resolve",
  CALIBRATION_CELL_METRICS: "/api/v1/kalshi/calibration/cell-metrics",

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
    RISK_POSITION_LIMITS: 60000, // 60 seconds
    SYSTEM_HEALTH: 60000, // 60 seconds
    API_STATUS: 60000, // 60 seconds
    LOGS: 10000,     // 10 seconds
    LOG_STATS: 60000, // 60 seconds
    BACKTESTS: 30000, // 30 seconds
    STALENESS: 15000,      // 15 seconds
    SIMULATION: 30000,     // 30 seconds
    FAST: 5000,            // 5 seconds — alias for FAST_REFRESH
    FAST_REFRESH: 5000,    // 5 seconds — kill switch, execution gate, halt status
    STANDARD: 10000,       // 10 seconds — balance, risk, positions, orders
    MEDIUM: 20000,         // 20 seconds — catalog, health, sizing
    SLOW: 30000,           // 30 seconds — edge signals, PnL history, volume
    EXPLAINABILITY: 30000, // 30 seconds
    BACKGROUND: 60000,     // 60 seconds
    INFREQUENT: 120000,    // 2 minutes
    RARE: 300000,          // 5 minutes
    SENTIMENT: 30000,      // 30 seconds
    CRYPTO_ALERTS: 30000,  // 30 seconds — matches router tick interval
    SPOT_BASIS: 2000,      // 2 seconds — tracker ticks at 1s, 2s poll is sufficient
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

// Chart Colors
export const CHART_COLORS = {
  GREEN: "#22c55e",
  RED: "#ef4444",
  YELLOW: "#eab308",
  ORANGE: "#f97316",
  BLUE: "#3b82f6",
  PURPLE: "#a855f7",
  CYAN: "#06b6d4",
  TEAL: "#14b8a6",
  LIGHT_RED: "#fca5a5",
  LIGHT_GREEN: "#86efac",
  LIGHT_BLUE: "#93c5fd",
  LIGHT_PURPLE: "#d8b4fe",
  AMBER: "#f59e0b",
  DEEP_ORANGE: "#ea580c",
  AXIS_TICK: "#64748b",
  GRID_STROKE: "#334155",
  TOOLTIP_BG: "#0f172a",
  TOOLTIP_BORDER: "#334155",
  TOOLTIP_LABEL: "#e2e8f0",
  BAR_BASE: "#1e293b",
  // Extended palette
  EMERALD: "#10b981",
  SLATE_400: "#94a3b8",
  SLATE_600: "#475569",
  INDIGO: "#6366f1",
  RED_600: "#dc2626",
  RED_800: "#991b1b",
  RED_50: "#fef2f2",
  RED_100: "#fee2e2",
  RED_200: "#fecaca",
  GREEN_50: "#dcfce7",
  GREEN_50B: "#f0fdf4",
  GREEN_200: "#bbf7d0",
  GREEN_600: "#16a34a",
  GREEN_800: "#166534",
  AMBER_100: "#fef3c7",
  AMBER_800: "#92400e",
  BLUE_100: "#dbeafe",
  BLUE_800: "#1e40af",
  GRAY_300: "#d1d5db",
  GRAY_400: "#9ca3af",
  GRAY_500: "#6b7280",
  GRAY_700: "#374151",
  GRAY_800: "#1f2937",
  GRAY_900: "#111827",
  GRAY_100: "#f3f4f6",
  GRAY_50: "#f9fafb",
  GRAY_200: "#e5e7eb",
  WHITE: "#ffffff",
} as const;

/**
 * Returns theme-aware chart chrome colors (grid lines, axis ticks, tooltip).
 * Pass `isDark` from `useTheme().theme === 'dark'`.
 * Semantic data colors (GREEN, RED, AMBER, etc.) are unchanged — they work in both themes.
 */
export function getChartColors(isDark: boolean) {
  return {
    AXIS_TICK:      isDark ? "#64748b" : "#64748b",
    GRID_STROKE:    isDark ? "#334155" : "#e2e8f0",
    TOOLTIP_BG:     isDark ? "#0f172a" : "#ffffff",
    TOOLTIP_BORDER: isDark ? "#334155" : "#e2e8f0",
    TOOLTIP_LABEL:  isDark ? "#e2e8f0" : "#1e293b",
    BAR_BASE:       isDark ? "#1e293b" : "#f1f5f9",
  };
}

// Readiness Status
export const READINESS_STATUS = {
  OK: "ok",
  DRIFTED: "drifted",
  MISSING: "missing",
} as const;

// Order Status
export const ORDER_STATUS = {
  RESTING: "resting",
  PENDING: "pending",
  CANCELED: "canceled",
  CANCELLED: "cancelled",
  FILLED: "filled",
} as const;

// Order Group Status
export const ORDER_GROUP_STATUS = {
  ACTIVE: "active",
  TRIGGERED: "triggered",
  CANCELED: "canceled",
  PENDING: "pending",
  ALL: "all",
} as const;

// Agent Status
export const AGENT_STATUS = {
  RUNNING: "running",
  ACTIVE: "active",
  ERROR: "error",
  PAUSED: "paused",
  IDLE: "idle",
} as const;

// Health Status
export const HEALTH_STATUS = {
  HEALTHY: "healthy",
  DEGRADED: "degraded",
  UNHEALTHY: "unhealthy",
} as const;

// Grid Cell Status
export const GRID_CELL_STATUS = {
  ACTIVE: "active",
  COVERING: "covering",
  IDLE: "idle",
} as const;

// Log Levels
export const LOG_LEVELS = {
  ERROR: "error",
  WARN: "warn",
  INFO: "info",
  DEBUG: "debug",
} as const;

// Cache TTL defaults (ms)
export const CACHE_TTL = {
  DEFAULT: 30000,     // 30 seconds
  SHORT: 5000,        // 5 seconds
  STANDARD: 30000,    // 30 seconds
  LONG: 120000,       // 2 minutes
  PERSISTENT: 600000, // 10 minutes
  RECONCILIATION: 60000,  // 1 minute
  DECISIONS: 30000,       // 30 seconds
  AUDIT: 120000,          // 2 minutes
  ANALYTICS: 60000,       // 1 minute
} as const;

// Retry defaults for data fetching
export const RETRY_DEFAULTS = {
  MAX_RETRIES: 3,
  BASE_DELAY: 1000,
  MAX_DELAY: 30000,
  BACKOFF_FACTOR: 2,
} as const;

