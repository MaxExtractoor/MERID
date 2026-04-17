/**
 * Shared View type — the single source of truth for all sidebar navigation targets.
 *
 * Used by: Sidebar.tsx, App.tsx, CommandPalette.tsx
 * When adding a new view, update ONLY this type.
 */

export type View =
  | "overview"
  | "kalshi-dashboard"
  | "kalshi-grid"
  | "kalshi-all-markets"
  | "kalshi-portfolio"
  | "kalshi-vol-dashboard"
  | "kalshi-risk-context"
  | "kalshi-risk"
  | "kalshi-terminal"
  | "kalshi-performance"
  | "kalshi-sentiment"
  | "positions"
  | "orders"
  | "operator"
  | "kill-switch"
  | "logs"
  | "settings"
  | "lane-control"
  | "swarm-consensus"
  | "calibration-dashboard";
