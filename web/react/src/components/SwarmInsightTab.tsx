/**
 * SwarmInsightTab - Composition of existing Kalshi components
 * for a unified operator view of agent decisions, orders, and positions
 */

import { Icon } from '../ui/icons';
import KalshiModeBadge from './KalshiModeBadge';
import KalshiReconciliationBadge from './KalshiReconciliationBadge';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import type { KalshiPosition, KalshiOrder, KalshiFill } from '../types/kalshi';

interface SwarmInsightTabProps {
  // Grid status data (already available in parent)
  status: any;
  gridRunning: boolean;
  isLive: boolean;
  portfolio: any;
  // session: any; // Available but not used in current implementation
}

export default function SwarmInsightTab({ 
  status, 
  gridRunning, 
  isLive, 
  portfolio 
}: SwarmInsightTabProps) {
  // Reuse existing data hooks from Portfolio
  const posResult = useApiData<{ positions: KalshiPosition[] }>(API_ENDPOINTS.KALSHI_POSITIONS, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD
  });
  const ordResult = useApiData<{ orders: KalshiOrder[] }>(API_ENDPOINTS.KALSHI_ORDERS, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD
  });
  const fillResult = useApiData<{ fills: KalshiFill[] }>(API_ENDPOINTS.KALSHI_FILLS, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD
  });

  const positions = posResult.data?.positions || [];
  const orders = ordResult.data?.orders || [];
  const fills = fillResult.data?.fills || [];

  // Get recent items (last 20 for performance)
  const recentOrders = orders.slice(-20).reverse();
  const recentFills = fills.slice(-20).reverse();

  // Calculate summary metrics
  const totalPnL = positions.reduce((sum, p) => sum + (p.unrealized_pnl + p.realized_pnl), 0);
  const activePositions = positions.filter(p => p.size > 0).length;
  const openOrders = orders.filter(o => o.status === 'resting').length;

  return (
    <div className="space-y-6">
      {/* Header Strip - Reuse existing components */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div className="flex items-center gap-3">
            <h3 className="text-lg font-semibold text-white">Swarm Insight</h3>
            <div className="flex items-center gap-2">
              <KalshiModeBadge />
              <span className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-semibold ${
                isLive ? 'bg-red-500/30 text-red-300 border border-red-500/50' : 'bg-amber-500/20 text-amber-400'
              }`}>
                {isLive ? '🔴 LIVE' : '📄 PAPER'}
              </span>
              <span className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full ${
                gridRunning ? 'bg-green-500/20 text-green-400' : 'bg-gray-500/20 text-gray-400'
              }`}>
                Grid: {gridRunning ? 'Running' : 'Stopped'}
              </span>
              {portfolio?.kill_switch_active && (
                <span className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-red-500/20 text-red-400">
                  <Icon name="alert" size={10} className="w-2.5 h-2.5" />
                  Kill Switch Active
                </span>
              )}
            </div>
          </div>
          <KalshiReconciliationBadge compact={true} />
        </div>
      </div>

      {/* Three Column Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Agent Decisions */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
          <h4 className="text-sm font-semibold text-white mb-3">Agent Decisions</h4>
          <div className="space-y-2">
            {/* This would reuse the agent table from Grid view */}
            {/* For now, showing placeholder with existing data structure */}
            {status?.agent_count ? (
              <div className="text-xs text-gray-400">
                {status.agent_count} agents active in matrix
              </div>
            ) : (
              <div className="text-xs text-gray-500">No agent data available</div>
            )}
            {/* TODO: Import and reuse agent decision table component */}
          </div>
        </div>

        {/* Center: Orders Feed */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
          <h4 className="text-sm font-semibold text-white mb-3">Recent Orders</h4>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {recentOrders.length === 0 ? (
              <div className="text-xs text-gray-500 text-center py-4">No recent orders</div>
            ) : (
              recentOrders.map((order) => (
                <div key={order.order_id} className="flex items-center justify-between text-xs p-2 bg-slate-800/50 rounded">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-gray-400">{order.ticker}</span>
                    <span className={`px-1.5 py-0.5 rounded ${
                      order.side === 'yes' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                    }`}>
                      {(order.side ?? 'yes').toUpperCase()}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-gray-300">{order.size}@{order.price ? (order.price * 100).toFixed(0) + '¢' : 'MKT'}</span>
                    {(order.initiated_by || order.agent_name) && (
                      <span className="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 text-[10px]">
                        {order.initiated_by || order.agent_name}
                      </span>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Right: Positions + Risk Snapshot */}
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
          <h4 className="text-sm font-semibold text-white mb-3">Positions & Risk</h4>
          
          {/* Reconciliation Badge */}
          <div className="mb-4">
            <KalshiReconciliationBadge />
          </div>

          {/* Summary Metrics */}
          <div className="space-y-3">
            <div className="flex justify-between text-xs">
              <span className="text-gray-400">Net PnL:</span>
              <span className={`font-medium ${totalPnL >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                ${(totalPnL ?? 0).toFixed(2)}
              </span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-gray-400">Positions:</span>
              <span className="text-white">{activePositions}</span>
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-gray-400">Open Orders:</span>
              <span className="text-white">{openOrders}</span>
            </div>
            {portfolio && (
              <>
                <div className="flex justify-between text-xs">
                  <span className="text-gray-400">Margin Util:</span>
                  <span className="text-white">{((portfolio.margin_utilization || 0) * 100).toFixed(1)}%</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-gray-400">Drawdown:</span>
                  <span className="text-white">{((portfolio.drawdown_pct || 0) * 100).toFixed(1)}%</span>
                </div>
              </>
            )}
          </div>

          {/* Recent Fills */}
          <div className="mt-4 pt-4 border-t border-slate-700">
            <h5 className="text-xs font-semibold text-gray-300 mb-2">Recent Fills</h5>
            <div className="space-y-1 max-h-32 overflow-y-auto">
              {recentFills.slice(0, 5).map((fill) => (
                <div key={fill.trade_id} className="flex items-center justify-between text-xs p-1 bg-slate-800/30 rounded">
                  <span className="font-mono text-gray-500">{fill.ticker}</span>
                  <div className="flex items-center gap-1">
                    <span className={`px-1 py-0.5 rounded ${
                      fill.side === 'yes' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
                    }`}>
                      {fill.side}
                    </span>
                    <span className="text-gray-300">{fill.size}@{((fill.price ?? 0) * 100).toFixed(0)}¢</span>
                    {(fill.initiated_by || fill.agent_name) && (
                      <span className="px-1 py-0.5 rounded bg-blue-500/20 text-blue-400 text-[9px]">
                        {(fill.initiated_by || fill.agent_name)?.slice(0, 3)}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Optional: Bottom mini-timeline placeholder */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
        <h4 className="text-sm font-semibold text-white mb-3">Activity Timeline</h4>
        <div className="text-xs text-gray-500 text-center py-4">
          Timeline view available in Phase 2.5 with pnl_delta_cents integration
        </div>
      </div>
    </div>
  );
}
