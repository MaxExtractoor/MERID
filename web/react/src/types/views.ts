/**
 * MERID View System — consolidated 7-view architecture.
 *
 * One job per view, no overlapping surfaces:
 *   agent-wall      primary dashboard — 5 asset agents, system ribbon, feed
 *   agent-detail    per-asset drill (charts, lanes, gates, book)
 *   mission-control fleet wallboard
 *   terminal        order entry + market instruments
 *   portfolio       positions / orders / fills / pnl
 *   risk            safety state + controls
 *   system          calibration / logs / settings tabs
 *
 * Deleted predecessors: dashboard (absorbed by wall + risk), grid (≈ wall),
 * monitor (→ portfolio), trade (→ terminal), calibration/logs/settings
 * (→ system tabs), kalshi-dashboard/kalshi-portfolio (debug stubs).
 *
 * Used by: Sidebar.tsx, App.tsx, CommandPalette.tsx, TopBar.tsx
 * When adding a new view, update ONLY this type.
 */

// Agent-centric views (the primary operator surface)
export type AgentView = 'agent-wall' | 'agent-detail' | 'mission-control';

// Unified View Type — every key must have a routed component in App.tsx
export type View =
  | AgentView
  | 'terminal'
  | 'portfolio'
  | 'risk'
  | 'system';
