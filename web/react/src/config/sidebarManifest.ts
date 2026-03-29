/**
 * Sidebar Navigation Manifest — the frontend single source of truth.
 *
 * This file mirrors the canonical `web/api/sidebar_config.py` on the backend.
 * Used by: Sidebar.tsx (rendering), smoke tests (validation), CommandPalette.
 *
 * When adding a new view:
 *   1. Add it here
 *   2. Add it to sidebar_config.py
 *   3. Add it to views.ts
 *   4. Add the route in App.tsx
 *   5. Run `py -m pytest tests/test_sidebar_wiring.py` to verify
 */

import type { View } from '../types/views';

export interface SidebarItem {
  name: string;
  href: View;
  icon: string;
  color: string;
}

export interface SidebarSection {
  label: string;
  key: string;
  items: SidebarItem[];
}

export const SIDEBAR_MANIFEST: SidebarSection[] = [
  {
    label: 'Live Trading',
    key: 'live-trading',
    items: [
      { name: 'Overview',     href: 'overview',            icon: 'LayoutDashboard', color: 'text-blue-400' },
      { name: 'Terminal',     href: 'kalshi-terminal',     icon: 'Monitor',         color: 'text-orange-400' },
      { name: 'Markets',      href: 'kalshi-dashboard',    icon: 'Search',          color: 'text-orange-300' },
      { name: 'Portfolio',    href: 'kalshi-portfolio',    icon: 'Briefcase',       color: 'text-orange-300' },
      { name: 'Positions',    href: 'positions',           icon: 'TrendingUp',      color: 'text-cyan-400' },
      { name: 'Orders',       href: 'orders',              icon: 'ClipboardList',   color: 'text-teal-300' },
    ],
  },
  {
    label: 'Swarm Intelligence',
    key: 'swarm-intelligence',
    items: [
      { name: 'Agent Grid',   href: 'kalshi-grid',         icon: 'LayoutGrid',      color: 'text-orange-500' },
      { name: 'Swarm Matrix', href: 'swarm-consensus',     icon: 'Grid',            color: 'text-cyan-500' },
      { name: 'Performance',  href: 'kalshi-performance',  icon: 'Award',           color: 'text-emerald-400' },
      { name: 'Calibration',  href: 'calibration-dashboard', icon: 'Target',        color: 'text-rose-400' },
      { name: 'Lane Control', href: 'lane-control',        icon: 'GitBranch',       color: 'text-violet-400' },
    ],
  },
  {
    label: 'Analytics',
    key: 'analytics',
    items: [
      { name: 'Discover',    href: 'discover-health',    icon: 'Radar',           color: 'text-emerald-400' },
      { name: 'Fear/Greed',  href: 'kalshi-sentiment',   icon: 'Activity',        color: 'text-rose-400' },
      { name: 'Vol & Sizing', href: 'kalshi-vol-dashboard', icon: 'Gauge',         color: 'text-purple-400' },
    ],
  },
  {
    label: 'Command Center',
    key: 'command-center',
    items: [
      { name: 'Operator',    href: 'operator',    icon: 'Sliders',    color: 'text-indigo-400' },
      { name: 'Kill Switch', href: 'kill-switch', icon: 'ShieldAlert', color: 'text-red-400' },
    ],
  },
  {
    label: 'System',
    key: 'system',
    items: [
      { name: 'Logs',     href: 'logs',     icon: 'Terminal',  color: 'text-gray-400' },
      { name: 'Settings', href: 'settings', icon: 'Settings2', color: 'text-gray-400' },
    ],
  },
];

/** Flat list of all sidebar items for iteration. */
export const ALL_SIDEBAR_ITEMS: SidebarItem[] = SIDEBAR_MANIFEST.flatMap(s => s.items);

/** Set of all navigable hrefs from the sidebar. */
export const SIDEBAR_HREFS: Set<View> = new Set(ALL_SIDEBAR_ITEMS.map(i => i.href));
