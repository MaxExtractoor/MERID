/**
 * KalshiDetailDrawer — Detail Drawer (Phase 4)
 *
 * Progressive disclosure component for detailed information.
 * Shows details for selected market, order, or trade.
 * 
 * Design principles:
 * - Slide-in drawer from right
 * - Lazy-loaded detail data
 * - Close button
 * - Responsive
 */

import { useState, useEffect } from 'react';
import { X, ChevronRight, DollarSign, Activity, Clock } from '../ui/icons';
import { useKalshiDetail } from '../hooks/useKalshiUIState';
import { formatCurrency, fmtTimestamp, formatPercent } from '../utils/formatters';
import { API_ENDPOINTS } from '../config/constants';

type DetailType = 'market' | 'order' | 'trade' | 'agent' | null;

interface KalshiDetailDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  type: DetailType;
  id: string | null;
}

// ── Sub-Components ─────────────────────────────────────────────────────────────

function MarketDetail({ ticker }: { ticker: string }) {
  const { data, loading, error } = useKalshiDetail<any>(
    ticker ? API_ENDPOINTS.KALSHI_UI_STATE_MARKET_DETAIL(ticker) : null,
    !!ticker
  );

  if (loading) {
    return (
      <div className="p-6 space-y-4">
        <div className="h-6 bg-slate-800 rounded w-1/2 animate-pulse" />
        <div className="h-4 bg-slate-800 rounded w-1/3 animate-pulse" />
        <div className="space-y-2 pt-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-4 bg-slate-800 rounded animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="p-6 text-center">
        <p className="text-sm text-slate-400">Failed to load market details</p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h3 className="text-lg font-bold text-slate-100">{data.title || ticker}</h3>
        <p className="text-sm text-slate-400">{data.subtitle || ''}</p>
      </div>

      {/* Pricing */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-slate-800/50 rounded-lg p-3">
          <div className="text-xs text-slate-400 mb-1">Yes Price</div>
          <div className="text-lg font-bold text-green-400">{data.yes_ask}¢</div>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-3">
          <div className="text-xs text-slate-400 mb-1">No Price</div>
          <div className="text-lg font-bold text-red-400">{data.no_ask}¢</div>
        </div>
      </div>

      {/* Market Stats */}
      <div className="space-y-2">
        <div className="flex justify-between text-sm">
          <span className="text-slate-400">Spread</span>
          <span className="text-slate-200">{data.spread_cents}¢</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-slate-400">Mid Price</span>
          <span className="text-slate-200">{data.mid_cents}¢</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-slate-400">Volume (24h)</span>
          <span className="text-slate-200">{data.volume_24h?.toLocaleString() || 'N/A'}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-slate-400">Open Interest</span>
          <span className="text-slate-200">{data.open_interest?.toLocaleString() || 'N/A'}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-slate-400">Expiry</span>
          <span className="text-slate-200">{fmtTimestamp(data.expiration_time)}</span>
        </div>
      </div>

      {/* Orderbook */}
      {data.orderbook && data.orderbook.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-200 mb-2">Orderbook</h4>
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {data.orderbook.slice(0, 10).map((level: any, idx: number) => (
              <div key={idx} className="flex justify-between text-xs">
                <span className="text-slate-300">{level.price_cents}¢</span>
                <span className="text-green-400">Yes: {level.yes_qty}</span>
                <span className="text-red-400">No: {level.no_qty}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent Trades */}
      {data.recent_trades && data.recent_trades.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-200 mb-2">Recent Trades</h4>
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {data.recent_trades.slice(0, 10).map((trade: any, idx: number) => (
              <div key={idx} className="flex justify-between text-xs">
                <span className="text-slate-300">{trade.contracts} @ {trade.price_cents}¢</span>
                <span className={trade.pnl_usd >= 0 ? 'text-green-400' : 'text-red-400'}>
                  {formatCurrency(trade.pnl_usd)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function OrderDetail({ orderId: _orderId }: { orderId: string }) {
  // TODO: Implement order detail view
  return (
    <div className="p-6 text-center">
      <Clock className="w-12 h-12 text-slate-600 mx-auto mb-3" />
      <p className="text-sm text-slate-400">Order detail view coming soon</p>
    </div>
  );
}

function TradeDetail({ tradeId: _tradeId }: { tradeId: string }) {
  // TODO: Implement trade detail view
  return (
    <div className="p-6 text-center">
      <DollarSign className="w-12 h-12 text-slate-600 mx-auto mb-3" />
      <p className="text-sm text-slate-400">Trade detail view coming soon</p>
    </div>
  );
}

function AgentDetail({ agentId }: { agentId: string }) {
  const { data, loading, error } = useKalshiDetail<any>(
    agentId ? API_ENDPOINTS.KALSHI_UI_STATE_AGENT_DETAIL(agentId) : null,
    !!agentId
  );

  if (loading) {
    return (
      <div className="p-6 space-y-4">
        <div className="h-6 bg-slate-800 rounded w-1/2 animate-pulse" />
        <div className="space-y-2 pt-4">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-4 bg-slate-800 rounded animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="p-6 text-center">
        <p className="text-sm text-slate-400">Failed to load agent details</p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h3 className="text-lg font-bold text-slate-100">{data.agent_id}</h3>
        <p className="text-sm text-slate-400">Agent Performance</p>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-slate-800/50 rounded-lg p-3">
          <div className="text-xs text-slate-400 mb-1">Total Fills</div>
          <div className="text-lg font-bold text-slate-200">{data.total_fills}</div>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-3">
          <div className="text-xs text-slate-400 mb-1">Win Rate</div>
          <div className="text-lg font-bold text-slate-200">{formatPercent(data.win_rate)}</div>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-3">
          <div className="text-xs text-slate-400 mb-1">Total PnL</div>
          <div className={`text-lg font-bold ${data.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {formatCurrency(data.total_pnl)}
          </div>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-3">
          <div className="text-xs text-slate-400 mb-1">Sharpe Ratio</div>
          <div className="text-lg font-bold text-slate-200">{data.sharpe_ratio?.toFixed(2) || 'N/A'}</div>
        </div>
      </div>

      {/* Additional Stats */}
      <div className="space-y-2">
        <div className="flex justify-between text-sm">
          <span className="text-slate-400">Edge Accuracy</span>
          <span className="text-slate-200">{formatPercent(data.edge_accuracy)}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-slate-400">Calibration Error</span>
          <span className="text-slate-200">{data.confidence_calibration_error?.toFixed(3) || 'N/A'}</span>
        </div>
        {data.brier_score !== null && (
          <div className="flex justify-between text-sm">
            <span className="text-slate-400">Brier Score</span>
            <span className="text-slate-200">{data.brier_score.toFixed(3)}</span>
          </div>
        )}
        <div className="flex justify-between text-sm">
          <span className="text-slate-400">Avg PnL/Trade</span>
          <span className={`text-slate-200 ${data.avg_pnl_per_trade >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {formatCurrency(data.avg_pnl_per_trade)}
          </span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-slate-400">Last Trade</span>
          <span className="text-slate-200">
            {data.last_trade_at ? fmtTimestamp(data.last_trade_at) : 'Never'}
          </span>
        </div>
      </div>

      {/* Recent Trades */}
      {data.recent_trades && data.recent_trades.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-200 mb-2">Recent Trades</h4>
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {data.recent_trades.slice(0, 10).map((trade: any, idx: number) => (
              <div key={idx} className="flex justify-between text-xs">
                <span className="text-slate-300">{trade.ticker}</span>
                <span className={trade.pnl_usd >= 0 ? 'text-green-400' : 'text-red-400'}>
                  {formatCurrency(trade.pnl_usd)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main Component ───────────────────────────────────────────────────────────────

export default function KalshiDetailDrawer({ isOpen, onClose, type, id }: KalshiDetailDrawerProps) {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    setIsVisible(isOpen);
  }, [isOpen]);

  if (!isVisible) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="relative w-full max-w-md bg-slate-900 border-l border-slate-800 shadow-2xl h-full overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-slate-900/95 backdrop-blur border-b border-slate-800 p-4 flex items-center justify-between z-10">
          <div className="flex items-center gap-2">
            <ChevronRight className="w-4 h-4 text-slate-400" />
            <span className="text-sm font-semibold text-slate-200 capitalize">
              {type} Detail
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 hover:bg-slate-800 rounded transition-colors"
          >
            <X className="w-5 h-5 text-slate-400" />
          </button>
        </div>

        {/* Content */}
        <div className="min-h-full">
          {type === 'market' && id && <MarketDetail ticker={id} />}
          {type === 'order' && id && <OrderDetail orderId={id} />}
          {type === 'trade' && id && <TradeDetail tradeId={id} />}
          {type === 'agent' && id && <AgentDetail agentId={id} />}
          {!type && (
            <div className="p-6 text-center">
              <Activity className="w-12 h-12 text-slate-600 mx-auto mb-3" />
              <p className="text-sm text-slate-400">Select an item to view details</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
