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
export const WS_PRICE_URL = getEnv('VITE_WS_PRICE_URL', `ws://${window?.location?.host || '127.0.0.1:8000'}/ws/dashboard-prices`);
export const WS_PORTFOLIO_URL = getEnv('VITE_WS_PORTFOLIO_URL', `ws://${window?.location?.host || '127.0.0.1:8000'}/ws/portfolio`);

// API Endpoints
export const API_ENDPOINTS = {
  // System Health
  SYSTEM_HEALTH: "/api/v1/system/health",
  SYSTEM_EXECUTION_GATE: "/api/v1/system/execution-gate",
  SYSTEM_FRESH_START: "/api/v1/system/fresh-start",
  EQUITY_SERIES: "/api/operator/equity-series",

  // Risk Protections (circuit breaker / kill switch) — used by RiskProtectionsPanel
  RISK_PROTECTIONS: "/api/risk/protections",
  RISK_CIRCUIT_BREAKER_RESET: "/api/risk/circuit-breaker/reset",
  RISK_KILL_SWITCH: (action: string) => `/api/risk/kill-switch/${action}`,
  RISK_METRICS: "/api/v1/risk/metrics",

  // Notifications — used by LiveNotifications component
  NOTIFICATIONS: "/api/v1/notifications",
  NOTIFICATIONS_READ_ALL: "/api/v1/notifications/read-all",
  NOTIFICATIONS_TELEGRAM_LOG: "/api/v1/notifications/telegram/log",
  NOTIFICATION_READ: (id: string) => `/api/v1/notifications/${id}/read`,

  // User / Settings
  USER_PROFILE: "/api/v1/user/profile",
  USER_SETTINGS: "/api/v1/user/settings",

  // Paper trading (referenced by PaperTradingView — not actively routed)
  PAPER_PORTFOLIO: "/api/v1/paper/portfolio",
  PAPER_POSITIONS: "/api/v1/paper/positions",
  PAPER_ORDERS: "/api/v1/paper/orders",

  // Legacy agent endpoints (referenced by Agents.tsx — not actively routed)
  AGENTS: "/api/v1/agents",
  AGENT_DETAIL: (id: string) => `/api/v1/agents/${id}`,
  AGENT_CHARTERS: "/api/v1/charters",

  // Operator sub-components
  ARBITRAGE_SCANNER: "/api/v1/arbitrage/scanner",
  ARBITRAGE_OPPORTUNITIES: "/api/v1/arbitrage/opportunities",
  ARBITRAGE_EXECUTE: "/api/v1/arbitrage/execute",
  CONSENSUS_STATUS: "/api/v1/consensus/status",
  CONSENSUS_VOTES: "/api/v1/consensus/votes",
  CONSENSUS_METRICS: "/api/v1/consensus/metrics",
  CONSENSUS_PLANS: "/api/v1/consensus/plans",
  CONSENSUS_OPINIONS: "/api/v1/consensus/opinions",
  ASSISTANT_QUERY: "/api/v1/assistant/query",
  PRIME_STATUS: "/api/v1/prime/status",
  DRIFT_SIGNALS: "/api/v1/signals/drift",
  PIPELINE_PNL: (timeRange: string) => `/api/v1/pipeline/pnl?range=${timeRange}`,
  PIPELINE_VENUES: "/api/v1/pipeline/venues",
  PIPELINE_VENUE_TOGGLE: (action: string) => `/api/v1/pipeline/venue/${action}`,
  SENTIMENT_TIMELINE: "/api/v1/signals/sentiment",
  BRIER_METRICS: "/api/v1/brier/metrics",
  DOMAIN_PNL: "/api/v1/domain/pnl",
  DATA_FRESHNESS: "/api/v1/data/freshness",
  ORCHESTRATOR_SUMMARY: "/api/v1/orchestrator/summary",
  ORCHESTRATOR_HISTORY: "/api/v1/orchestrator/history",
  DECISIONS_RECENT: "/api/v1/system/decisions/recent",
  CONSENSUS_HISTORY: "/api/v1/system/consensus/history",
  REWARDS_LEADERBOARD: "/api/v1/rewards/leaderboard",
  PIPELINE_LEADERBOARD: "/api/v1/pipeline/leaderboard",
  BLOCKCHAIN_COMPLIANCE: "/api/v1/blockchain/compliance",
  PROMOTION_REPORT: "/api/operator/promotion-report",
  PROMOTION_REPORT_REFRESH: "/api/operator/promotion-report/refresh",
  PROMOTION_CHECKLIST: "/api/operator/promotion-checklist",
  PROMOTION_LOG: "/api/operator/promotion-log",
  PROMOTION_OVERRIDE: "/api/operator/promotion-override",
  GOVERNANCE_STATUS: "/api/operator/governance-status",
  PAPER_LADDER_STATUS: "/api/v1/paper-ladder/status",
  PAPER_LADDER_SEED: "/api/v1/paper-ladder/seed",
  PAPER_LADDER_SEED_ALL: "/api/v1/paper-ladder/seed-all",
  PAPER_LADDER_TIERS: "/api/v1/paper-ladder/tiers",
  BENCHMARKS_REPORT: "/api/v1/benchmarks/report",
  SIGNALS_ALERTS_HISTORY: "/api/v1/signals/alerts/history",
  EXPLAINABILITY_DECISIONS: "/api/v1/explainability/decisions",
  PIPELINE_SUMMARY: "/api/v1/pipeline/summary",
  BLOCKCHAIN_HEALTH: "/api/v1/blockchain/health",
  RISK_AGENTS: "/api/v1/risk-metrics/agents",
  ANALYTICS_OVERVIEW: "/api/v1/analytics/overview",
  SWARM_STATUS: "/api/v1/swarm/status",
  RISK_HALT_STATUS: "/api/v1/risk/halt-status",
  RISK_STALENESS: "/api/v1/risk/staleness",
  RISK_HALT: "/api/v1/risk/halt",
  RISK_RESUME: "/api/v1/risk/resume",
  RISK_ALERTS: "/api/v1/risk/alerts",
  RISK_POSITION_LIMITS: "/api/v1/risk/position-limits",
  OBSERVABILITY_SUMMARY: "/api/v1/monitoring/observability/summary",
  LLM_TRACES_SUMMARY: "/api/v1/llm/traces/summary",
  LLM_TOOLS_SUMMARY: "/api/v1/llm/tools/summary",
  LLM_GUARDRAILS: "/api/v1/llm/guardrails",
  LLM_PROMPTS: "/api/v1/llm/prompts",
  SPORTS_SLO_METRICS: "/api/v1/sports/slo/metrics",
  MARKETS_STOCKS: "/api/v1/markets/stocks",
  MARKETS_FOREX: "/api/v1/markets/forex",
  MARKETS_COMMODITIES: "/api/v1/markets/commodities",
  MARKETS_ALL: "/api/v1/markets",
  ORDERS: "/api/v1/orders",
  PREDICTION_CONSENSUS_SUMMARY: "/api/v1/prediction-consensus/summary",
  PREDICTION_METRICS: "/api/v1/prediction-consensus/metrics",
  PREDICTION_MARKETS: "/api/v1/prediction-markets",
  SIGNAL_FEATURES: "/api/v1/signals/features",
  SIGNAL_SOCIAL: "/api/v1/signals/social",
  SIGNAL_CQI: "/api/v1/signals/cqi",
  SIGNAL_ARBS: "/api/v1/signals/arbs",
  SIGNAL_METRICS: "/api/v1/signals/metrics",
  SIGNAL_DECAY_CONFIGS: "/api/v1/signals/decay-configs",
  SPORTS_LIVE_ODDS: "/api/v1/sports/live-odds",
  TELEMETRY: "/api/v1/telemetry",
  COGNITIVE_REALITY_DEBUG: "/api/v1/cognitive/reality-debug",
  COGNITIVE_HEALTH: "/api/v1/cognitive/health",
  COGNITIVE_ACTIONS: "/api/v1/cognitive/actions",
  COGNITIVE_SNAPSHOT: "/api/v1/cognitive/snapshot",
  QUADRATIC_FUNDING_PROPOSALS: "/api/v1/quadratic-funding/proposals",
  QUADRATIC_FUNDING_ROUNDS: "/api/v1/quadratic-funding/rounds",
  RISK_SUMMARY: "/api/v1/risk/summary",
  LIVE_REFRESH: "/api/v1/live/refresh",
  REFLECTION_SUMMARY: "/api/v1/reflection/summary",
  REFLECTION_LIST: "/api/v1/reflection/list",
  SIMULATION_STATUS: "/api/v1/simulation/status",
  SIMULATION_RESET: "/api/v1/simulation/reset",
  SIMULATION_SPEED: (speed: number) => `/api/v1/simulation/speed/${speed}`,
  SIMULATION_SAVE: "/api/v1/simulation/save",
  BETTING_CONSENSUS_SUMMARY: "/api/v1/betting-consensus/summary",
  BETTING_CONSENSUS_METRICS: "/api/v1/betting-consensus/metrics",
  DEBATE_METRICS: "/api/v1/debate/metrics",
  DEBATE_LEADERBOARD: "/api/v1/debate/leaderboard",
  AGENT_CALIBRATION: (agentId: string) => `/api/v1/agents/${agentId}/calibration`,
  AGENT_BADGES: (agentId: string) => `/api/v1/agents/${agentId}/badges`,
  AGENT_REWARDS: (agentId: string) => `/api/v1/agents/${agentId}/rewards`,
  TEAM_DIVERSITY: (teamId: string) => `/api/v1/agents/teams/${teamId}/diversity`,
  CANCEL_ORDER: (id: string) => `/api/v1/orders/${id}/cancel`,
  PAPER_TRADING_STATS: (userId: string) => `/api/v1/paper/stats/${userId}`,
  FLOW_RADAR: "/api/v1/flow/radar",
  FLOW_METRICS: "/api/v1/flow/metrics",
  FLOW_SNIPER_STATUS: "/api/v1/flow/sniper/status",
  FLOW_SNIPER_FILLS: "/api/v1/flow/sniper/fills",
  FLOW_RISK: "/api/v1/flow/risk",
  SPORTS_LIVE_EVENT: (eventId: string) => `/api/v1/sports/events/${eventId}`,
  TRADE_MODE: "/api/v1/trade-mode",
  PORTFOLIO_SUMMARY: "/api/v1/portfolio/summary",
  PORTFOLIO_LIVE: "/api/v1/portfolio/live",
  PIPELINE_VENUE_MODE: "/api/v1/pipeline/venue-mode",
  PAPER_TRADING_PORTFOLIO: (userId: string) => `/api/v1/paper/portfolio/${userId}`,
  PAPER_TRADING_CLOSE_POSITION: (id: string) => `/api/v1/paper/positions/${id}/close`,
  PAPER_TRADING_CANCEL_ORDER: (id: string) => `/api/v1/paper/orders/${id}/cancel`,
  DEV_GOVERNANCE_PROPOSALS: "/api/dev-swarm/governance/proposals",
  DEV_GOVERNANCE_PROPOSAL: (id: string) => `/api/dev-swarm/governance/proposals/${id}`,
  DEV_GOVERNANCE_PROPOSAL_STATUS: (id: string) => `/api/dev-swarm/governance/proposals/${id}/status`,
  DEV_GOVERNANCE_PROPOSAL_APPROVALS: (id: string) => `/api/dev-swarm/governance/proposals/${id}/approvals`,
  DEV_GOVERNANCE_PROPOSAL_DEBATES: (id: string) => `/api/dev-swarm/governance/proposals/${id}/debates`,
  DEV_GOVERNANCE_PROPOSAL_METRICS: (id: string) => `/api/dev-swarm/governance/proposals/${id}/metrics`,
  DEV_GOVERNANCE_METRICS: "/api/dev-swarm/governance/metrics",
  DEV_GOVERNANCE_AGENT_STATS: "/api/dev-swarm/governance/agent-stats",
  DEV_GOVERNANCE_RISK_POLICY: "/api/dev-swarm/governance/risk-policy",
  DEV_GOVERNANCE_AUDIT_LOG: "/api/dev-swarm/governance/audit-log",
  DEV_GOVERNANCE_PENDING: "/api/dev-swarm/governance/pending-approvals",
  RISK_AGENT_EQUITY_HISTORY: (agentId: string) => `/api/v1/risk-metrics/agents/${agentId}/equity-history?limit=100`,
  RISK_AGENT_DRAWDOWN_HISTORY: (agentId: string) => `/api/v1/risk-metrics/agents/${agentId}/drawdown-history?limit=100`,
  RISK_AGENT_METRICS: (agentId: string) => `/api/v1/risk-metrics/agents/${agentId}`,

  // Logs
  LOGS: "/api/v1/logs",
  LOGS_STATS: "/api/v1/logs/stats",
  LOGS_CLEAR: "/api/v1/logs/clear",

  // Operator Summary
  OPERATOR_SUMMARY: "/api/v1/operator/summary",
  OPERATOR_KILL_SWITCH_STATUS: "/api/v1/operator/kill-switch-status",
  OPERATOR_RISK_STATE: "/api/v1/operator/risk-state",
  OPERATOR_AGENT_ACTIVITY: "/api/v1/operator/agent-activity",
  OPERATOR_EMERGENCY_STOP: "/api/v1/operator/emergency-stop",
  OPERATOR_RESET_KILL_SWITCH: "/api/v1/operator/reset-kill-switch",
  DEV_SWARM_PAUSE: "/api/dev-swarm/pause",
  DEV_SWARM_RESUME: "/api/dev-swarm/resume",
  TRADING_MODE_SET: "/api/v1/trading-mode/mode",
  GUARD_STATUS: "/api/v1/loop/guard/status",
  GUARD_KILL: "/api/v1/loop/guard/kill",
  GUARD_UNKILL: "/api/v1/loop/guard/unkill",
  OPERATOR_ORDERS: "/api/v1/orders",
  SYSTEM_DECISIONS: "/api/v1/system/decisions/recent",
  OPERATOR_AUDIT_TRAIL: "/api/operator/audit-trail",
  DEV_SWARM_SHUTDOWN: "/api/dev-swarm/shutdown",
  SYSTEM_STOP: "/api/v1/monitoring/system/stop",

  // Kalshi Agent Grid
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
  
  // Kalshi Agent Performance
  KALSHI_GRID_PERFORMANCE_AGENTS: "/api/v1/kalshi-grid/performance/agents",
  KALSHI_GRID_PERFORMANCE_AGENT: (agentId: string) => `/api/v1/kalshi-grid/performance/agents/${agentId}`,
  KALSHI_GRID_PERFORMANCE_SUMMARY: "/api/v1/kalshi-grid/performance/summary",
  KALSHI_GRID_PERFORMANCE_TOP: "/api/v1/kalshi-grid/performance/top",
  KALSHI_GRID_PERFORMANCE_EXPORT: "/api/v1/kalshi-grid/performance/export",
  KALSHI_GRID_PERFORMANCE_CALIBRATION: "/api/v1/kalshi-grid/performance/calibration",

  // Kalshi Deep Integration
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
  KALSHI_WS: "/api/v1/kalshi/ws",
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

// Chart Colors — centralized hex values for Recharts visualizations
export const CHART_COLORS = {
  // Semantic
  GREEN: '#22c55e',
  RED: '#ef4444',
  YELLOW: '#facc15',
  ORANGE: '#f59e0b',
  BLUE: '#3b82f6',
  PURPLE: '#a855f7',
  CYAN: '#06b6d4',
  TEAL: '#10b981',
  LIGHT_RED: '#f87171',
  LIGHT_GREEN: '#4ade80',
  LIGHT_BLUE: '#60a5fa',
  LIGHT_PURPLE: '#a78bfa',
  AMBER: '#d97706',
  DEEP_ORANGE: '#f97316',

  // Neutral / UI
  SLATE_300: '#94a3b8',
  SLATE_400: '#64748b',
  SLATE_500: '#475569',
  SLATE_600: '#334155',
  SLATE_700: '#1e293b',
  SLATE_800: '#0f172a',
  GRAY_500: '#6b7280',

  // Chart-specific
  AXIS_TICK: '#94a3b8',
  GRID_STROKE: '#334155',
  TOOLTIP_BG: '#1e293b',
  TOOLTIP_BORDER: '#334155',
  TOOLTIP_LABEL: '#94a3b8',
  BAR_BASE: '#475569',
} as const;

// WebSocket Events
export const WS_EVENTS = {
  // Price data
  PRICE_TICK: "price_tick",
  SUBSCRIBE_PRICES: "subscribe_prices",
  UNSUBSCRIBE_PRICES: "unsubscribe_prices",
  
  // Order updates
  ORDER_UPDATE: "order_update",
  FILL_UPDATE: "fill_update",
  
  // System updates
  SYSTEM_STATUS: "system_status",
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
    RISK_POSITION_LIMITS: 30000, // 30 seconds
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

// Arb Scanner Status
export const ARB_STATUS = {
  LIVE: 'live',
  FILLED: 'filled',
  SUBMITTED: 'submitted',
  FAILED: 'failed',
} as const;

// Compliance Venue Status
export const COMPLIANCE_STATUS = {
  ALLOWED: 'ALLOWED',
  RESTRICTED: 'RESTRICTED',
  PROHIBITED: 'PROHIBITED',
} as const;

// Dev Proposal Status
export const PROPOSAL_STATUS = {
  DRAFT: 'draft',
  IN_REVIEW: 'in_review',
  APPROVED: 'approved',
  SCHEDULED: 'scheduled',
  EXECUTING: 'executing',
  EXECUTED: 'executed',
} as const;

// Swarm Readiness Check Status
export const READINESS_STATUS = {
  OK: 'OK',
  DRIFTED: 'DRIFTED',
  MISSING: 'MISSING',
} as const;

// Log Levels
export const LOG_LEVELS = {
  ERROR: "error",
  WARN: "warn",
  INFO: "info",
  DEBUG: "debug",
} as const;

