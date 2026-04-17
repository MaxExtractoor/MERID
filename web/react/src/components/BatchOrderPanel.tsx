/**
 * BatchOrderPanel.tsx — Batch order placement with order group assignment.
 *
 * Provides:
 * - Multi-order entry (ticker, side, size, price)
 * - Order group assignment (select existing or create new)
 * - Post-only toggle per order
 * - Batch submission with progress tracking
 * - Real-time order status updates
 *
 * Usage:
 *   <BatchOrderPanel onOrdersPlaced={() => refetchPositions()} />
 */

import React, { useState, useCallback, useMemo } from 'react';
import { 
  Plus, Trash2, Send, Loader2, AlertTriangle, 
  CheckCircle, Package, Layers 
} from 'lucide-react';
import { API_BASE_URL, API_ENDPOINTS, CHART_COLORS, AUTH_TOKEN_KEY } from '../config/constants';
import { logUxEvent } from '../utils/uxTelemetry';

export interface BatchOrderItem {
  id: string;
  ticker: string;
  side: 'yes' | 'no';
  action: 'buy' | 'sell';
  count: number;
  price_cents: number | null;
  post_only: boolean;
  order_group_id?: string;
}

interface OrderGroup {
  order_group_id: string;
  name: string;
  status: 'active' | 'triggered' | 'canceled' | 'pending';
  contracts_limit: number;
  used_contracts: number;
  utilization_pct: number;
}

interface BatchOrderPanelProps {
  /** Callback when batch is successfully submitted */
  onOrdersPlaced?: () => void;
  /** Initial orders to pre-fill */
  initialOrders?: BatchOrderItem[];
  /** Default order group to assign */
  defaultOrderGroupId?: string;
  /** Available order groups for selection */
  availableGroups?: OrderGroup[];
  /** Show compact view */
  compact?: boolean;
}

/**
 * Batch Order Placement Panel
 * 
 * Allows traders to submit multiple orders simultaneously,
 * with optional assignment to order groups for risk management.
 */
export function BatchOrderPanel({
  onOrdersPlaced,
  initialOrders,
  defaultOrderGroupId,
  availableGroups = [],
  compact = false,
}: BatchOrderPanelProps): JSX.Element {
  const [orders, setOrders] = useState<BatchOrderItem[]>(
    initialOrders || [createEmptyOrder(defaultOrderGroupId)]
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null);
  const [selectedGroupId, setSelectedGroupId] = useState<string>(
    defaultOrderGroupId || 'none'
  );

  // Create empty order template
  function createEmptyOrder(groupId?: string): BatchOrderItem {
    return {
      id: Math.random().toString(36).substring(2, 9),
      ticker: '',
      side: 'yes',
      action: 'buy',
      count: 1,
      price_cents: 50,
      post_only: false,
      order_group_id: groupId,
    };
  }

  // Add new order row
  const addOrder = useCallback(() => {
    setOrders(prev => [...prev, createEmptyOrder(
      selectedGroupId !== 'none' ? selectedGroupId : undefined
    )]);
    logUxEvent('batch_order_add_row');
  }, [selectedGroupId]);

  // Remove order row
  const removeOrder = useCallback((id: string) => {
    setOrders(prev => prev.filter(o => o.id !== id));
    logUxEvent('batch_order_remove_row');
  }, []);

  // Update order field
  const updateOrder = useCallback((id: string, field: keyof BatchOrderItem, value: string | number | boolean | null | undefined) => {
    setOrders(prev => prev.map(o => 
      o.id === id ? { ...o, [field]: value } : o
    ));
  }, []);

  // Apply group selection to all orders
  const applyGroupToAll = useCallback((groupId: string) => {
    setSelectedGroupId(groupId);
    setOrders(prev => prev.map(o => ({
      ...o,
      order_group_id: groupId === 'none' ? undefined : groupId,
    })));
  }, []);

  // Validate all orders
  const validationErrors = useMemo(() => {
    const errors: Record<string, string> = {};
    orders.forEach((order) => {
      if (!order.ticker.trim()) {
        errors[order.id] = 'Ticker required';
      } else if (order.count <= 0) {
        errors[order.id] = 'Count must be > 0';
      } else if (order.price_cents !== null && (order.price_cents < 1 || order.price_cents > 99)) {
        errors[order.id] = 'Price must be 1-99¢';
      }
    });
    return errors;
  }, [orders]);

  const isValid = Object.keys(validationErrors).length === 0;

  // Submit batch orders
  const handleSubmit = useCallback(async () => {
    if (!isValid || orders.length === 0) return;

    setIsSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(null);

    try {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      
      // Build batch request
      const batchData = {
        orders: orders.map(o => ({
          ticker: o.ticker.trim().toUpperCase(),
          side: o.side,
          action: o.action,
          count: o.count,
          price_cents: o.price_cents,
          order_type: o.price_cents ? 'limit' : 'market',
          post_only: o.post_only,
          order_group_id: o.order_group_id,
        })),
        order_group_id: selectedGroupId !== 'none' ? selectedGroupId : undefined,
        self_trade_prevention_type: 'taker_at_cross',
      };

      const response = await fetch(
        `${API_BASE_URL}${API_ENDPOINTS.KALSHI_BATCH_ORDERS}`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
          },
          body: JSON.stringify(batchData),
        }
      );

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Batch order failed (${response.status})`);
      }

      const result = await response.json();
      
      logUxEvent('batch_order_submit', 'success', { 
        count: orders.length, 
        group_id: selectedGroupId,
        contracts: orders.reduce((sum, o) => sum + o.count, 0)
      });
      setSubmitSuccess(`Placed ${result.placed?.length || orders.length} orders successfully`);
      onOrdersPlaced?.();
      
      // Clear form after success
      setOrders([createEmptyOrder(selectedGroupId !== 'none' ? selectedGroupId : undefined)]);
    } catch (err) {
      logUxEvent('batch_order_submit', 'error', { error: err instanceof Error ? err.message : 'Unknown' });
      setSubmitError(err instanceof Error ? err.message : 'Batch submission failed');
    } finally {
      setIsSubmitting(false);
    }
  }, [orders, isValid, selectedGroupId, onOrdersPlaced]);

  // Compact view
  if (compact) {
    return (
      <div style={styles.compactContainer}>
        <div style={styles.compactHeader}>
          <Package className="w-4 h-4" />
          <span style={styles.compactTitle}>Batch Orders</span>
          <span style={styles.compactCount}>{orders.length} pending</span>
        </div>
        <button type="button"
          style={styles.compactButton}
          onClick={() => { /* Expand to full view */ }}
          disabled={isSubmitting}
        >
          {isSubmitting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Layers className="w-3 h-3" />}
          Open Batch Panel
        </button>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          <Layers className="w-5 h-5 text-orange-400" />
          <h3 style={styles.title}>Batch Order Placement</h3>
        </div>
        <span style={styles.orderCount}>{orders.length} orders</span>
      </div>

      {/* Global Group Selector */}
      <div style={styles.globalGroupSection}>
        <label htmlFor="global-group-select" style={styles.label}>Assign to Order Group (all orders):</label>
        <select
          aria-label="Order group for all orders"
          id="global-group-select"
          value={selectedGroupId}
          onChange={(e) => applyGroupToAll(e.target.value)}
          style={styles.select}
          title="Select order group for all orders"
        >
          <option value="none">— No Group —</option>
          {availableGroups.map(g => (
            <option key={g.order_group_id} value={g.order_group_id}>
              {g.name || g.order_group_id} 
              ({g.utilization_pct}% used, {g.status})
            </option>
          ))}
        </select>
        {selectedGroupId !== 'none' && (
          <span style={styles.groupBadge}>
            Group selected
          </span>
        )}
      </div>

      {/* Status Messages */}
      {submitError && (
        <div style={styles.errorBanner}>
          <AlertTriangle className="w-4 h-4" />
          {submitError}
        </div>
      )}
      {submitSuccess && (
        <div style={styles.successBanner}>
          <CheckCircle className="w-4 h-4" />
          {submitSuccess}
        </div>
      )}

      {/* Order List */}
      <div style={styles.orderList}>
        {orders.map((order, index) => (
          <div 
            key={order.id} 
            style={{
              ...styles.orderRow,
              borderColor: validationErrors[order.id] ? CHART_COLORS.RED : CHART_COLORS.GRAY_200,
            }}
          >
            {/* Row Number */}
            <span style={styles.rowNumber}>#{index + 1}</span>

            {/* Ticker */}
            <input
              aria-label="Order ticker symbol"
              type="text"
              placeholder="Ticker (e.g., KXBTC)"
              value={order.ticker}
              onChange={(e) => updateOrder(order.id, 'ticker', e.target.value)}
              style={{
                ...styles.input,
                width: '120px',
                borderColor: validationErrors[order.id] && !order.ticker ? CHART_COLORS.RED : undefined,
              }}
            />

            {/* Side */}
            <select
              aria-label="Order side"
              value={order.side}
              onChange={(e) => updateOrder(order.id, 'side', e.target.value)}
              style={{
                ...styles.select,
                width: '70px',
                backgroundColor: order.side === 'yes' ? CHART_COLORS.GREEN_50 : CHART_COLORS.RED_100,
                color: order.side === 'yes' ? CHART_COLORS.GREEN_800 : CHART_COLORS.RED_800,
              }}
              title="Select side (YES/NO)"
            >
              <option value="yes">YES</option>
              <option value="no">NO</option>
            </select>

            {/* Action */}
            <select
              aria-label="Order action"
              value={order.action}
              onChange={(e) => updateOrder(order.id, 'action', e.target.value)}
              style={{ ...styles.select, width: '80px' }}
              title="Select action (Buy/Sell)"
            >
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
            </select>

            {/* Count */}
            <input
              aria-label="Order quantity"
              type="number"
              min={1}
              placeholder="Qty"
              value={order.count}
              onChange={(e) => updateOrder(order.id, 'count', parseInt(e.target.value) || 0)}
              style={{ ...styles.input, width: '70px' }}
            />

            {/* Price */}
            <div style={styles.priceInput}>
              <input
                aria-label="Order price in cents"
                type="number"
                min={1}
                max={99}
                placeholder="Price"
                value={order.price_cents || ''}
                onChange={(e) => updateOrder(order.id, 'price_cents', parseInt(e.target.value) || null)}
                style={{ ...styles.input, width: '60px' }}
              />
              <span style={styles.centsLabel}>¢</span>
            </div>

            {/* Post-Only Toggle */}
            <label style={styles.postOnlyLabel}>
              <input
                type="checkbox"
                aria-label="Post-only order"
                checked={order.post_only}
                onChange={(e) => updateOrder(order.id, 'post_only', e.target.checked)}
                style={styles.checkbox}
              />
              <span style={styles.postOnlyText}>Post</span>
            </label>

            {/* Per-order Group Override */}
            <select
              aria-label="Order group override"
              value={order.order_group_id || 'inherit'}
              onChange={(e) => updateOrder(order.id, 'order_group_id', 
                e.target.value === 'inherit' ? undefined : e.target.value
              )}
              style={{ ...styles.select, width: '100px', fontSize: '11px' }}
              title="Select order group (or inherit from global)"
            >
              <option value="inherit">Inherit</option>
              {availableGroups.map(g => (
                <option key={g.order_group_id} value={g.order_group_id}>
                  {g.name || g.order_group_id}
                </option>
              ))}
            </select>

            {/* Remove Button */}
            <button type="button"
              onClick={() => removeOrder(order.id)}
              disabled={orders.length === 1}
              style={{
                ...styles.removeButton,
                opacity: orders.length === 1 ? 0.3 : 1,
              }}
              title="Remove order"
            >
              <Trash2 className="w-4 h-4" />
            </button>

            {/* Validation Error */}
            {validationErrors[order.id] && (
              <div style={styles.rowError}>{validationErrors[order.id]}</div>
            )}
          </div>
        ))}
      </div>

      {/* Actions */}
      <div style={styles.actions}>
        <button type="button"
          onClick={addOrder}
          style={styles.addButton}
          disabled={isSubmitting}
        >
          <Plus className="w-4 h-4" />
          Add Order
        </button>

        <div style={styles.rightActions}>
          {/* Total Summary */}
          <span style={styles.summary}>
            {orders.length} orders • {orders.reduce((sum, o) => sum + o.count, 0)} contracts
          </span>

          <button type="button"
            onClick={handleSubmit}
            disabled={!isValid || isSubmitting || orders.length === 0}
            style={{
              ...styles.submitButton,
              opacity: !isValid || isSubmitting ? 0.5 : 1,
            }}
          >
            {isSubmitting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
            {isSubmitting ? 'Submitting...' : 'Place Batch'}
          </button>
        </div>
      </div>
    </div>
  );
}

// Styles
const styles: Record<string, React.CSSProperties> = {
  container: {
    backgroundColor: CHART_COLORS.WHITE,
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
    paddingBottom: '12px',
    borderBottom: `1px solid ${CHART_COLORS.GRAY_200}`,
  },
  headerLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  title: {
    margin: 0,
    fontSize: '16px',
    fontWeight: 600,
    color: CHART_COLORS.GRAY_900,
  },
  orderCount: {
    fontSize: '12px',
    color: CHART_COLORS.GRAY_500,
    backgroundColor: CHART_COLORS.GRAY_100,
    padding: '4px 8px',
    borderRadius: '4px',
  },
  globalGroupSection: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    marginBottom: '16px',
    padding: '12px',
    backgroundColor: CHART_COLORS.GRAY_50,
    borderRadius: '6px',
  },
  label: {
    fontSize: '13px',
    color: CHART_COLORS.GRAY_700,
    fontWeight: 500,
  },
  select: {
    padding: '6px 10px',
    border: `1px solid ${CHART_COLORS.GRAY_300}`,
    borderRadius: '6px',
    fontSize: '13px',
    backgroundColor: CHART_COLORS.WHITE,
    cursor: 'pointer',
  },

  errorBanner: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '10px 12px',
    backgroundColor: CHART_COLORS.RED_50,
    border: `1px solid ${CHART_COLORS.RED_200}`,
    borderRadius: '6px',
    color: CHART_COLORS.RED_600,
    fontSize: '13px',
    marginBottom: '12px',
  },

  successBanner: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '10px 12px',
    backgroundColor: CHART_COLORS.GREEN_50B,
    border: `1px solid ${CHART_COLORS.GREEN_200}`,
    borderRadius: '6px',
    color: CHART_COLORS.GREEN_600,
    fontSize: '13px',
    marginBottom: '12px',
  },

  input: {
    padding: '6px 8px',
    border: `1px solid ${CHART_COLORS.GRAY_300}`,
    borderRadius: '6px',
    fontSize: '13px',
    backgroundColor: CHART_COLORS.WHITE,
  },

  postOnlyLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
    cursor: 'pointer',
    padding: '4px 8px',
    backgroundColor: CHART_COLORS.WHITE,
    borderRadius: '4px',
    border: `1px solid ${CHART_COLORS.GRAY_300}`,
  },

  addButton: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '8px 12px',
    backgroundColor: CHART_COLORS.GRAY_100,
    border: `1px solid ${CHART_COLORS.GRAY_300}`,
    borderRadius: '6px',
    fontSize: '13px',
    color: CHART_COLORS.GRAY_700,
    cursor: 'pointer',
  },

  compactButton: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '6px',
    width: '100%',
    padding: '8px',
    backgroundColor: CHART_COLORS.WHITE,
    border: `1px solid ${CHART_COLORS.GRAY_300}`,
    borderRadius: '6px',
    fontSize: '12px',
    color: CHART_COLORS.GRAY_700,
    cursor: 'pointer',
  },
};

export default BatchOrderPanel;
