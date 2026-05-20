/**
 * DataPanel - Unified panel component
 * 
 * Consolidates 7 panel components into 2 configurable primitives:
 * - DataPanel (generic panel with title, content, actions)
 * - AlertPanel (specialized for Kalshi alert/history data)
 * 
 * Uses design tokens for consistent styling across all Kalshi views.
 * 
 * Tier 2: Panel Consolidation (7 → 2)
 */

import React, { useState } from 'react';
import { KALSHI_STATUS_COLORS } from '../tokens';

/**
 * DataPanel API - Generic panel component
 */
export interface DataPanelProps {
  /**
   * Panel title
   */
  title: string;
  
  /**
   * Optional icon
   */
  icon?: React.ReactNode;
  
  /**
   * Status indicator
   */
  status?: 'success' | 'warning' | 'error' | 'info' | 'neutral';
  
  /**
   * Panel content
   */
  children: React.ReactNode;
  
  /**
   * Optional actions (buttons, etc.)
   */
  actions?: React.ReactNode;
  
  /**
   * Collapsible
   */
  collapsible?: boolean;
  
  /**
   * Default collapsed state
   */
  defaultCollapsed?: boolean;
  
  /**
   * Additional CSS classes
   */
  className?: string;
}

/**
 * DataPanel Component - Generic panel for displaying data
 */
export const DataPanel = React.memo(function DataPanel({
  title,
  icon,
  status = 'neutral',
  children,
  actions,
  collapsible = false,
  defaultCollapsed = false,
  className = '',
}: DataPanelProps) {
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed);
  
  const colors = KALSHI_STATUS_COLORS[status];
  
  return (
    <div className={`
      bg-slate-900/70 rounded-xl border ${colors.border}
      ${className}
    `}>
      {/* Panel Header */}
      <div className="flex items-center justify-between p-4 border-b border-slate-800">
        <div className="flex items-center gap-3">
          {icon && (
            <div className={`${colors.bg} p-2 rounded-lg`}>
              {icon}
            </div>
          )}
          <h3 className={`font-semibold ${colors.text}`}>
            {title}
          </h3>
        </div>
        <div className="flex items-center gap-2">
          {actions}
          {collapsible && (
            <button
              onClick={() => setIsCollapsed(!isCollapsed)}
              className={`p-1 rounded hover:bg-slate-800 transition-colors ${colors.text}`}
              aria-label={isCollapsed ? 'Expand' : 'Collapse'}
            >
              <svg
                className={`w-5 h-5 transition-transform ${isCollapsed ? '-rotate-90' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M19 9l-7 7-7-7"
                />
              </svg>
            </button>
          )}
        </div>
      </div>
      
      {/* Panel Content */}
      {!isCollapsed && (
        <div className="p-4">
          {children}
        </div>
      )}
    </div>
  );
});

/**
 * Alert interface for AlertPanel
 */
export interface KalshiAlert {
  id: string;
  severity: 'success' | 'warning' | 'error' | 'info';
  message: string;
  timestamp: Date;
  source?: string;
  acknowledged?: boolean;
}

/**
 * AlertPanel API - Specialized for Kalshi alert/history data
 */
export interface AlertPanelProps {
  /**
   * Panel title
   */
  title: string;
  
  /**
   * Alert data
   */
  alerts: KalshiAlert[];
  
  /**
   * Acknowledge handler
   */
  onAcknowledge?: (alertId: string) => void;
  
  /**
   * Filter handler
   */
  onFilter?: (severity: string) => void;
  
  /**
   * Maximum visible alerts
   */
  maxVisible?: number;
  
  /**
   * Additional CSS classes
   */
  className?: string;
}

/**
 * AlertPanel Component - Specialized for Kalshi alert/history data
 */
export const AlertPanel = React.memo(function AlertPanel({
  title,
  alerts,
  onAcknowledge,
  onFilter,
  maxVisible,
  className = '',
}: AlertPanelProps) {
  const [filter, setFilter] = useState<string>('all');
  
  const filteredAlerts = filter === 'all' 
    ? alerts 
    : alerts.filter(alert => alert.severity === filter);
  
  const visibleAlerts = maxVisible 
    ? filteredAlerts.slice(0, maxVisible)
    : filteredAlerts;
  
  const handleFilterChange = (newFilter: string) => {
    setFilter(newFilter);
    onFilter?.(newFilter);
  };
  
  const handleAcknowledge = (alertId: string) => {
    onAcknowledge?.(alertId);
  };
  
  return (
    <DataPanel
      title={title}
      status={alerts.some(a => a.severity === 'error') ? 'error' : alerts.some(a => a.severity === 'warning') ? 'warning' : 'neutral'}
      className={className}
      actions={
        <div className="flex items-center gap-2">
          <select
            value={filter}
            onChange={(e) => handleFilterChange(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="all">All</option>
            <option value="error">Error</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
            <option value="success">Success</option>
          </select>
        </div>
      }
    >
      <div className="space-y-2">
        {visibleAlerts.length === 0 ? (
          <div className="text-center py-8 text-slate-500">
            No alerts
          </div>
        ) : (
          visibleAlerts.map((alert) => (
            <div
              key={alert.id}
              className={`
                flex items-start gap-3 p-3 rounded-lg border
                ${KALSHI_STATUS_COLORS[alert.severity].bg} ${KALSHI_STATUS_COLORS[alert.severity].border}
                ${alert.acknowledged ? 'opacity-50' : ''}
              `}
            >
              <div className={`flex-1`}>
                <div className="flex items-center gap-2">
                  <span className={`font-medium ${KALSHI_STATUS_COLORS[alert.severity].text}`}>
                    {alert.severity.toUpperCase()}
                  </span>
                  <span className="text-slate-400 text-xs">
                    {alert.timestamp.toLocaleString()}
                  </span>
                  {alert.source && (
                    <span className="text-slate-500 text-xs">
                      • {alert.source}
                    </span>
                  )}
                </div>
                <p className="text-sm text-slate-300 mt-1">
                  {alert.message}
                </p>
              </div>
              {onAcknowledge && !alert.acknowledged && (
                <button
                  onClick={() => handleAcknowledge(alert.id)}
                  className="px-2 py-1 text-xs bg-slate-800 hover:bg-slate-700 rounded border border-slate-700 transition-colors"
                >
                  Ack
                </button>
              )}
            </div>
          ))
        )}
        {maxVisible && filteredAlerts.length > maxVisible && (
          <div className="text-center py-2 text-sm text-slate-500">
            Showing {maxVisible} of {filteredAlerts.length} alerts
          </div>
        )}
      </div>
    </DataPanel>
  );
});
