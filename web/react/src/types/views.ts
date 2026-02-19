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
  | "kalshi-portfolio"
  | "kalshi-vol-dashboard"
  | "kalshi-terminal"
  | "kalshi-performance"
  | "positions"
  | "orders"
  | "operator"
  | "kill-switch"
  | "logs"
  | "settings";
