// MERID Configuration Constants

// Environment-based URLs - fallback for non-Vite environments (Jest)
const getEnv = (key: string, fallback: string): string => {
  try {
    // @ts-ignore - import.meta.env may not exist in test environment
    return import.meta.env?.[key] ?? fallback;
  } catch {
    return fallback;
  }
};

export const API_BASE_URL = getEnv('VITE_API_BASE', "");
export const WS_URL = getEnv('VITE_WS_URL', `ws://${window?.location?.host || '127.0.0.1:8000'}/ws`);

// API Endpoints
export const API_ENDPOINTS = {
  // Portfolio & Positions
  PORTFOLIO_SUMMARY: "/api/v1/portfolio/summary",
  POSITIONS: "/api/v1/positions",
  POSITIONS_SUMMARY: "/api/v1/positions/summary",
  ORDERS: "/api/v1/orders",
  ORDERS_SUMMARY: "/api/v1/orders/summary",
  FILLS: "/api/v1/fills",
  
  // Trading
  SUBMIT_ORDER: "/api/v1/orders/submit",
  CANCEL_ORDER: "/api/v1/orders/cancel",
  TRADING_SUMMARY: "/api/trading/summary",
  
  // Agents
  AGENTS: "/api/v1/agents",
  AGENTS_SUMMARY: "/api/agents/summary",
  AGENT_DETAIL: (id: string) => `/api/v1/agents/${id}`,
  AGENT_CHARTERS: "/api/v1/charters",
  
  // Prediction Markets
  PREDICTION_MARKETS: "/api/v1/us-compliant/prediction-markets",
  PREDICTION_POSITIONS: "/api/v1/prediction-markets/positions",
  
  // Risk & Health
  RISK_METRICS: "/api/v1/risk/metrics",
  RISK_PNL_SUMMARY: "/api/risk/pnl-summary",
  RISK_EXPOSURE: "/api/risk/exposure",
  RISK_LIMITS: "/api/risk/limits",
  RISK_PROTECTIONS: "/api/risk/protections",
  SYSTEM_HEALTH: "/api/v1/system/health",
  SYSTEM_HEALTH_V2: "/api/system/health",
  SYSTEM_VERSION: "/api/system/version",
  SYSTEM_COMPONENTS: "/api/system/components",
  
  // Prime Screen
  PRIME_STATUS: "/api/prime/status",
  
  // API Status
  API_STATUS: "/api/v1/api/status",
  API_METRICS: "/api/v1/api/metrics",
  
  // Research
  BACKTEST: "/api/v1/research/backtest",
  BACKTEST_RESULTS: "/api/v1/research/backtest/results",
  
  // Consensus
  CONSENSUS_SUMMARY: "/api/v1/consensus/summary",
  CONSENSUS_METRICS: "/api/v1/consensus/metrics",
  
  // Flow Domain (Memecoins, Whales, KOLs, Snipers, MEV)
  FLOW_RADAR: "/api/v1/flow/radar",
  FLOW_TOKENS: "/api/v1/flow/tokens",
  FLOW_ENTITIES: "/api/v1/flow/entities",
  FLOW_EVENTS: "/api/v1/flow/events",
  FLOW_PLANS: "/api/v1/flow/plans",
  FLOW_SNIPER_STATUS: "/api/v1/flow/sniper/status",
  FLOW_SNIPER_FILLS: "/api/v1/flow/sniper/fills",
  FLOW_RISK: "/api/v1/flow/risk",
  FLOW_METRICS: "/api/v1/flow/metrics",

  // Signal Layer (Decay, Features, Arbs, Drift, CQI)
  SIGNAL_FEATURES: "/api/v1/signal-layer/features",
  SIGNAL_SOCIAL: "/api/v1/signal-layer/social",
  SIGNAL_MACRO: "/api/v1/signal-layer/macro",
  SIGNAL_ONCHAIN: "/api/v1/signal-layer/onchain",
  SIGNAL_SNAPSHOT: "/api/v1/signal-layer/snapshot",
  SIGNAL_ARBS: "/api/v1/signal-layer/arbs",
  SIGNAL_ARB_PLANS: "/api/v1/signal-layer/arb-plans",
  SIGNAL_DRIFT: "/api/v1/signal-layer/drift",
  SIGNAL_CQI: "/api/v1/signal-layer/cqi",
  SIGNAL_METRICS: "/api/v1/signal-layer/metrics",
  SIGNAL_DECAY_CONFIGS: "/api/v1/signal-layer/decay-configs",

  // Betting Consensus
  BETTING_CONSENSUS_SUMMARY: "/api/v1/betting/consensus/summary",
  BETTING_CONSENSUS_LIVE: "/api/v1/betting/consensus/live",
  BETTING_CONSENSUS_EVENTS: "/api/v1/betting/consensus/events",
  BETTING_CONSENSUS_PLANS: "/api/v1/betting/consensus/plans",
  BETTING_CONSENSUS_METRICS: "/api/v1/betting/consensus/metrics",

  // Prediction Consensus
  PREDICTION_CONSENSUS_SUMMARY: "/api/v1/prediction/consensus/summary",
  PREDICTION_CONSENSUS_OPINIONS: "/api/v1/prediction/consensus/opinions",
  PREDICTION_CONSENSUS_PLANS: "/api/v1/prediction/consensus/plans",
  PREDICTION_CONSENSUS_INSTRUMENTS: "/api/v1/prediction/consensus/instruments",
  PREDICTION_METRICS: "/api/v1/prediction/metrics",

  // Debate & Calibration
  DEBATE_METRICS: "/api/v1/prediction/consensus/debate-metrics",
  DEBATE_LEADERBOARD: "/api/v1/prediction/consensus/leaderboard",
  DEBATE_BACKTEST: "/api/v1/prediction/consensus/backtest",
  AGENT_CALIBRATION: (agentId: string) => `/api/v1/prediction/consensus/calibration/${agentId}`,
  AGENT_BADGES: (agentId: string) => `/api/v1/prediction/consensus/badges/${agentId}`,
  AGENT_REWARDS: (agentId: string) => `/api/v1/prediction/consensus/rewards/${agentId}`,
  TEAM_LIST: "/api/v1/prediction/consensus/teams",
  TEAM_DIVERSITY: (teamId: string) => `/api/v1/prediction/consensus/teams/${teamId}/diversity`,

  // Cognitive / Reality-Debug
  COGNITIVE_SNAPSHOT: "/api/v1/cognitive/snapshot",
  COGNITIVE_HYPOTHESES: "/api/v1/cognitive/hypotheses",
  COGNITIVE_METRICS: "/api/v1/cognitive/metrics",
  COGNITIVE_STUCK: "/api/v1/cognitive/stuck-models",
  COGNITIVE_HEALTH: "/api/v1/cognitive/health",
  COGNITIVE_REALITY_DEBUG: "/api/v1/cognitive/reality-debug",
  COGNITIVE_ACTIONS: "/api/v1/cognitive/actions",

  // Paper Trading
  PAPER_PORTFOLIO: "/api/v1/paper-trading/portfolio",
  PAPER_POSITIONS: "/api/v1/paper-trading/positions",
  PAPER_ORDERS: "/api/v1/paper-trading/orders",
  PAPER_PNL_HISTORY: "/api/v1/paper-trading/pnl-history",
  PAPER_SUBMIT_ORDER: "/api/v1/paper-trading/orders/submit",

  // Sports Live / Odds
  SPORTS_LIVE_ODDS: "/api/v1/betting/consensus/live",
  SPORTS_LIVE_EVENT: (eventId: string) => `/api/v1/betting/consensus/live/${eventId}`,
  SPORTS_ANOMALIES: "/api/v1/betting/consensus/summary",
  SPORTS_DEBATES: "/api/v1/betting/consensus/events",
  SPORTS_SLO_METRICS: "/api/v1/betting/sports/slo-metrics",
  SPORTS_ODDS_HISTORY: (eventId: string) => `/api/v1/betting/consensus/live/${eventId}`,

  // Loop Orchestration
  ORCHESTRATOR_SUMMARY: "/api/v1/orchestrator/summary",
  ORCHESTRATOR_HISTORY: "/api/v1/orchestrator/history",
  DECISIONS_RECENT: "/api/v1/system/decisions/recent",
  CONSENSUS_HISTORY: "/api/v1/system/consensus/history",

  // System Observability
  OBSERVABILITY_SUMMARY: "/api/v1/system/observability",
  OBSERVABILITY_ALERTS: "/api/v1/system/alerts",
  OBSERVABILITY_SLO: "/api/v1/system/slo",
  SIGNAL_SLO_METRICS: "/api/v1/signal-layer/metrics",

  // LLM Governance
  LLM_TRACES_SUMMARY: "/api/v1/llm/traces/summary",
  LLM_TOOLS_SUMMARY: "/api/v1/llm/tools/summary",
  LLM_GUARDRAILS: "/api/v1/llm/guardrails",
  LLM_PROMPTS: "/api/v1/llm/prompts",
  
  // Promotion Report
  PROMOTION_REPORT: "/api/operator/promotion-report",
  PROMOTION_REPORT_REFRESH: "/api/operator/promotion-report/refresh",
  PROMOTION_CHECKLIST: "/api/operator/promotion-checklist",
  PROMOTION_LOG: "/api/operator/promotion-log",
  PROMOTION_OVERRIDE: "/api/operator/promotion-override",
  GOVERNANCE_STATUS: "/api/operator/governance-status",

  // Dev Swarm Governance
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

  // Wallet
  WALLET_BALANCES: "/api/v1/wallet/balances",

  // Treasury
  TREASURY_OVERVIEW: "/api/v1/treasury/overview",

  // Social
  SOCIAL_FEED: "/api/v1/social/feed",
  SOCIAL_POST: "/api/v1/social/post",

  // Mining
  MINING_OVERVIEW: "/api/v1/mining/overview",

  // Institutional
  INSTITUTIONAL_OVERVIEW: "/api/v1/institutional/overview",

  // Plugins
  PLUGINS_LIST: "/api/v1/plugins/list",

  // Betting (basic)
  BETTING_OVERVIEW: "/api/v1/betting/overview",
  BETTING_PLACE: "/api/v1/betting/place",

  // Rewards
  REWARDS_SUMMARY: "/api/v1/rewards/summary",
  REWARDS_QUESTS: "/api/v1/rewards/quests",
  REWARDS_LEADERBOARD: "/api/v1/rewards/leaderboard",

  // Overview / Portfolio
  PORTFOLIO_LIVE: "/api/portfolio/summary",
  PRICES_LIVE: "/api/prices/live",
  ORDERS_RECENT: "/api/orders/recent",
  EQUITY_SERIES: "/api/operator/equity-series",

  // Positions & Orders (trading)
  TRADING_PORTFOLIO_SUMMARY: "/api/v1/trading/portfolio/summary",
  TRADING_ORDERS_OPEN: "/api/v1/trading/orders/open",

  // Predictions (additional)
  PREDICTION_MARKETS_SUMMARY: "/api/v1/prediction-markets/summary",
  PREDICTION_DRIFT_SIGNALS: "/api/v1/us-compliant/drift-signals",
  SPECTATOR_RECORD: "/api/v1/trading-mode/spectator/record",
  SPECTATOR_LIVE: "/api/v1/trading-mode/spectator/live",

  // Logs
  LOGS: "/api/v1/logs",
  LOGS_STATS: "/api/v1/logs/stats",
  LOGS_CLEAR: "/api/v1/logs/clear",

  // User / Settings
  USER_PROFILE: "/api/v1/user/profile",
  USER_SETTINGS: "/api/v1/user/settings",
  
  // Risk (extended)
  RISK_AGENTS: "/api/v1/risk-metrics/agents",
  RISK_HALT_STATUS: "/api/v1/risk/halt-status",
  RISK_STALENESS: "/api/v1/risk/staleness",
  RISK_ALERTS: "/api/v1/risk/alerts",
  RISK_POSITION_LIMITS: "/api/v1/risk/position-limits",
  RISK_HALT: "/api/v1/risk/halt",
  RISK_RESUME: "/api/v1/risk/resume",

  // Operator Activity
  OPERATOR_ORDERS: "/api/v1/orders",
  SYSTEM_DECISIONS: "/api/v1/system/decisions/recent",
  OPERATOR_AUDIT_TRAIL: "/api/operator/audit-trail",
  DEV_SWARM_SHUTDOWN: "/api/dev-swarm/shutdown",
  SYSTEM_STOP: "/api/v1/monitoring/system/stop",

  // Signals (extended)
  SIGNALS_ALERTS_HISTORY: "/api/v1/signals/alerts/history",

  // Analytics
  ANALYTICS_OVERVIEW: "/api/v1/analytics/overview",

  // Arbitrage
  ARBITRAGE_OPPORTUNITIES: "/api/v1/arbitrage/opportunities",
  ARBITRAGE_EXECUTE: "/api/v1/arbitrage/execute",
  ARBITRAGE_SCANNER: "/api/v1/arbitrage/scanner",

  // Blockchain
  BLOCKCHAIN_COMPLIANCE: "/api/v1/blockchain/compliance",
  BLOCKCHAIN_HEALTH: "/api/v1/blockchain/health",

  // Consensus (extended)
  CONSENSUS_STATUS: "/api/v1/consensus/status",
  CONSENSUS_PLANS: "/api/v1/consensus/plans",
  CONSENSUS_VOTES: "/api/v1/consensus/votes",
  CONSENSUS_OPINIONS: "/api/v1/consensus/opinions",

  // Data
  DATA_FRESHNESS: "/api/v1/data/freshness",

  // Drift
  DRIFT_SIGNALS: "/api/v1/us-compliant/drift-signals",

  // Explainability
  EXPLAINABILITY_DECISIONS: "/api/v1/explainability/decisions",

  // Pipeline
  PIPELINE_SUMMARY: "/api/v1/pipeline/summary",
  PIPELINE_VENUES: "/api/v1/pipeline/venues",
  PIPELINE_VENUE_MODE: "/api/v1/pipeline/venue/mode",
  PIPELINE_LEADERBOARD: "/api/v1/pipeline/leaderboard",

  // Quadratic Funding
  QUADRATIC_FUNDING_PROPOSALS: "/api/v1/quadratic-funding/proposals",
  QUADRATIC_FUNDING_ROUNDS: "/api/v1/quadratic-funding/rounds/summary",

  // Reflection
  REFLECTION_SUMMARY: "/api/v1/reflection/summary",
  REFLECTION_LIST: "/api/v1/reflection/reflections",

  // Simulation
  SIMULATION_STATUS: "/api/v1/simulation/status",
  SIMULATION_RESET: "/api/v1/simulation/reset",
  SIMULATION_SAVE: "/api/v1/simulation/save",

  // Swarm
  SWARM_STATUS: "/api/v1/swarm/status",

  // Notifications
  NOTIFICATIONS: "/api/v1/notifications",
  NOTIFICATIONS_READ_ALL: "/api/v1/notifications/read-all",
  NOTIFICATIONS_TELEGRAM_LOG: "/api/v1/notifications/telegram/log",

  // Charts (operator dashboard)
  BRIER_METRICS: "/api/v1/brier/metrics",
  DOMAIN_PNL: "/api/v1/domain/pnl",
  SENTIMENT_TIMELINE: "/api/v1/signals/sentiment",

  // Markets
  MARKETS_ALL: "/api/v1/markets/all",
  MARKETS_STOCKS: "/api/v1/markets/stocks",
  MARKETS_FOREX: "/api/v1/markets/forex",
  MARKETS_COMMODITIES: "/api/v1/markets/commodities",

  // Risk Protections (circuit breaker / kill switch)
  RISK_CIRCUIT_BREAKER_RESET: "/api/risk/circuit-breaker/reset",
  RISK_KILL_SWITCH: (action: string) => `/api/risk/kill-switch/${action}`,

  // Assistant
  ASSISTANT_QUERY: "/api/v1/assistant/query",
  ASSISTANT_CONTEXTS: "/api/v1/assistant/contexts",

  // Plugins
  PLUGINS_INSTALL: (pluginId: string) => `/api/v1/plugins/install/${pluginId}`,
  PLUGINS_UNINSTALL: (pluginId: string) => `/api/v1/plugins/uninstall/${pluginId}`,
  PLUGINS_TOGGLE: (pluginId: string) => `/api/v1/plugins/toggle/${pluginId}`,

  // Prediction Markets (actions)
  PREDICTION_MARKET_ACTION: (action: string) => `/api/v1/prediction-markets/${action}`,

  // Signal Layer
  SIGNAL_LAYER_FEATURES: (symbol: string) => `/api/v1/signal-layer/features/${symbol}`,

  // Pipeline
  PIPELINE_PNL: (timeRange: string) => `/api/v1/pipeline/pnl?range=${timeRange}`,
  PIPELINE_VENUE_TOGGLE: (action: string) => `/api/v1/pipeline/venue/${action}`,

  // Risk Metrics (agent-specific)
  RISK_AGENT_EQUITY_HISTORY: (agentId: string) => `/api/v1/risk-metrics/agents/${agentId}/equity-history?limit=100`,
  RISK_AGENT_DRAWDOWN_HISTORY: (agentId: string) => `/api/v1/risk-metrics/agents/${agentId}/drawdown-history?limit=100`,
  RISK_AGENT_METRICS: (agentId: string) => `/api/v1/risk-metrics/agents/${agentId}`,

  // Notifications (per-item)
  NOTIFICATION_READ: (id: string) => `/api/v1/notifications/${id}/read`,

  // Paper Trading
  PAPER_TRADING_PORTFOLIO: (userId: string) => `/api/v1/paper-trading/portfolio/${userId}`,
  PAPER_TRADING_CLOSE_POSITION: (positionId: string) => `/api/v1/paper-trading/positions/${positionId}/close`,
  PAPER_TRADING_CANCEL_ORDER: (orderId: string) => `/api/v1/paper-trading/orders/${orderId}/cancel`,
  PAPER_TRADING_STATS: (userId: string) => `/api/v1/paper/portfolio/${userId}/stats`,

  // Simulation (speed)
  SIMULATION_SPEED: (speed: number) => `/api/v1/simulation/speed/${speed}`,

  // Authentication
  AUTH_LOGIN: "/auth/login",
  AUTH_REFRESH: "/auth/refresh",
  AUTH_LOGOUT: "/auth/logout",
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
    PORTFOLIO: 5000, // 5 seconds
    POSITIONS: 10000, // 10 seconds
    ORDERS: 10000,   // 10 seconds
    AGENTS: 10000,   // 10 seconds
    RISK: 30000,     // 30 seconds
    RISK_ALERTS: 15000, // 15 seconds
    SYSTEM_HEALTH: 60000, // 60 seconds
    API_STATUS: 30000, // 30 seconds
    LOGS: 5000,      // 5 seconds
    LOG_STATS: 30000, // 30 seconds
    BACKTESTS: 5000, // 5 seconds
    RISK_POSITION_LIMITS: 10000, // 10 seconds
    STALENESS: 5000,       // 5 seconds
    SIMULATION: 5000,      // 5 seconds
    FAST_REFRESH: 10000,   // 10 seconds
    STANDARD: 5000,        // 5 seconds
    MEDIUM: 10000,         // 10 seconds
    SLOW: 15000,           // 15 seconds
    EXPLAINABILITY: 20000, // 20 seconds
    BACKGROUND: 30000,     // 30 seconds
    INFREQUENT: 60000,     // 60 seconds
    RARE: 120000,          // 2 minutes
  },
  TIMEOUTS: {
    DEBOUNCE: 50,         // 50ms debounce
    UI_FEEDBACK: 500,     // 500ms UI feedback delay
    TOAST: 3000,          // 3s toast/notification
    STATUS_RESET: 5000,   // 5s status message reset
  },
  SYMBOLS: [
    "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD",
    "ADA-USD", "DOT-USD", "ATOM-USD", "NEAR-USD",
    "APT-USD", "SUI-USD", "LINK-USD", "UNI-USD",
    "DOGE-USD", "SHIB-USD", "PEPE-USD", "WIF-USD",
    "ARB-USD", "OP-USD", "POL-USD", "FIL-USD",
    "AAVE-USD", "MKR-USD", "RENDER-USD",
  ],
  VENUES: ["Coinbase", "Kraken", "Binance", "Alpaca", "Kalshi", "IBKR"],
  ASSET_CLASSES: ["crypto", "prediction_markets", "equities", "forex", "memecoins", "defi", "rwa"],
  ORDER_TYPES: ["MARKET", "LIMIT", "STOP", "BRACKET"],
  SIDES: ["BUY", "SELL"],
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

