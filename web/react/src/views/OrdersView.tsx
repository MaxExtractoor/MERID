import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { Icon } from '../ui/icons';
import { useApiData } from '../hooks/useApiData';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS, ORDER_STATUS, AUTH_TOKEN_KEY } from '../config/constants';
import { fmtTimestamp } from '../utils/formatters';
import type { KalshiOrder } from '../types/kalshi';
import KalshiModeBadge from '../components/KalshiModeBadge';
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import KalshiCancelAllButton from '../components/KalshiCancelAllButton';
import { ConfirmModal } from '../components/ConfirmModal';
import { useKalshiRiskStream } from '../hooks/useKalshiRiskStream';

type StatusFilter = 'all' | 'resting' | 'pending' | 'filled' | 'canceled';

export default function OrdersView() {
  const pollOpts = { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD };
  const ordResult = useApiData<{ orders: KalshiOrder[] }>(API_ENDPOINTS.KALSHI_ORDERS, pollOpts);
  const fillResult = useApiData<{ fills: Array<{ trade_id: string; ticker: string; side: string; size: number; price: number; fee: number; timestamp: string }> }>(
    API_ENDPOINTS.KALSHI_FILLS, pollOpts
  );

  const { summary } = useKalshiRiskStream();
  const ordRefetch = ordResult.refetch;
  const fillRefetch = fillResult.refetch;
  useEffect(() => { if (summary) { ordRefetch(); fillRefetch(); } }, [summary, ordRefetch, fillRefetch]);

  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [cancellingOrder, setCancellingOrder] = useState<string | null>(null);
  const [amendOrderId, setAmendOrderId] = useState<string | null>(null);
  const [amendPrice, setAmendPrice] = useState('');
  const [amendSubmitting, setAmendSubmitting] = useState(false);
  const [orderError, setOrderError] = useState<string | null>(null);
  const [confirmModal, setConfirmModal] = useState<{
    isOpen: boolean; title: string; message: string;
    onConfirm: () => void; confirmVariant?: 'primary' | 'danger' | 'warning';
  }>({ isOpen: false, title: '', message: '', onConfirm: () => undefined });

  const authHeaders = useCallback((headers?: HeadersInit): HeadersInit => {
    const token = localStorage.getItem(AUTH_TOKEN_KEY);
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
      ...(headers ?? {}),
    };
  }, []);

  const allOrders = useMemo(() => ordResult.data?.orders ?? [], [ordResult.data]);
  const allFills = useMemo(() => fillResult.data?.fills ?? [], [fillResult.data]);
  const [fillsPage, setFillsPage] = useState(1);
  const FILLS_PAGE_SIZE = 20;
  const fillsTotalPages = Math.max(1, Math.ceil(allFills.length / FILLS_PAGE_SIZE));
  const recentFills = useMemo(
    () => allFills.slice((fillsPage - 1) * FILLS_PAGE_SIZE, fillsPage * FILLS_PAGE_SIZE),
    [allFills, fillsPage]
  );
  // BUG-005 fix: clamp fills page when data shrinks
  useEffect(() => {
    if (fillsPage > fillsTotalPages) setFillsPage(fillsTotalPages);
  }, [fillsTotalPages, fillsPage]);

  const orders = useMemo(() => {
    if (statusFilter === 'all') return allOrders;
    return allOrders.filter(o => {
      switch (statusFilter) {
        case 'resting': return o.status === ORDER_STATUS.RESTING;
        case 'pending': return o.status === ORDER_STATUS.PENDING;
        case 'filled': return o.status === ORDER_STATUS.FILLED;
        case 'canceled': return o.status === ORDER_STATUS.CANCELED || o.status === ORDER_STATUS.CANCELLED;
        default: return true;
      }
    });
  }, [allOrders, statusFilter]);

  // Stats
  const stats = useMemo(() => {
    const resting = allOrders.filter(o => o.status === ORDER_STATUS.RESTING).length;
    const pending = allOrders.filter(o => o.status === ORDER_STATUS.PENDING).length;
    const filled = allOrders.filter(o => o.status === ORDER_STATUS.FILLED).length;
    const canceled = allOrders.filter(o => o.status === ORDER_STATUS.CANCELED || o.status === ORDER_STATUS.CANCELLED).length;
    const totalNotional = allOrders
      .filter(o => o.status === ORDER_STATUS.RESTING || o.status === ORDER_STATUS.PENDING)
      .reduce((sum, o) => sum + ((o.price ?? 0) * (o.size ?? 0)), 0);
    return { resting, pending, filled, canceled, total: allOrders.length, totalNotional };
  }, [allOrders]);

  const executeCancelOrder = useCallback(async (orderId: string) => {
    setCancellingOrder(orderId);
    setOrderError(null);
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_ORDER_CANCEL(orderId)}`, {
        method: 'DELETE', headers: authHeaders(),
      });
      if (!res.ok) throw new Error(`Cancel failed: HTTP ${res.status}`);
      ordRefetch();
    } catch (err) {
      setOrderError(err instanceof Error ? err.message : `Cancel order ${orderId} failed`);
    }
    setCancellingOrder(null);
  }, [authHeaders, ordRefetch]);

  const handleCancelOrder = useCallback((orderId: string) => {
    setAmendOrderId(null);
    setAmendPrice('');
    setConfirmModal({
      isOpen: true,
      title: 'Cancel Order',
      message: `Cancel order ${orderId.slice(0, 12)}…? This cannot be undone.`,
      confirmVariant: 'danger',
      onConfirm: async () => {
        setConfirmModal(prev => ({ ...prev, isOpen: false }));
        await executeCancelOrder(orderId);
      },
    });
  }, [executeCancelOrder]);

  const handleAmendOpen = useCallback((orderId: string, currentPrice: number | null) => {
    setAmendOrderId(orderId);
    setAmendPrice(currentPrice != null ? String(Math.round(currentPrice * 100)) : '');
  }, []);

  const handleAmendSubmit = useCallback(async () => {
    if (!amendOrderId || amendSubmitting) return;
    const newPriceCents = parseInt(amendPrice, 10);
    if (isNaN(newPriceCents) || newPriceCents < 1 || newPriceCents > 99) return;
    setAmendSubmitting(true);
    setOrderError(null);
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_ORDER_AMEND(amendOrderId)}?price_cents=${newPriceCents}`, {
        method: 'PATCH', headers: authHeaders(),
      });
      if (!res.ok) throw new Error(`Amend failed: HTTP ${res.status}`);
      ordRefetch();
      setAmendOrderId(null);
      setAmendPrice('');
    } catch (err) {
      setOrderError(err instanceof Error ? err.message : 'Amend order failed');
    } finally {
      setAmendSubmitting(false);
    }
  }, [amendOrderId, amendPrice, amendSubmitting, authHeaders, ordRefetch]);

  if (ordResult.loading && !allOrders.length) {
    return (
      <div className="p-6 flex items-center gap-2 text-slate-400">
        <Icon name="loader" size={16} className="animate-spin" />
        Loading orders...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <ExecutionGateStrip />

      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-teal-500/10">
            <Icon name="clipboard" size={24} className="w-6 h-6 text-teal-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white flex items-center gap-2">
              Orders
              <KalshiModeBadge />
            </h1>
            <p className="text-xs text-gray-500">
              {stats.total} total · {stats.resting} resting · {stats.pending} pending
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {stats.resting > 0 && (
            <KalshiCancelAllButton
              compact={true}
              onSuccess={() => { ordRefetch(); fillRefetch(); }}
            />
          )}
          <button
            type="button"
            onClick={() => ordRefetch()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-gray-300 text-xs border border-slate-700"
          >
            <Icon name="refresh" size={14} className="w-3.5 h-3.5" />
            Refresh
          </button>
        </div>
      </div>

      {/* Error banner */}
      {orderError && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          <Icon name="alert" size={16} className="w-4 h-4 shrink-0" />
          <span>{orderError}</span>
          <button type="button" onClick={() => setOrderError(null)} className="ml-auto text-red-400 hover:text-red-300" aria-label="Dismiss">×</button>
        </div>
      )}

      {/* Status Filter Chips */}
      <div className="flex items-center gap-2 flex-wrap">
        <Icon name="filter" size={12} className="w-3 h-3 text-gray-500" />
        {([
          { key: 'all' as StatusFilter, label: 'All', count: stats.total },
          { key: 'resting' as StatusFilter, label: 'Resting', count: stats.resting },
          { key: 'pending' as StatusFilter, label: 'Pending', count: stats.pending },
          { key: 'filled' as StatusFilter, label: 'Filled', count: stats.filled },
          { key: 'canceled' as StatusFilter, label: 'Canceled', count: stats.canceled },
        ]).map(f => (
          <button
            type="button"
            key={f.key}
            onClick={() => setStatusFilter(f.key)}
            className={`px-2 py-0.5 rounded-full text-[11px] font-medium transition-all ${
              statusFilter === f.key
                ? 'bg-teal-500/20 text-teal-300 ring-1 ring-teal-500/50'
                : 'text-gray-500 bg-slate-800 hover:text-white'
            }`}
          >
            {f.label} {f.count > 0 && <span className="opacity-60">({f.count})</span>}
          </button>
        ))}
      </div>

      {/* Open Orders Notional */}
      {stats.totalNotional > 0 && (
        <div className="flex items-center gap-4 px-3 py-2 bg-slate-900/50 rounded-lg border border-slate-800 text-xs text-gray-500">
          <span>Open order notional <span className="text-gray-600">(pre-fee)</span>: <span className="text-white font-medium">${stats.totalNotional.toFixed(2)}</span></span>
          <span>Resting: <span className="text-blue-400 font-medium">{stats.resting}</span></span>
          <span>Pending: <span className="text-yellow-400 font-medium">{stats.pending}</span></span>
        </div>
      )}

      {/* Orders Table */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-gray-500 text-[11px] uppercase tracking-wider">
              <th className="text-left p-3">Order ID</th>
              <th className="text-left p-3">Ticker</th>
              <th className="text-left p-3">Side</th>
              <th className="text-right p-3">Size</th>
              <th className="text-right p-3">Price</th>
              <th className="text-right p-3">Filled</th>
              <th className="text-left p-3">Status</th>
              <th className="p-3" />
            </tr>
          </thead>
          <tbody>
            {orders.length === 0 ? (
              <tr>
                <td colSpan={8} className="text-center py-12 text-gray-600">
                  <Icon name="inbox" size={32} className="w-8 h-8 mx-auto mb-2 opacity-50" />
                  No orders{statusFilter !== 'all' ? ` matching "${statusFilter}"` : ''}
                </td>
              </tr>
            ) : (
              orders.map((o) => (
                <React.Fragment key={o.order_id}>
                  <tr className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">
                    <td className="p-3 font-mono text-gray-500 text-[10px]">{o.order_id.slice(0, 12)}…</td>
                    <td className="p-3 font-mono text-white text-xs">{o.ticker}</td>
                    <td className="p-3">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                        o.side === 'buy' ? 'text-green-400 bg-green-400/10' : 'text-red-400 bg-red-400/10'
                      }`}>
                        {(o.side ?? '—').toUpperCase()}
                      </span>
                    </td>
                    <td className="p-3 text-right text-white font-mono text-xs">{o.size}</td>
                    <td className="p-3 text-right text-gray-400 font-mono text-xs">
                      {o.price != null ? `${((o.price ?? 0) * 100).toFixed(0)}¢` : 'MKT'}
                    </td>
                    <td className="p-3 text-right text-gray-400 font-mono text-xs">{o.filled}/{o.size}</td>
                    <td className="p-3">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                        o.status === ORDER_STATUS.RESTING ? 'text-blue-400 bg-blue-400/10'
                        : o.status === ORDER_STATUS.PENDING ? 'text-yellow-400 bg-yellow-400/10'
                        : o.status === ORDER_STATUS.CANCELED || o.status === ORDER_STATUS.CANCELLED ? 'text-gray-500 bg-gray-500/10'
                        : o.status === ORDER_STATUS.FILLED ? 'text-green-400 bg-green-400/10'
                        : 'text-gray-400 bg-gray-400/10'
                      }`}>{o.status}</span>
                    </td>
                    <td className="p-3 text-right">
                      {o.status === ORDER_STATUS.RESTING && (
                        <div className="flex items-center justify-end gap-1">
                          <button
                            type="button"
                            onClick={() => handleAmendOpen(o.order_id, o.price)}
                            className="p-1 rounded hover:bg-blue-500/20 text-gray-600 hover:text-blue-400 transition-colors"
                            title="Amend price"
                          >
                            <Icon name="edit" size={14} className="w-3.5 h-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleCancelOrder(o.order_id)}
                            disabled={cancellingOrder === o.order_id}
                            className="p-1 rounded hover:bg-red-500/20 text-gray-600 hover:text-red-400 transition-colors disabled:opacity-50"
                            title="Cancel order"
                          >
                            <Icon name="close" size={14} className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                  {amendOrderId === o.order_id && (
                    <tr className="bg-blue-500/5 border-b border-slate-800">
                      <td colSpan={8} className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-gray-400">New price (1–99¢):</span>
                          <input
                            type="number" min={1} max={99}
                            value={amendPrice}
                            disabled={confirmModal.isOpen || amendSubmitting}
                            onChange={e => setAmendPrice(e.target.value)}
                            className="w-20 bg-slate-700 border border-slate-600 rounded px-2 py-1 text-xs text-white font-mono focus:border-blue-400 focus:outline-none disabled:opacity-50"
                            aria-label="New limit price in cents"
                            onKeyDown={e => {
                              if (e.key === 'Enter' && !confirmModal.isOpen) void handleAmendSubmit();
                              if (e.key === 'Escape') { setAmendOrderId(null); setAmendPrice(''); }
                            }}
                          />
                          <span className="text-xs text-gray-500">¢</span>
                          <button type="button" onClick={() => void handleAmendSubmit()}
                            disabled={confirmModal.isOpen || amendSubmitting}
                            className="px-2 py-1 rounded text-xs bg-blue-500/20 text-blue-300 hover:bg-blue-500/30 border border-blue-500/30 disabled:opacity-50 disabled:cursor-not-allowed">
                            {amendSubmitting ? '…' : 'Amend'}
                          </button>
                          <button type="button" onClick={() => { setAmendOrderId(null); setAmendPrice(''); }}
                            className="px-2 py-1 rounded text-xs bg-slate-700 text-gray-400 hover:text-white">
                            Cancel
                          </button>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))
            )}
          </tbody>
        </table>

        {/* Footer */}
        {orders.length > 0 && (
          <div className="flex items-center justify-between px-3 py-2 border-t border-slate-800 bg-slate-900/50 text-[11px] text-gray-500">
            <span>{orders.length} order{orders.length !== 1 ? 's' : ''} shown</span>
          </div>
        )}
      </div>

      {/* Recent Fills */}
      {allFills.length > 0 && (
        <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
          <div className="px-3 py-2 border-b border-slate-800 flex items-center gap-2">
            <Icon name="check" size={14} className="w-3.5 h-3.5 text-green-400" />
            <span className="text-xs font-medium text-gray-300">Recent Fills</span>
            <span className="text-[10px] text-gray-600">{allFills.length} total</span>
            {fillsTotalPages > 1 && (
              <div className="ml-auto flex items-center gap-1 text-[10px] text-gray-500">
                <button type="button" onClick={() => setFillsPage(p => Math.max(1, p - 1))} disabled={fillsPage === 1}
                  className="px-1 rounded hover:bg-slate-700 disabled:opacity-30" aria-label="Previous fills page">
                  ‹
                </button>
                <span>{fillsPage}/{fillsTotalPages}</span>
                <button type="button" onClick={() => setFillsPage(p => Math.min(fillsTotalPages, p + 1))} disabled={fillsPage === fillsTotalPages}
                  className="px-1 rounded hover:bg-slate-700 disabled:opacity-30" aria-label="Next fills page">
                  ›
                </button>
              </div>
            )}
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-gray-500 text-[11px] uppercase tracking-wider">
                <th className="text-left p-3">Time</th>
                <th className="text-left p-3">Ticker</th>
                <th className="text-left p-3">Side</th>
                <th className="text-right p-3">Size</th>
                <th className="text-right p-3">Price</th>
                <th className="text-right p-3">Fee</th>
              </tr>
            </thead>
            <tbody>
              {recentFills.map((f) => (
                <tr key={f.trade_id} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">
                  <td className="p-3 text-gray-500 text-[10px]">{fmtTimestamp(f.timestamp, { timeOnly: true })}</td>
                  <td className="p-3 font-mono text-white text-xs">{f.ticker}</td>
                  <td className="p-3">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                      f.side === 'yes' ? 'text-green-400 bg-green-400/10' : 'text-red-400 bg-red-400/10'
                    }`}>{(f.side ?? '—').toUpperCase()}</span>
                  </td>
                  <td className="p-3 text-right text-white font-mono text-xs">{f.size}</td>
                  <td className="p-3 text-right text-gray-400 font-mono text-xs">{((f.price ?? 0) * 100).toFixed(1)}¢</td>
                  <td className="p-3 text-right text-yellow-400 text-xs">${(f.fee ?? 0).toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmModal
        isOpen={confirmModal.isOpen}
        title={confirmModal.title}
        message={confirmModal.message}
        confirmVariant={confirmModal.confirmVariant}
        onConfirm={confirmModal.onConfirm}
        onCancel={() => setConfirmModal(prev => ({ ...prev, isOpen: false }))}
      />
    </div>
  );
}
