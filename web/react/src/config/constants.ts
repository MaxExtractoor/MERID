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

export const API_BASE_URL = getEnv('VITE_API_BASE', "http://127.0.0.1:8000");
export const WS_URL = getEnv('VITE_WS_URL', "ws://127.0.0.1:8000");

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
  SYMBOLS: ["BTC-USD", "ETH-USD", "SOL-USD", "MATIC-USD"],
  VENUES: ["Coinbase", "Kraken", "Binance", "Gemini"],
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
