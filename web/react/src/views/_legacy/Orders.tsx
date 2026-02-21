import { useState, useMemo } from 'react';
import { Search, RefreshCw } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import KalshiModeBadge from '../components/KalshiModeBadge';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import type { KalshiOrder } from '../types/kalshi';

export default function Orders() {
  const [filter, setFilter] = useState('all');
  const [searchTerm, setSearchTerm] = useState('');

  const { data: rawData, loading, refetch } = useApiData<{ orders: KalshiOrder[] }>(
    API_ENDPOINTS.KALSHI_ORDERS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.ORDERS },
  );

  const orders = useMemo(() => rawData?.orders ?? [], [rawData]);

  const filteredOrders = useMemo(() => orders.filter(o => {
    if (filter !== 'all' && o.status !== filter) return false;
    if (searchTerm && !o.ticker.toLowerCase().includes(searchTerm.toLowerCase())) return false;
    return true;
  }), [orders, filter, searchTerm]);

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'executed': case 'filled': return 'text-emerald-400 bg-emerald-500/10';
      case 'resting': case 'open': return 'text-blue-400 bg-blue-500/10';
      case 'canceled': case 'cancelled': return 'text-slate-400 bg-slate-500/10';
      case 'rejected': return 'text-rose-400 bg-rose-500/10';
      default: return 'text-slate-400 bg-slate-500/10';
    }
  };

  return (
    <div className="space-y-6">
      {/* Execution Gate — always visible */}
      <ExecutionGateStrip />

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">Kalshi Orders <KalshiModeBadge /></h1>
          <p className="text-slate-400">Resting and recent orders on your Kalshi account</p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-4 items-center bg-slate-900/70 rounded-xl p-4 border border-slate-800">
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input aria-label="Search ticker"
            id="order-search"
            name="orderSearch"
            type="text"
            placeholder="Search ticker..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-9 pr-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm focus:outline-none focus:border-blue-500 w-48"
          />
        </div>
        
        <select
          id="order-status-filter"
          name="orderStatusFilter"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          aria-label="Filter orders by status"
          className="px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="all">All Status</option>
          <option value="open">Open</option>
          <option value="filled">Filled</option>
          <option value="cancelled">Cancelled</option>
          <option value="rejected">Rejected</option>
        </select>

        <button type="button" onClick={() => refetch()} className="p-2 hover:bg-slate-800 rounded-lg transition-colors" title="Refresh" aria-label="Refresh">
          <RefreshCw className="w-4 h-4 text-slate-400" />
        </button>
      </div>

      {/* Orders Table */}
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 overflow-hidden">
        {loading ? (
          <div className="p-8 text-center">
            <div className="animate-spin w-8 h-8 border-2 border-orange-500 border-t-transparent rounded-full mx-auto mb-4" />
            <p className="text-slate-400">Loading orders...</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-slate-800/50">
              <tr className="text-slate-500 text-xs uppercase tracking-wider">
                <th className="text-left px-4 py-3">Order ID</th>
                <th className="text-left px-4 py-3">Ticker</th>
                <th className="text-left px-4 py-3">Side</th>
                <th className="text-right px-4 py-3">Size</th>
                <th className="text-right px-4 py-3">Filled</th>
                <th className="text-right px-4 py-3">Price</th>
                <th className="text-left px-4 py-3">Status</th>
                <th className="text-left px-4 py-3">Time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50">
              {filteredOrders.map((o) => (
                <tr key={o.order_id} className="hover:bg-slate-800/30 transition-colors">
                  <td className="px-4 py-3 font-mono text-slate-500 text-xs">{o.order_id.slice(0, 8)}…</td>
                  <td className="px-4 py-3 font-mono text-orange-300 font-medium">{o.ticker}</td>
                  <td className="px-4 py-3">
                    <span className={o.side === 'yes' ? 'text-emerald-400 font-semibold' : 'text-red-400 font-semibold'}>
                      {o.side.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right text-slate-200">{o.size}</td>
                  <td className="px-4 py-3 text-right text-slate-400">{o.filled}</td>
                  <td className="px-4 py-3 text-right text-slate-200">
                    {o.price !== null ? `${Math.round(o.price * 100)}¢` : 'Market'}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${getStatusColor(o.status)}`}>
                      {o.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-400">
                    {o.created_at ? new Date(o.created_at).toLocaleTimeString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        
        {!loading && filteredOrders.length === 0 && (
          <div className="p-8 text-center text-slate-400 text-sm">
            No Kalshi orders found.
          </div>
        )}
      </div>
    </div>
  );
}
