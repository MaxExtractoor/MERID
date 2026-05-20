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

// Stage 1: DISCOVER - Market Discovery (consolidated into unified DiscoverView with tabs)
export type DiscoverView = "discover";
export type DiscoverTab = "focus" | "universe" | "trending";

// Stage 2: ANALYZE - Technical Analysis
export type AnalyzeView = "analyze-sentiment" | "analyze-vol";

// Stage 3: CONSENSUS - Swarm Intelligence
export type ConsensusView = "consensus-swarm" | "consensus-performance" | "consensus-calibration";

// Stage 4: SIZE - Position Sizing (consolidated into unified SizeView)
export type SizeView = "size";
export type SizeTab = "bankroll" | "lanes" | "sizing";

// Stage 5: EXECUTE - Order Execution (consolidated into unified ExecuteView with tabs)
export type ExecuteView = "execute";
export type ExecuteTab = "terminal" | "orders" | "positions";

// Stage 6: MONITOR - Portfolio Monitoring (consolidated into unified MonitorView with tabs)
export type MonitorView = "monitor";
export type MonitorTab = "portfolio" | "pnl" | "health";

// Stage 7: PROMOTE - Deployment Pipeline (consolidated into unified PromoteView)
export type PromoteView = "promote";
export type PromoteTab = "pipeline" | "grid";

// Stage 8: PROTECT - Risk & Safety (consolidated into unified ProtectView with tabs)
export type ProtectView = "protect";
export type ProtectTab = "overview" | "alerts" | "kill-switch" | "context";

// System Views
export type SystemView = "overview" | "operator" | "logs" | "settings";

// Legacy view keys still referenced by the sidebar manifest and some tests.
// Keep as part of the View union until the manifest is migrated to the
// consolidated view names.
//
// DEPRECATED: These legacy view names are maintained only for backward compatibility.
// Do not add new entries to this type. Use the consolidated View types instead.
//
// NOTE: KalshiDashboardView and KalshiTerminalView removed (stub views, functionality moved to consolidated views)
export type LegacyView =
  | "kalshi-all-markets"
  | "kalshi-portfolio"
  | "positions"
  | "orders"
  | "kalshi-grid"
  | "swarm-consensus"
  | "kalshi-performance"
  | "calibration-dashboard"
  | "lane-control"
  | "kalshi-risk-context"
  | "kalshi-sentiment"
  | "kalshi-vol-dashboard"
  | "kill-switch";

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
  | SystemView
  | LegacyView;

// View Stage Mapping for Navigation
export const VIEW_STAGES: Record<string, { label: string; color: string; icon: string }> = {
  // Stage 1: Discover (Blue) - Consolidated unified view
  discover: { label: "Discover", color: "text-blue-400", icon: "search" },
  
  // Stage 2: Analyze (Purple)
  "analyze-sentiment": { label: "Sentiment", color: "text-purple-400", icon: "activity" },
  "analyze-vol": { label: "Vol & ATR", color: "text-purple-400", icon: "gauge" },
  
  // Stage 3: Consensus (Cyan)
  "consensus-swarm": { label: "Swarm Matrix", color: "text-cyan-400", icon: "grid" },
  "consensus-performance": { label: "Performance", color: "text-cyan-400", icon: "award" },
  "consensus-calibration": { label: "Calibration", color: "text-cyan-400", icon: "crosshair" },
  
  // Stage 4: Size (Amber) - Consolidated unified view
  size: { label: "Size", color: "text-amber-400", icon: "sliders" },
  
  // Stage 5: Execute (Emerald) - Consolidated unified view
  execute: { label: "Execute", color: "text-emerald-400", icon: "terminal" },
  
  // Stage 6: Monitor (Orange) - Consolidated unified view
  monitor: { label: "Monitor", color: "text-orange-400", icon: "briefcase" },
  
  // Stage 7: Promote (Violet) - Consolidated unified view
  promote: { label: "Promote", color: "text-violet-400", icon: "rocket" },
  
  // Stage 8: Protect (Red) - Consolidated unified view
  protect: { label: "Protect", color: "text-red-400", icon: "shield" },
  
  // System (Slate)
  overview: { label: "Overview", color: "text-slate-200", icon: "layoutDashboard" },
  operator: { label: "Operator", color: "text-slate-200", icon: "sliders" },
  logs: { label: "Logs", color: "text-slate-200", icon: "fileText" },
  settings: { label: "Settings", color: "text-slate-200", icon: "settings" },
};

// Stage Groups for Sidebar - Consolidated Architecture
export const STAGE_GROUPS = [
  { 
    id: "discover", 
    label: "1. Discover", 
    color: "blue", 
    views: ["discover"] as View[],
    tabs: [
      { id: "focus", label: "Focus" },
      { id: "universe", label: "Universe" },
      { id: "trending", label: "Trending" },
    ]
  },
  { 
    id: "analyze", 
    label: "2. Analyze", 
    color: "purple", 
    views: ["analyze-sentiment", "analyze-vol"] as View[] 
  },
  { 
    id: "consensus", 
    label: "3. Consensus", 
    color: "cyan", 
    views: ["consensus-swarm", "consensus-performance", "consensus-calibration"] as View[] 
  },
  { 
    id: "size", 
    label: "4. Size", 
    color: "amber", 
    views: ["size"] as View[],
    tabs: [
      { id: "bankroll", label: "Bankroll" },
      { id: "lanes", label: "Lane Control" },
      { id: "sizing", label: "Sizing" },
    ]
  },
  { 
    id: "execute", 
    label: "5. Execute", 
    color: "emerald", 
    views: ["execute"] as View[],
    tabs: [
      { id: "terminal", label: "Terminal" },
      { id: "orders", label: "Orders" },
      { id: "positions", label: "Positions" },
    ]
  },
  { 
    id: "monitor", 
    label: "6. Monitor", 
    color: "orange", 
    views: ["monitor"] as View[],
    tabs: [
      { id: "portfolio", label: "Portfolio" },
      { id: "pnl", label: "PnL History" },
      { id: "health", label: "Health" },
    ]
  },
  { 
    id: "promote", 
    label: "7. Promote", 
    color: "violet", 
    views: ["promote"] as View[],
    tabs: [
      { id: "pipeline", label: "Pipeline" },
      { id: "grid", label: "Agent Grid" },
    ]
  },
  { 
    id: "protect", 
    label: "8. Protect", 
    color: "red", 
    views: ["protect"] as View[],
    tabs: [
      { id: "overview", label: "Overview" },
      { id: "alerts", label: "Alerts" },
      { id: "kill-switch", label: "Kill Switch" },
      { id: "context", label: "Context" },
    ]
  },
  { 
    id: "system", 
    label: "System", 
    color: "slate", 
    views: ["overview", "operator", "logs", "settings"] as View[] 
  },
] as const;

// Legacy View Mapping (for backward compatibility during transition)
//
// TRANSITIONAL ARCHITECTURE:
// ==========================
// The UI has migrated from many individual views to a consolidated 8-stage workflow:
// - Stage 1 (Discover): Unified view replaces kalshi-dashboard, kalshi-all-markets
// - Stage 2 (Analyze): Individual views preserved (KalshiSentimentView, KalshiVolDashboardView)
// - Stage 3 (Consensus): Individual views preserved (KalshiAgentPerformanceView, CalibrationDashboardView)
// - Stage 4 (Size): Unified view replaces lane-control
// - Stage 5 (Execute): Unified view replaces kalshi-terminal, orders, positions
// - Stage 6 (Monitor): Unified view replaces kalshi-portfolio
// - Stage 7 (Promote): Unified view replaces kalshi-grid
// - Stage 8 (Protect): Unified view replaces kill-switch, kalshi-risk-context
//
// This LEGACY_VIEW_MAP allows deep links and old navigation to continue working
// by redirecting to the appropriate consolidated view. It should NOT be extended
// for new features - all new views should use the consolidated architecture.
//
// NOTE: kalshi-dashboard and kalshi-terminal removed (stub views deleted)
// LEGACY REMOVAL: SwarmConsensusMatrix removed - consensus module deleted
export const LEGACY_VIEW_MAP: Record<string, View> = {
  // Stage 1: Discover - all map to unified discover view
  "kalshi-all-markets": "discover",
  "discover-all-markets": "discover",
  "discover-trending": "discover",
  
  // Stage 2: Analyze - individual views preserved
  "kalshi-sentiment": "analyze-sentiment",
  "kalshi-vol-dashboard": "analyze-vol",
  
  // Stage 3: Consensus - individual views preserved
  "swarm-consensus": "consensus-swarm",
  "kalshi-performance": "consensus-performance",
  "calibration-dashboard": "consensus-calibration",
  
  // Stage 4: Size - all map to unified size view
  "lane-control": "size",
  "size-bankroll": "size",
  "size-lanes": "size",
  "size-sizing": "size",
  
  // Stage 5: Execute - all map to unified execute view
  "execute-terminal": "execute",
  "execute-orders": "execute",
  "execute-positions": "execute",
  "orders": "execute",
  "positions": "execute",
  
  // Stage 6: Monitor - all map to unified monitor view
  "kalshi-portfolio": "monitor",
  "monitor-portfolio": "monitor",
  "monitor-pnl": "monitor",
  "monitor-health": "monitor",
  
  // Stage 7: Promote - all map to unified promote view
  "kalshi-grid": "promote",
  "promote-pipeline": "promote",
  "promote-grid": "promote",
  
  // Stage 8: Protect - all map to unified protect view
  "kalshi-risk": "protect",
  "kalshi-risk-context": "protect",
  "protect-risk": "protect",
  "protect-kill-switch": "protect",
  "protect-alerts": "protect",
  "kill-switch": "protect",
};
