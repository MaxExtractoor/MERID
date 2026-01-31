import { useMemo } from 'react';
import MetricCard from '../components/MetricCard';
import DataTableEnhanced from '../components/DataTableEnhanced';
import StatusIndicator from '../components/StatusIndicator';
import { useOpenOrders } from '../hooks/useOpenOrders';
import type { OrderRow } from '../types/orders';
import { orderStatusToStatusType } from '../utils/statusMappers';
import { formatCurrency, formatNumber, formatPercent, formatTime } from '../utils/formatters';
import { RefreshCw } from 'lucide-react';

/**
 * Open Orders Panel
 * 
 * Displays real-time open order data with:
 * - Summary metric cards (total, pending, partially filled, total notional)
 * - Sortable/filterable data table with order details
 * - Live WebSocket updates for order changes
 */
export function OpenOrdersPanel() {
  const { rows, meta, loading, error, lastUpdated } = useOpenOrders();

  const columns = useMemo(() => [
    {
      key: 'symbol' as keyof OrderRow,
      label: 'Symbol',
      sortable: true,
    },
    {
      key: 'side' as keyof OrderRow,
      label: 'Side',
      sortable: true,
      render: (value: string) => (
        <span className={value === 'BUY' ? 'text-green-500' : 'text-red-500'}>
          {value}
        </span>
      ),
    },
    {
      key: 'type' as keyof OrderRow,
      label: 'Type',
      sortable: true,
    },
    {
      key: 'status' as keyof OrderRow,
      label: 'Status',
      sortable: true,
      render: (value: string) => (
        <StatusIndicator status={orderStatusToStatusType(value as any)} showText />
      ),
    },
    {
      key: 'price' as keyof OrderRow,
      label: 'Price',
      sortable: true,
      render: (value: number | null, row: OrderRow) => (
        <span>
          {row.type === 'MARKET' && value == null
            ? 'MKT'
            : value != null
            ? formatCurrency(value)
            : '-'
          }
        </span>
      ),
    },
    {
      key: 'size' as keyof OrderRow,
      label: 'Size',
      sortable: true,
      render: (value: number) => formatNumber(value, 4),
    },
    {
      key: 'filledSize' as keyof OrderRow,
      label: 'Filled %',
      sortable: true,
      render: (value: number, row: OrderRow) => {
        const pct = row.size > 0 ? (value / row.size) * 100 : 0;
        return (
          <div className="flex items-center gap-2">
            <div className="w-16 bg-slate-700 rounded-full h-2">
              <div
                className={`h-2 rounded-full ${
                  pct >= 100 ? 'bg-green-500' : pct >= 50 ? 'bg-amber-500' : 'bg-blue-500'
                }`}
                style={{ width: `${Math.min(pct, 100)}%` }}
              />
            </div>
            <span className="text-sm">{formatPercent(pct / 100)}</span>
          </div>
        );
      },
    },
    {
      key: 'notional' as keyof OrderRow,
      label: 'Notional',
      sortable: true,
      render: (value: number) => formatCurrency(value),
    },
    {
      key: 'venue' as keyof OrderRow,
      label: 'Venue',
      sortable: true,
    },
    {
      key: 'createdAt' as keyof OrderRow,
      label: 'Created',
      sortable: true,
      render: (value: string) => formatTime(value),
    },
  ], []);

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="metric-card animate-pulse">
              <div className="h-4 bg-slate-700 rounded w-24 mb-2" />
              <div className="h-8 bg-slate-700 rounded w-16" />
            </div>
          ))}
        </div>
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
          <div className="h-64 bg-slate-800 rounded animate-pulse" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-900/20 border border-red-800 rounded-xl p-6">
        <h3 className="text-lg font-semibold text-red-400 mb-2">Error loading open orders</h3>
        <p className="text-red-300">{error.message}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Metric Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <MetricCard
          label="Total Orders"
          value={meta.total}
          status="GOOD"
        />
        <MetricCard
          label="Pending"
          value={meta.pending}
          status={meta.pending > 0 ? 'ONLINE' : 'GOOD'}
        />
        <MetricCard
          label="Partially Filled"
          value={meta.partiallyFilled}
          status={meta.partiallyFilled > 0 ? 'WARNING' : 'GOOD'}
        />
        <MetricCard
          label="Total Notional"
          value={formatCurrency(meta.totalNotional)}
          status="GOOD"
        />
      </div>

      {/* Last Updated Indicator */}
      {lastUpdated && (
        <div className="flex items-center gap-2 text-sm text-slate-400 px-1">
          <RefreshCw className="w-3 h-3" />
          <span>Last updated: {formatTime(lastUpdated.toISOString())}</span>
        </div>
      )}

      {/* Orders Table */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Open Orders</h2>
        <DataTableEnhanced
          data={rows}
          columns={columns}
          pageSize={15}
          showPagination
          showFilter
        />
      </div>
    </div>
  );
}
