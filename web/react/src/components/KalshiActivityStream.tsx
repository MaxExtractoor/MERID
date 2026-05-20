/**
 * KalshiActivityStream — Live Activity Stream (Phase 3)
 *
 * Shows real-time Kalshi events and backend actions.
 * 
 * Event types:
 * - Fills: Trade executions with PnL
 * - Orders: Order status changes
 * - Risk alerts: Risk limit breaches
 * - Grid errors: Agent errors
 * - System events: Kill switch, execution gate changes
 */

import { useState, useMemo } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Clock,
  Shield,
  Filter,
} from '../ui/icons';
import { useKalshiUIState } from '../hooks/useKalshiUIState';
import { formatCurrency, fmtTimestamp } from '../utils/formatters';
import type { FillSummary, OrderSummary, RiskAlertSummary, GridErrorSummary } from '../types/kalshiUIState';

type EventType = 'all' | 'fills' | 'orders' | 'alerts' | 'errors' | 'system';

interface ActivityEvent {
  id: string;
  type: 'fill' | 'order' | 'alert' | 'error' | 'system';
  timestamp: string;
  data: FillSummary | OrderSummary | RiskAlertSummary | GridErrorSummary | any;
}

// ── Sub-Components ─────────────────────────────────────────────────────────────

function EventIcon({ type, data }: { type: string; data: any }) {
  switch (type) {
    case 'fill':
      return data.pnl_usd >= 0 
        ? <CheckCircle className="w-4 h-4 text-green-400" />
        : <XCircle className="w-4 h-4 text-red-400" />;
    case 'order':
      return <Clock className="w-4 h-4 text-blue-400" />;
    case 'alert':
      return data.level === 'critical' 
        ? <AlertTriangle className="w-4 h-4 text-red-400" />
        : <AlertTriangle className="w-4 h-4 text-amber-400" />;
    case 'error':
      return <XCircle className="w-4 h-4 text-red-400" />;
    case 'system':
      return <Shield className="w-4 h-4 text-purple-400" />;
    default:
      return <Activity className="w-4 h-4 text-slate-400" />;
  }
}

function EventContent({ type, data }: { type: string; data: any }) {
  switch (type) {
    case 'fill':
      return (
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-slate-200">{data.ticker}</span>
            <span className={`text-xs ${data.pnl_usd >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {formatCurrency(data.pnl_usd)}
            </span>
          </div>
          <div className="text-xs text-slate-400">
            {data.contracts} contracts @ {data.price_cents}¢
          </div>
        </div>
      );
    case 'order':
      return (
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-slate-200">{data.ticker}</span>
            <span className="text-xs text-slate-400 uppercase">
              {data.action} {data.side}
            </span>
          </div>
          <div className="text-xs text-slate-400">
            {data.contracts} contracts @ {data.limit_price_cents}¢ ({data.status})
          </div>
        </div>
      );
    case 'alert':
      return (
        <div className="space-y-1">
          <div className="font-medium text-slate-200">{data.category}</div>
          <div className="text-xs text-slate-400">{data.message}</div>
        </div>
      );
    case 'error':
      return (
        <div className="space-y-1">
          <div className="font-medium text-slate-200">{data.agent_id}</div>
          <div className="text-xs text-slate-400 line-clamp-2">{data.error}</div>
        </div>
      );
    case 'system':
      return (
        <div className="space-y-1">
          <div className="font-medium text-slate-200">{data.event_type || 'System Event'}</div>
          <div className="text-xs text-slate-400">{data.message}</div>
        </div>
      );
    default:
      return <div className="text-slate-400">Unknown event type</div>;
  }
}

// ── Main Component ───────────────────────────────────────────────────────────────

export default function KalshiActivityStream() {
  const { state, loading, error } = useKalshiUIState({ pollingInterval: 10000 });
  const [filter, setFilter] = useState<EventType>('all');

  // Aggregate events from state
  const events = useMemo(() => {
    if (!state) return [];

    const aggregated: ActivityEvent[] = [];

    // Add fills
    state.markets.recent_fills.forEach((fill) => {
      aggregated.push({
        id: fill.fill_id,
        type: 'fill',
        timestamp: fill.filled_at,
        data: fill,
      });
    });

    // Add orders
    state.markets.recent_orders.forEach((order) => {
      aggregated.push({
        id: order.order_id,
        type: 'order',
        timestamp: order.created_at,
        data: order,
      });
    });

    // Add alerts
    state.risk.recent_alerts.forEach((alert) => {
      aggregated.push({
        id: alert.id,
        type: 'alert',
        timestamp: alert.timestamp,
        data: alert,
      });
    });

    // Add grid errors
    state.grid.recent_errors.forEach((err, idx) => {
      aggregated.push({
        id: `error-${idx}`,
        type: 'error',
        timestamp: err.timestamp,
        data: err,
      });
    });

    // Sort by timestamp descending
    return aggregated.sort((a, b) => 
      new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
    );
  }, [state]);

  // Filter events
  const filteredEvents = useMemo(() => {
    if (filter === 'all') return events;
    return events.filter((e) => e.type === filter);
  }, [events, filter]);

  if (loading && !state) {
    return (
      <div className="bg-slate-900/80 rounded-xl border border-slate-800 p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-blue-400" />
          <span className="text-sm font-semibold text-slate-200">Activity Stream</span>
        </div>
        <div className="space-y-2">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="bg-slate-800/50 rounded p-3 animate-pulse">
              <div className="h-4 bg-slate-700 rounded w-32 mb-2" />
              <div className="h-3 bg-slate-700 rounded w-48" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-900/20 border border-red-800 rounded-xl p-4">
        <div className="flex items-center gap-2 text-red-400">
          <AlertTriangle className="w-5 h-5" />
          <span className="font-medium">Error loading activity</span>
        </div>
        <p className="text-sm text-red-300 mt-2">{error}</p>
      </div>
    );
  }

  const eventCounts = {
    all: events.length,
    fills: events.filter((e) => e.type === 'fill').length,
    orders: events.filter((e) => e.type === 'order').length,
    alerts: events.filter((e) => e.type === 'alert').length,
    errors: events.filter((e) => e.type === 'error').length,
    system: events.filter((e) => e.type === 'system').length,
  };

  return (
    <div className="bg-slate-900/80 rounded-xl border border-slate-800 p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-blue-400" />
          <span className="text-sm font-semibold text-slate-200">Activity Stream</span>
        </div>
        <div className="flex items-center gap-1">
          <Filter className="w-3 h-3 text-slate-500" />
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as EventType)}
            className="text-xs bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-300 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="all">All ({eventCounts.all})</option>
            <option value="fills">Fills ({eventCounts.fills})</option>
            <option value="orders">Orders ({eventCounts.orders})</option>
            <option value="alerts">Alerts ({eventCounts.alerts})</option>
            <option value="errors">Errors ({eventCounts.errors})</option>
            <option value="system">System ({eventCounts.system})</option>
          </select>
        </div>
      </div>

      {/* Event List */}
      {filteredEvents.length === 0 ? (
        <div className="text-center py-8">
          <Activity className="w-8 h-8 text-slate-600 mx-auto mb-2" />
          <p className="text-sm text-slate-500">No recent activity</p>
        </div>
      ) : (
        <div className="space-y-2 max-h-96 overflow-y-auto">
          {filteredEvents.map((event) => (
            <div
              key={event.id}
              className="bg-slate-800/50 rounded-lg p-3 hover:bg-slate-800 transition-colors"
            >
              <div className="flex items-start gap-3">
                <EventIcon type={event.type} data={event.data} />
                <div className="flex-1 min-w-0">
                  <EventContent type={event.type} data={event.data} />
                  <div className="text-xs text-slate-500 mt-1">
                    {fmtTimestamp(event.timestamp)}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
