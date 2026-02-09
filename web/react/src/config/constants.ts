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
  
  // Logs
  LOGS: "/api/v1/logs",
  
  // Authentication
  AUTH_LOGIN: "/auth/login",
  AUTH_REFRESH: "/auth/refresh",
  AUTH_LOGOUT: "/auth/logout",
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

// Default Values
export const DEFAULTS = {
  PAGE_SIZE: 25,
  POLLING_INTERVALS: {
    PORTFOLIO: 5000, // 5 seconds
    POSITIONS: 2000, // 2 seconds
    ORDERS: 1000,    // 1 second
    AGENTS: 10000,   // 10 seconds
    RISK: 30000,     // 30 seconds
  },
  SYMBOLS: [
    "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD",
    "ADA-USD", "DOT-USD", "ATOM-USD", "NEAR-USD",
    "APT-USD", "SUI-USD", "LINK-USD", "UNI-USD",
    "DOGE-USD", "SHIB-USD", "PEPE-USD", "WIF-USD",
    "ARB-USD", "OP-USD", "MATIC-USD", "FIL-USD",
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

// Log Levels
export const LOG_LEVELS = {
  ERROR: "error",
  WARN: "warn",
  INFO: "info",
  DEBUG: "debug",
} as const;

// Chart Colors (Tailwind palette)
export const CHART_COLORS = {
  PRIMARY: "#22c55e", // green-500
  DANGER: "#ef4444", // red-500
  WARNING: "#f59e0b", // amber-500
  INFO: "#3b82f6",   // blue-500
  NEUTRAL: "#6b7280", // gray-500
} as const;
