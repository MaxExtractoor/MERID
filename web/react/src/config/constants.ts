// MERID Configuration Constants

import { API_BASE } from './apiBase';

// Canonical API base — same-origin relative by default (Vite dev proxy /api->:8011),
// VITE_API_BASE override for non-proxied deployments. Never hardcode a host.
export const API_BASE_URL = API_BASE;

// T-034: Warn if API_BASE_URL is empty in production
if (!API_BASE_URL && typeof window !== 'undefined') {
  try {
    const meta = (globalThis as any).import?.meta;
    if (meta?.env?.PROD) {
      console.error("CRITICAL: VITE_API_BASE not set in production! All API calls will use relative URLs.");
    }
  } catch { /* non-Vite environment */ }
}

// WS_PORTFOLIO_URL removed — the only consumer (useKalshiRiskStream) pointed
// at a dead WS router and was deleted. All realtime state is polled via REST.

// API Endpoints
//
// 2026 agent-architecture cleanup: ~200 API_ENDPOINTS entries were removed because
// every component/hook that consumed them was deleted as unreachable. The removed
// routes were verified dead or unmounted: /api/v1/system/*, /api/v1/operator/*,
// /api/v1/kalshi/ui-state(+ws, agent/sentiment/market detail), /api/v1/kalshi/15m/*,
// /api/v1/lanes/*, /api/v1/monitoring/*, sentiment/mood/consensus/swarm families,
// /api/v1/incentives, /api/v1/replay, /api/v1/crypto/* (venues/spot-vs-kalshi/alerts),
// /api/metrics/*, /debates/*, logs, explainability, audit-trail, top-level /api/v1/risk/*
// families, kalshi-grid control verbs (start/stop/pause/resume/kill-switch) +
// performance/crypto sub-routes, publish-pipeline, universe, fix/*, favorites,
// volume/liquidity families, bracket-risk, responsible-trading, FVG/XTF/correlation/
// metrics/deployment/auto-promoter/order-groups/calibration/vol bundles, paper-ladder,
// pipeline venues, prediction-markets, x/telegram bots, trade-mode, reconciliation,
// ui/sidebar, config-reload, data/freshness, signals/alerts history.
// Deliberately dropped rather than kept:
//  - KALSHI_SIZING_METRICS: the GET triggers a server-side recompute (read with
//    side-effect) — a stale constant pointing at it is a footgun.
//  - KALSHI_SENTIMENT_LANE_SNAPSHOT: backend returns a synthetic 200 payload —
//    keeping the constant invites trusting fabricated data.
// If a route is revived, restore the constant from git history together with its
// consumer — do not re-add speculative entries.
export const API_ENDPOINTS = {
  // ── System ────────────────────────────────────────────────────
  // /api/v1/health is the real liveness probe on the lean app
  // (there is no /api/v1/system/*).
  SYSTEM_HEALTH: "/api/v1/health",

  // ── Kalshi ────────────────────────────────────────────────────
  KALSHI_MARKETS: "/api/v1/kalshi/markets",
  KALSHI_POSITIONS: "/api/v1/kalshi/positions",
  KALSHI_ORDERS: "/api/v1/kalshi/orders",
  KALSHI_FILLS: "/api/v1/kalshi/fills",
  KALSHI_BALANCE: "/api/v1/kalshi/balance",
  KALSHI_PNL: "/api/v1/kalshi/pnl",
} as const;

// Deliberately NOT defined (dead routes — do not re-add):
//   /api/v1/system/execution-gate (gate state is derived in useExecutionGate
//     from live-runtime-state + kill-switch in the store)
//   /api/v1/telemetry, /api/v1/notifications/* (no notification producer)
//   /api/v1/kalshi-grid/mode (mode comes from live-runtime-state)

// Auth
export const AUTH_TOKEN_KEY = "merid-access";

// Default Values
export const DEFAULTS = {
  POLLING_INTERVALS: {
    FAST: 5000,            // 5 seconds — 15m health/alignment panels
    FAST_REFRESH: 5000,    // 5 seconds — execution gate
    STANDARD: 10000,       // 10 seconds — balance, pnl, fills, grid mode
    SLOW: 30000,           // 30 seconds — connection status
    BACKGROUND: 60000,     // 60 seconds — notifications
  },
  TIMEOUTS: {
    DEBOUNCE: 50,         // 50ms debounce
    TOAST: 3000,          // 3s toast/notification
    STATUS_RESET: 5000,   // 5s status message reset
  },
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
