/**
 * MERID View System — agent-centric architecture.
 *
 * The previous 8-stage workflow model (Discover/Analyze/Consensus/Size/Execute/
 * Monitor/Promote/Protect), its VIEW_STAGES/STAGE_GROUPS navigation maps and the
 * LEGACY_VIEW_MAP deep-link redirects were removed: no live file imports them.
 * Restore from git history if the staged workflow is revived.
 *
 * Used by: Sidebar.tsx, App.tsx, CommandPalette.tsx, TopBar.tsx
 * When adding a new view, update ONLY this type.
 */

// Agent-centric views (the primary operator surface)
export type AgentView = 'agent-wall' | 'agent-detail' | 'mission-control';

// Unified View Type — every key must have a routed component in App.tsx
export type View =
  | AgentView
  | 'dashboard'
  | 'trade'
  | 'monitor'
  | 'grid'
  | 'risk'
  | 'calibration'
  | 'logs'
  | 'settings'
  | 'kalshi-dashboard'
  | 'kalshi-portfolio';
