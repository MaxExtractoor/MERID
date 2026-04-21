/**
 * MERID 8-Stage Workflow View System
 * 
 * Aligned to the trading lifecycle:
 * 1. DISCOVER - Market discovery and scanning
 * 2. ANALYZE - Technical analysis and sentiment
 * 3. CONSENSUS - Swarm intelligence and debates
 * 4. SIZE - Position sizing and bankroll management
 * 5. EXECUTE - Order entry and terminal
 * 6. MONITOR - Portfolio tracking and PnL
 * 7. PROMOTE - Deployment pipeline (paper → shadow → live)
 * 8. PROTECT - Risk management and kill switches
 *
 * Used by: Sidebar.tsx, App.tsx, CommandPalette.tsx
 * When adding a new view, update ONLY this type.
 */

// Stage 1: DISCOVER - Market Discovery
export type DiscoverView = "discover" | "discover-all-markets" | "discover-trending";

// Stage 2: ANALYZE - Technical Analysis
export type AnalyzeView = "analyze-edge" | "analyze-sentiment" | "analyze-vol";

// Stage 3: CONSENSUS - Swarm Intelligence
export type ConsensusView = "consensus-swarm" | "consensus-debates" | "consensus-performance" | "consensus-calibration";

// Stage 4: SIZE - Position Sizing
export type SizeView = "size-bankroll" | "size-lanes" | "size-sizing";

// Stage 5: EXECUTE - Order Execution
export type ExecuteView = "execute-terminal" | "execute-orders" | "execute-positions";

// Stage 6: MONITOR - Portfolio Monitoring
export type MonitorView = "monitor-portfolio" | "monitor-pnl" | "monitor-health";

// Stage 7: PROMOTE - Deployment Pipeline
export type PromoteView = "promote-pipeline" | "promote-grid";

// Stage 8: PROTECT - Risk & Safety
export type ProtectView = "protect-risk" | "protect-kill-switch" | "protect-alerts";

// System Views
export type SystemView = "overview" | "operator" | "logs" | "settings";

// Unified View Type
export type View =
  | DiscoverView
  | AnalyzeView
  | ConsensusView
  | SizeView
  | ExecuteView
  | MonitorView
  | PromoteView
  | ProtectView
  | SystemView;

// View Stage Mapping for Navigation
export const VIEW_STAGES: Record<string, { label: string; color: string; icon: string }> = {
  // Discover (Blue)
  discover: { label: "Discover", color: "text-blue-400", icon: "search" },
  "discover-all-markets": { label: "All Markets", color: "text-blue-400", icon: "globe" },
  "discover-trending": { label: "Trending", color: "text-blue-400", icon: "flame" },
  
  // Analyze (Purple)
  "analyze-edge": { label: "Edge Signals", color: "text-purple-400", icon: "target" },
  "analyze-sentiment": { label: "Sentiment", color: "text-purple-400", icon: "activity" },
  "analyze-vol": { label: "Vol & ATR", color: "text-purple-400", icon: "gauge" },
  
  // Consensus (Cyan)
  "consensus-swarm": { label: "Swarm Matrix", color: "text-cyan-400", icon: "grid" },
  "consensus-debates": { label: "Debates", color: "text-cyan-400", icon: "messageSquare" },
  "consensus-performance": { label: "Performance", color: "text-cyan-400", icon: "award" },
  "consensus-calibration": { label: "Calibration", color: "text-cyan-400", icon: "crosshair" },
  
  // Size (Amber)
  "size-bankroll": { label: "Bankroll", color: "text-amber-400", icon: "wallet" },
  "size-lanes": { label: "Lane Control", color: "text-amber-400", icon: "gitBranch" },
  "size-sizing": { label: "Sizing Metrics", color: "text-amber-400", icon: "sliders" },
  
  // Execute (Emerald)
  "execute-terminal": { label: "Terminal", color: "text-emerald-400", icon: "terminal" },
  "execute-orders": { label: "Orders", color: "text-emerald-400", icon: "clipboardList" },
  "execute-positions": { label: "Positions", color: "text-emerald-400", icon: "trendingUp" },
  
  // Monitor (Orange)
  "monitor-portfolio": { label: "Portfolio", color: "text-orange-400", icon: "briefcase" },
  "monitor-pnl": { label: "PnL History", color: "text-orange-400", icon: "dollarSign" },
  "monitor-health": { label: "System Health", color: "text-orange-400", icon: "heart" },
  
  // Promote (Violet)
  "promote-pipeline": { label: "Pipeline", color: "text-violet-400", icon: "rocket" },
  "promote-grid": { label: "Agent Grid", color: "text-violet-400", icon: "layoutGrid" },
  
  // Protect (Red)
  "protect-risk": { label: "Risk Center", color: "text-red-400", icon: "shieldAlert" },
  "protect-kill-switch": { label: "Kill Switch", color: "text-red-400", icon: "shield" },
  "protect-alerts": { label: "Alerts", color: "text-red-400", icon: "bell" },
  
  // System (Slate)
  overview: { label: "Overview", color: "text-slate-200", icon: "layoutDashboard" },
  operator: { label: "Operator", color: "text-slate-200", icon: "sliders" },
  logs: { label: "Logs", color: "text-slate-200", icon: "fileText" },
  settings: { label: "Settings", color: "text-slate-200", icon: "settings" },
};

// Stage Groups for Sidebar
export const STAGE_GROUPS = [
  { 
    id: "discover", 
    label: "1. Discover", 
    color: "blue", 
    views: ["discover", "discover-all-markets", "discover-trending"] as View[] 
  },
  { 
    id: "analyze", 
    label: "2. Analyze", 
    color: "purple", 
    views: ["analyze-edge", "analyze-sentiment", "analyze-vol"] as View[] 
  },
  { 
    id: "consensus", 
    label: "3. Consensus", 
    color: "cyan", 
    views: ["consensus-swarm", "consensus-debates", "consensus-performance", "consensus-calibration"] as View[] 
  },
  { 
    id: "size", 
    label: "4. Size", 
    color: "amber", 
    views: ["size-bankroll", "size-lanes", "size-sizing"] as View[] 
  },
  { 
    id: "execute", 
    label: "5. Execute", 
    color: "emerald", 
    views: ["execute-terminal", "execute-orders", "execute-positions"] as View[] 
  },
  { 
    id: "monitor", 
    label: "6. Monitor", 
    color: "orange", 
    views: ["monitor-portfolio", "monitor-pnl", "monitor-health"] as View[] 
  },
  { 
    id: "promote", 
    label: "7. Promote", 
    color: "violet", 
    views: ["promote-pipeline", "promote-grid"] as View[] 
  },
  { 
    id: "protect", 
    label: "8. Protect", 
    color: "red", 
    views: ["protect-risk", "protect-kill-switch", "protect-alerts"] as View[] 
  },
  { 
    id: "system", 
    label: "System", 
    color: "slate", 
    views: ["overview", "operator", "logs", "settings"] as View[] 
  },
] as const;

// Legacy View Mapping (for backward compatibility during transition)
export const LEGACY_VIEW_MAP: Record<string, View> = {
  "kalshi-dashboard": "discover",
  "kalshi-all-markets": "discover-all-markets",
  "kalshi-sentiment": "analyze-sentiment",
  "kalshi-vol-dashboard": "analyze-vol",
  "swarm-consensus": "consensus-swarm",
  "kalshi-performance": "consensus-performance",
  "calibration-dashboard": "consensus-calibration",
  "lane-control": "size-lanes",
  "kalshi-terminal": "execute-terminal",
  "orders": "execute-orders",
  "positions": "execute-positions",
  "kalshi-portfolio": "monitor-portfolio",
  "kalshi-risk": "protect-risk",
  "kill-switch": "protect-kill-switch",
  "kalshi-grid": "promote-grid",
  "kalshi-risk-context": "protect-risk",
};
