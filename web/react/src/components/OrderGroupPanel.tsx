/**
 * OrderGroupPanel.tsx — Real-time order group management UI.
 *
 * Provides:
 * - Live order group status display with utilization bars
 * - Create/reset/delete order group actions
 * - Real-time alerts for triggered/high-utilization groups
 * - Integration with useOrderGroupStream for live updates
 *
 * Usage:
 *   <OrderGroupPanel />
 */

import React, { useState, useCallback, useMemo } from 'react';
import { useOrderGroupStream } from '../hooks/useOrderGroupStream';
import { API_BASE_URL, API_ENDPOINTS } from '../config/constants';
import { logUxEvent } from '../utils/uxTelemetry';

export interface OrderGroup {
  order_group_id: string;
  name: string;
  status: 'active' | 'triggered' | 'canceled' | 'pending' | 'unknown';
  subaccount: number;
  contracts_limit: number;
  matched_contracts: number;
  used_contracts: number;
  remaining_contracts: number;
  utilization_pct: number;
  filled_cost: number;
  remaining_cost: number;
  max_cost: number;
}

export interface OrderGroupSummary {
  total_groups: number;
  active: number;
  triggered: number;
  canceled: number;
  pending: number;
}

export interface OrderGroupUsage {
  total_contracts_limit: number;
  total_matched_contracts: number;
  total_used_contracts: number;
  total_filled_cost: number;
  total_remaining_cost: number;
  overall_utilization_pct: number;
}

interface OrderGroupPanelProps {
  /** Specific group IDs to monitor (undefined = all) */
  groupIds?: string[];
  /** Callback when a group is triggered */
  onGroupTriggered?: (groupId: string) => void;
  /** Callback when user selects a group */
  onGroupSelect?: (group: OrderGroup) => void;
  /** Show compact view */
  compact?: boolean;
}

/**
 * Order Group Management Panel
 * 
 * Displays real-time order group status with live updates via SSE.
 * Includes actions to create, reset, and delete order groups.
 */
export function OrderGroupPanel({
  groupIds,
  onGroupTriggered,
  onGroupSelect,
  compact = false,
}: OrderGroupPanelProps): JSX.Element {
  const [isCreating, setIsCreating] = useState(false);
  const [newGroupName, setNewGroupName] = useState('');
  const [newGroupLimit, setNewGroupLimit] = useState(1000);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<OrderGroup['status'] | 'all'>('all');

  // Subscribe to real-time updates
  const {
    groups: liveGroups,
    alerts,
    isConnected,
    error: streamError,
    reconnectAttempts,
  } = useOrderGroupStream({
    groupIds,
    autoConnect: true,
    onTriggered: (groupId) => {
      onGroupTriggered?.(groupId);
    },
  });

  // Transform live updates into OrderGroup format
  const groups: OrderGroup[] = Object.values(liveGroups).map((g) => ({
    order_group_id: g.order_group_id,
    name: g.order_group_id, // Fallback name
    status: (g.status as OrderGroup['status']) || 'unknown',
    subaccount: 0,
    contracts_limit: g.contracts_limit || 0,
    matched_contracts: g.matched_contracts || 0,
    used_contracts: g.used_contracts || 0,
    remaining_contracts: (g.contracts_limit || 0) - (g.used_contracts || 0),
    utilization_pct: g.contracts_limit
      ? Math.round(((g.used_contracts || 0) / g.contracts_limit) * 100)
      : 0,
    filled_cost: g.filled_cost || 0,
    remaining_cost: g.remaining_cost || 0,
    max_cost: 0,
  }));

  // Calculate summary stats
  const summary: OrderGroupSummary = {
    total_groups: groups.length,
    active: groups.filter((g) => g.status === 'active').length,
    triggered: groups.filter((g) => g.status === 'triggered').length,
    canceled: groups.filter((g) => g.status === 'canceled').length,
    pending: groups.filter((g) => g.status === 'pending').length,
  };

  // Filter groups by status
  const filteredGroups = useMemo(() => {
    if (statusFilter === 'all') return groups;
    return groups.filter(g => g.status === statusFilter);
  }, [groups, statusFilter]);
  const usage: OrderGroupUsage = {
    total_contracts_limit: groups.reduce((sum, g) => sum + g.contracts_limit, 0),
    total_matched_contracts: groups.reduce((sum, g) => sum + g.matched_contracts, 0),
    total_used_contracts: groups.reduce((sum, g) => sum + g.used_contracts, 0),
    total_filled_cost: groups.reduce((sum, g) => sum + g.filled_cost, 0),
    total_remaining_cost: groups.reduce((sum, g) => sum + g.remaining_cost, 0),
    overall_utilization_pct: groups.length > 0
      ? Math.round(
          groups.reduce((sum, g) => sum + (g.utilization_pct || 0), 0) / groups.length
        )
      : 0,
  };

  // Create new order group
  const handleCreateGroup = useCallback(async () => {
    if (!newGroupName.trim()) return;

    setActionLoading('create');
    setActionError(null);

    try {
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_ORDER_GROUP_CREATE}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newGroupName.trim(),
          max_cost_cents: newGroupLimit,
        }),
      });

      if (!response.ok) {
        const error = await response.text();
        throw new Error(error);
      }

      logUxEvent('order_group_create', newGroupName.trim(), { limit: newGroupLimit });
      setNewGroupName('');
      setIsCreating(false);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to create group');
    } finally {
      setActionLoading(null);
    }
  }, [newGroupName, newGroupLimit]);

  // Reset order group
  const handleResetGroup = useCallback(async (groupId: string) => {
    if (!window.confirm(`Reset order group ${groupId}? This will clear matched contracts.`)) {
      return;
    }

    setActionLoading(`reset-${groupId}`);
    setActionError(null);

    try {
      const response = await fetch(
        `${API_BASE_URL}${API_ENDPOINTS.KALSHI_ORDER_GROUP_RESET(groupId)}`,
        { method: 'PUT' }
      );

      if (!response.ok) {
        const error = await response.text();
        throw new Error(error);
      }
      logUxEvent('order_group_reset', groupId);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to reset group');
    } finally {
      setActionLoading(null);
    }
  }, []);

  // Delete order group
  const handleDeleteGroup = useCallback(async (groupId: string) => {
    if (!window.confirm(`Delete order group ${groupId}? This will cancel all orders in the group.`)) {
      return;
    }

    setActionLoading(`delete-${groupId}`);
    setActionError(null);

    try {
      const response = await fetch(
        `${API_BASE_URL}${API_ENDPOINTS.KALSHI_ORDER_GROUP_DELETE(groupId)}`,
        { method: 'DELETE' }
      );

      if (!response.ok) {
        const error = await response.text();
        throw new Error(error);
      }
      logUxEvent('order_group_delete', groupId);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to delete group');
    } finally {
      setActionLoading(null);
    }
  }, []);

  // Get status badge color
  const getStatusColor = (status: string): string => {
    switch (status) {
      case 'active':
        return '#22c55e'; // green
      case 'triggered':
        return '#ef4444'; // red
      case 'canceled':
        return '#6b7280'; // gray
      case 'pending':
        return '#f59e0b'; // amber
      default:
        return '#9ca3af'; // gray
    }
  };

  // Get utilization bar color
  const getUtilizationColor = (pct: number): string => {
    if (pct >= 90) return '#ef4444'; // red
    if (pct >= 75) return '#f59e0b'; // amber
    if (pct >= 50) return '#3b82f6'; // blue
    return '#22c55e'; // green
  };

  if (compact) {
    return (
      <div style={styles.compactContainer}>
        <div style={styles.compactHeader}>
          <span style={styles.title}>Order Groups</span>
          <span
            style={{
              ...styles.connectionBadge,
              backgroundColor: isConnected ? '#22c55e' : '#ef4444',
            }}
          >
            {isConnected ? 'Live' : 'Offline'}
          </span>
        </div>
        <div style={styles.compactStats}>
          <div style={styles.stat}>
            <span style={styles.statValue}>{summary.total_groups}</span>
            <span style={styles.statLabel}>Total</span>
          </div>
          <div style={styles.stat}>
            <span style={{ ...styles.statValue, color: '#22c55e' }}>{summary.active}</span>
            <span style={styles.statLabel}>Active</span>
          </div>
          <div style={styles.stat}>
            <span style={{ ...styles.statValue, color: '#ef4444' }}>{summary.triggered}</span>
            <span style={styles.statLabel}>Triggered</span>
          </div>
        </div>
        {alerts.length > 0 && (
          <div style={styles.alertBanner}>
            {alerts.length} alert{alerts.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    );
  }

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          <h3 style={styles.title}>Order Groups</h3>
          <span
            style={{
              ...styles.connectionBadge,
              backgroundColor: isConnected ? '#22c55e' : '#ef4444',
            }}
          >
            {isConnected ? 'Live' : reconnectAttempts > 0 ? `Reconnecting (${reconnectAttempts})` : 'Offline'}
          </span>
        </div>
        <button
          style={styles.createButton}
          onClick={() => setIsCreating(true)}
          disabled={isCreating || !!actionLoading}
        >
          + New Group
        </button>
      </div>

      {/* Error Display */}
      {(actionError || streamError) && (
        <div style={styles.errorBanner}>
          {actionError || streamError?.message}
          <button style={styles.dismissButton} onClick={() => setActionError(null)}>
            Dismiss
          </button>
        </div>
      )}

      {/* Create Form */}
      {isCreating && (
        <div style={styles.createForm}>
          <input
            type="text"
            placeholder="Group name..."
            value={newGroupName}
            onChange={(e) => setNewGroupName(e.target.value)}
            style={styles.input}
          />
          <input
            type="number"
            placeholder="Limit ($)"
            value={newGroupLimit}
            onChange={(e) => setNewGroupLimit(Number(e.target.value))}
            style={styles.input}
            min={1}
          />
          <div style={styles.formActions}>
            <button
              style={styles.submitButton}
              onClick={handleCreateGroup}
              disabled={!newGroupName.trim() || actionLoading === 'create'}
            >
              {actionLoading === 'create' ? 'Creating...' : 'Create'}
            </button>
            <button
              style={styles.cancelButton}
              onClick={() => {
                setIsCreating(false);
                setNewGroupName('');
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Summary Stats */}
      <div style={styles.summaryGrid}>
        <div style={styles.summaryCard} data-testid="order-group-summary-total">
          <span style={styles.summaryValue}>{summary.total_groups}</span>
          <span style={styles.summaryLabel}>Total Groups</span>
        </div>
        <div style={styles.summaryCard} data-testid="order-group-summary-active">
          <span style={{ ...styles.summaryValue, color: '#22c55e' }}>{summary.active}</span>
          <span style={styles.summaryLabel}>Active</span>
        </div>
        <div style={styles.summaryCard} data-testid="order-group-summary-triggered">
          <span style={{ ...styles.summaryValue, color: '#ef4444' }}>{summary.triggered}</span>
          <span style={styles.summaryLabel}>Triggered</span>
        </div>
        <div style={styles.summaryCard}>
          <span style={styles.summaryValue}>{usage.overall_utilization_pct}%</span>
          <span style={styles.summaryLabel}>Avg Utilization</span>
        </div>
      </div>

      {/* Status Filter */}
      <div style={styles.filterSection}>
        <span style={styles.filterLabel}>Filter:</span>
        <div style={styles.filterButtons}>
          {(['all', 'active', 'triggered', 'canceled', 'pending'] as const).map((status) => (
            <button
              key={status}
              onClick={() => setStatusFilter(status)}
              style={{
                ...styles.filterButton,
                ...(statusFilter === status ? styles.filterButtonActive : {}),
              }}
            >
              {status === 'all' ? 'All' : status.charAt(0).toUpperCase() + status.slice(1)}
              {status !== 'all' && (
                <span style={styles.filterCount}>
                  {summary[status as keyof OrderGroupSummary]}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Alerts */}
      {alerts.length > 0 && (
        <div style={styles.alertsSection}>
          <h4 style={styles.sectionTitle}>Alerts ({alerts.length})</h4>
          <div style={styles.alertsList}>
            {alerts.slice(0, 5).map((alert, idx) => (
              <div
                key={idx}
                style={{
                  ...styles.alertItem,
                  backgroundColor: alert.level === 'critical' ? '#fef2f2' : '#fffbeb',
                  borderLeftColor: alert.level === 'critical' ? '#ef4444' : '#f59e0b',
                }}
              >
                <span style={styles.alertMessage}>{alert.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Groups List */}
      <div style={styles.groupsSection}>
        <h4 style={styles.sectionTitle}>Groups ({filteredGroups.length})</h4>
        {filteredGroups.length === 0 ? (
          <div style={styles.emptyState}>
            {statusFilter === 'all' 
              ? 'No order groups found. Create one to get started.'
              : `No ${statusFilter} order groups found.`}
          </div>
        ) : (
          <div style={styles.groupsList}>
            {filteredGroups.map((group) => (
              <div
                key={group.order_group_id}
                style={styles.groupCard}
                role="button"
                tabIndex={0}
                onClick={() => onGroupSelect?.(group)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onGroupSelect?.(group);
                  }
                }}
              >
                <div style={styles.groupHeader}>
                  <div style={styles.groupInfo}>
                    <span style={styles.groupName}>{group.name || group.order_group_id}</span>
                    <span
                      style={{
                        ...styles.statusBadge,
                        backgroundColor: getStatusColor(group.status),
                      }}
                    >
                      {group.status}
                    </span>
                  </div>
                  <div style={styles.groupActions}>
                    {group.status === 'triggered' && (
                      <button
                        style={styles.actionButton}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleResetGroup(group.order_group_id);
                        }}
                        disabled={actionLoading === `reset-${group.order_group_id}`}
                      >
                        {actionLoading === `reset-${group.order_group_id}` ? '...' : 'Reset'}
                      </button>
                    )}
                    <button
                      style={{ ...styles.actionButton, color: '#ef4444' }}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteGroup(group.order_group_id);
                      }}
                      disabled={actionLoading === `delete-${group.order_group_id}`}
                    >
                      {actionLoading === `delete-${group.order_group_id}` ? '...' : 'Delete'}
                    </button>
                  </div>
                </div>

                {/* Utilization Bar */}
                <div style={styles.utilizationSection}>
                  <div style={styles.utilizationHeader}>
                    <span style={styles.utilizationLabel}>Utilization</span>
                    <span
                      style={{
                        ...styles.utilizationValue,
                        color: getUtilizationColor(group.utilization_pct),
                      }}
                    >
                      {group.utilization_pct}%
                    </span>
                  </div>
                  <div style={styles.progressBarBg}>
                    <div
                      style={{
                        ...styles.progressBarFill,
                        width: `${Math.min(group.utilization_pct, 100)}%`,
                        backgroundColor: getUtilizationColor(group.utilization_pct),
                      }}
                    />
                  </div>
                  <div style={styles.utilizationStats}>
                    <span>{group.used_contracts} / {group.contracts_limit} contracts</span>
                    <span>${(group.filled_cost / 100).toFixed(2)} filled</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// Styles
const styles: Record<string, React.CSSProperties> = {
  container: {
    backgroundColor: '#ffffff',
    borderRadius: '8px',
    padding: '16px',
    boxShadow: '0 1px 3px rgba(0, 0, 0, 0.1)',
    fontFamily: 'system-ui, -apple-system, sans-serif',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '16px',
  },
  headerLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
  title: {
    margin: 0,
    fontSize: '18px',
    fontWeight: 600,
    color: '#111827',
  },
  connectionBadge: {
    padding: '4px 8px',
    borderRadius: '4px',
    fontSize: '12px',
    fontWeight: 500,
    color: '#ffffff',
  },
  createButton: {
    padding: '8px 16px',
    backgroundColor: '#3b82f6',
    color: '#ffffff',
    border: 'none',
    borderRadius: '6px',
    fontSize: '14px',
    fontWeight: 500,
    cursor: 'pointer',
  },
  errorBanner: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '12px',
    backgroundColor: '#fef2f2',
    border: '1px solid #fecaca',
    borderRadius: '6px',
    color: '#dc2626',
    fontSize: '14px',
    marginBottom: '16px',
  },
  dismissButton: {
    padding: '4px 8px',
    backgroundColor: 'transparent',
    border: 'none',
    color: '#dc2626',
    cursor: 'pointer',
    fontSize: '12px',
  },
  createForm: {
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
    padding: '16px',
    backgroundColor: '#f9fafb',
    borderRadius: '6px',
    marginBottom: '16px',
  },
  input: {
    padding: '8px 12px',
    border: '1px solid #d1d5db',
    borderRadius: '6px',
    fontSize: '14px',
  },
  formActions: {
    display: 'flex',
    gap: '8px',
  },
  submitButton: {
    padding: '8px 16px',
    backgroundColor: '#22c55e',
    color: '#ffffff',
    border: 'none',
    borderRadius: '6px',
    fontSize: '14px',
    cursor: 'pointer',
  },
  cancelButton: {
    padding: '8px 16px',
    backgroundColor: '#f3f4f6',
    color: '#374151',
    border: 'none',
    borderRadius: '6px',
    fontSize: '14px',
    cursor: 'pointer',
  },
  summaryGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(4, 1fr)',
    gap: '12px',
    marginBottom: '16px',
  },
  summaryCard: {
    padding: '12px',
    backgroundColor: '#f9fafb',
    borderRadius: '6px',
    textAlign: 'center',
  },
  summaryValue: {
    display: 'block',
    fontSize: '24px',
    fontWeight: 700,
    color: '#111827',
  },
  summaryLabel: {
    display: 'block',
    fontSize: '12px',
    color: '#6b7280',
    marginTop: '4px',
  },
  alertsSection: {
    marginBottom: '16px',
  },
  sectionTitle: {
    margin: '0 0 12px 0',
    fontSize: '14px',
    fontWeight: 600,
    color: '#374151',
  },
  alertsList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  alertItem: {
    padding: '12px',
    borderRadius: '6px',
    borderLeftWidth: '4px',
    borderLeftStyle: 'solid',
  },
  alertMessage: {
    fontSize: '14px',
    color: '#1f2937',
  },
  groupsSection: {
    marginTop: '16px',
  },
  emptyState: {
    padding: '32px',
    textAlign: 'center',
    color: '#6b7280',
    fontSize: '14px',
  },
  groupsList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
  },
  groupCard: {
    padding: '16px',
    backgroundColor: '#f9fafb',
    borderRadius: '8px',
    border: '1px solid #e5e7eb',
    cursor: 'pointer',
    transition: 'box-shadow 0.2s',
  },
  groupHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '12px',
  },
  groupInfo: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
  groupName: {
    fontWeight: 600,
    fontSize: '14px',
    color: '#111827',
  },
  statusBadge: {
    padding: '2px 8px',
    borderRadius: '4px',
    fontSize: '12px',
    fontWeight: 500,
    color: '#ffffff',
    textTransform: 'uppercase',
  },
  groupActions: {
    display: 'flex',
    gap: '8px',
  },
  actionButton: {
    padding: '4px 12px',
    backgroundColor: '#ffffff',
    border: '1px solid #d1d5db',
    borderRadius: '4px',
    fontSize: '12px',
    cursor: 'pointer',
  },
  utilizationSection: {
    marginTop: '8px',
  },
  utilizationHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    marginBottom: '4px',
  },
  utilizationLabel: {
    fontSize: '12px',
    color: '#6b7280',
  },
  utilizationValue: {
    fontSize: '12px',
    fontWeight: 600,
  },
  progressBarBg: {
    height: '8px',
    backgroundColor: '#e5e7eb',
    borderRadius: '4px',
    overflow: 'hidden',
  },
  progressBarFill: {
    height: '100%',
    borderRadius: '4px',
    transition: 'width 0.3s ease',
  },
  utilizationStats: {
    display: 'flex',
    justifyContent: 'space-between',
    marginTop: '8px',
    fontSize: '12px',
    color: '#6b7280',
  },
  // Compact view styles
  compactContainer: {
    padding: '12px',
    backgroundColor: '#ffffff',
    borderRadius: '8px',
    boxShadow: '0 1px 3px rgba(0, 0, 0, 0.1)',
  },
  compactHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '12px',
  },
  compactStats: {
    display: 'flex',
    gap: '16px',
  },
  stat: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
  },
  statValue: {
    fontSize: '20px',
    fontWeight: 700,
    color: '#111827',
  },
  statLabel: {
    fontSize: '12px',
    color: '#6b7280',
  },
  alertBanner: {
    marginTop: '12px',
    padding: '8px',
    backgroundColor: '#fef3c7',
    borderRadius: '4px',
    fontSize: '12px',
    color: '#92400e',
    textAlign: 'center',
  },
  filterSection: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    marginBottom: '12px',
    padding: '8px',
    backgroundColor: '#f9fafb',
    borderRadius: '6px',
  },
  filterLabel: {
    fontSize: '12px',
    fontWeight: 500,
    color: '#374151',
  },
  filterButtons: {
    display: 'flex',
    gap: '4px',
    flexWrap: 'wrap',
  },
  filterButton: {
    padding: '4px 8px',
    fontSize: '11px',
    backgroundColor: '#ffffff',
    border: '1px solid #d1d5db',
    borderRadius: '4px',
    cursor: 'pointer',
    color: '#374151',
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
  },
  filterButtonActive: {
    backgroundColor: '#3b82f6',
    color: '#ffffff',
    borderColor: '#3b82f6',
  },
  filterCount: {
    fontSize: '10px',
    padding: '1px 4px',
    backgroundColor: '#e5e7eb',
    borderRadius: '3px',
    color: '#374151',
  },
};

export default OrderGroupPanel;
