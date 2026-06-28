/**
 * Sidebar Navigation Manifest — NEW 8-View Architecture
 * 
 * Consolidated from 20+ views to 8 core views aligned with 15m stack
 * 
 * Views:
 *   - Dashboard: Single pane of glass (system health, kill switch, key metrics)
 *   - Trade: Order entry and position management
 *   - Monitor: Portfolio monitoring and PnL tracking
 *   - Grid: Agent management and deployment
 *   - Risk: Risk analytics and sizing
 *   - Calibration: Agent calibration and consensus
 *   - Logs: System logs and audit trail
 *   - Settings: Configuration and profile management
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
    label: 'Dashboard',
    key: 'dashboard',
    items: [
      { name: 'Dashboard', href: 'dashboard', icon: 'LayoutDashboard', color: 'text-blue-400' },
    ],
  },
  {
    label: 'Operations',
    key: 'operations',
    items: [
      { name: 'Trade', href: 'trade', icon: 'Monitor', color: 'text-orange-400' },
      { name: 'Monitor', href: 'monitor', icon: 'Briefcase', color: 'text-cyan-400' },
      { name: 'Grid', href: 'grid', icon: 'LayoutGrid', color: 'text-orange-500' },
    ],
  },
  {
    label: 'Analytics',
    key: 'analytics',
    items: [
      { name: 'Risk', href: 'risk', icon: 'Gauge', color: 'text-purple-400' },
      { name: 'Calibration', href: 'calibration', icon: 'Target', color: 'text-rose-400' },
    ],
  },
  {
    label: 'System',
    key: 'system',
    items: [
      { name: 'Logs', href: 'logs', icon: 'Terminal', color: 'text-gray-400' },
      { name: 'Settings', href: 'settings', icon: 'Settings2', color: 'text-gray-400' },
    ],
  },
];

/** Flat list of all sidebar items for iteration. */
export const ALL_SIDEBAR_ITEMS: SidebarItem[] = SIDEBAR_MANIFEST.flatMap(s => s.items);

/** Set of all navigable hrefs from the sidebar. */
export const SIDEBAR_HREFS: Set<View> = new Set(ALL_SIDEBAR_ITEMS.map(i => i.href));
