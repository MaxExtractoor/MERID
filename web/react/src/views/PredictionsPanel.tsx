import { useMemo } from 'react';
import MetricCard from '../components/MetricCard';
import DataTableEnhanced from '../components/DataTableEnhanced';
import StatusIndicator from '../components/StatusIndicator';
import { usePredictions } from '../hooks/usePredictions';
import { marketStatusToStatusType, confidenceToStatusType } from '../utils/statusMappers';
import { formatCurrency, formatPercent, formatTime, formatDate } from '../utils/formatters';
import { RefreshCw, TrendingUp, TrendingDown } from 'lucide-react';
import type { PredictionMarket } from '../types/predictions';

/**
 * Predictions Panel
 *
 * Displays prediction markets with:
 * - Metric cards for totals (markets, open, volume, P&L)
 * - Data table with market details, prices, positions, and confidence
 * - Live WebSocket updates for price changes and resolutions
 */
export function PredictionsPanel() {
  const { markets, meta, loading, error, lastUpdated } = usePredictions();

  // Sort markets by volume (desc) then by end time
  const sortedMarkets = useMemo(() => {
    return [...markets].sort((a, b) => {
      if (b.volume !== a.volume) return b.volume - a.volume;
      return new Date(a.endTime).getTime() - new Date(b.endTime).getTime();
    });
  }, [markets]);

  // Top 3 markets by volume for mini cards
  const topMarkets = useMemo(() => sortedMarkets.slice(0, 3), [sortedMarkets]);

  const columns = [
    {
      key: 'symbol' as keyof PredictionMarket,
      label: 'Symbol',
    },
    {
      key: 'question' as keyof PredictionMarket,
      label: 'Question',
      render: (value: string) => (
        <span className="text-sm text-slate-300 max-w-xs truncate block" title={value}>
          {value}
        </span>
      ),
    },
    {
      key: 'yesPrice' as keyof PredictionMarket,
      label: 'YES Price',
      sortable: true,
      render: (value: number, _row: PredictionMarket) => (
        <div className="flex items-center gap-2">
          <div className="w-16 h-2 bg-slate-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-green-500 transition-all duration-300"
              style={{ width: `${value * 100}%` }}
            />
          </div>
          <span className="text-sm font-medium">{formatPercent(value)}</span>
        </div>
      ),
    },
    {
      key: 'ourPosition' as keyof PredictionMarket,
      label: 'Position',
      render: (value: string, row: PredictionMarket) => {
        if (value === 'NONE') return <span className="text-slate-500">-</span>;
        const Icon = value === 'YES' ? TrendingUp : TrendingDown;
        const colorClass = value === 'YES' ? 'text-green-400' : 'text-red-400';
        return (
          <div className={`flex items-center gap-1 ${colorClass}`}>
            <Icon className="w-4 h-4" />
            <span className="font-medium">{value}</span>
            <span className="text-slate-400 text-sm">({row.ourSize})</span>
          </div>
        );
      },
    },
    {
      key: 'ourPnl' as keyof PredictionMarket,
      label: 'P&L',
      sortable: true,
      render: (value: number) => (
        <span className={value >= 0 ? 'text-green-400' : 'text-red-400'}>
          {formatCurrency(value)}
        </span>
      ),
    },
    {
      key: 'modelConfidence' as keyof PredictionMarket,
      label: 'Confidence',
      sortable: true,
      render: (value: number) => (
        <StatusIndicator
          status={confidenceToStatusType(value)}
          showText={false}
          className="inline-flex"
        />
      ),
    },
    {
      key: 'endTime' as keyof PredictionMarket,
      label: 'End Time',
      sortable: true,
      render: (value: string) => formatDate(value),
    },
    {
      key: 'status' as keyof PredictionMarket,
      label: 'Status',
      render: (value: string, row: PredictionMarket) => (
        <StatusIndicator
          status={marketStatusToStatusType(value as 'OPEN' | 'CLOSED' | 'RESOLVED', row.ourPnl)}
          showText
        />
      ),
    },
  ];

  if (loading) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-slate-800 rounded w-1/4" />
          <div className="grid grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-20 bg-slate-800 rounded" />
            ))}
          </div>
          <div className="h-64 bg-slate-800 rounded" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Prediction Markets</h2>
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4">
          <p className="text-red-400">Failed to load prediction markets</p>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">Prediction Markets</h2>
        {lastUpdated && (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <RefreshCw className="w-3 h-3" />
            <span>{formatTime(lastUpdated.toISOString())}</span>
          </div>
        )}
      </div>

      {/* Top Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          label="Total Markets"
          value={(meta?.total || 0).toString()}
          status="ONLINE"
        />
        <MetricCard
          label="Open Markets"
          value={(meta?.open || 0).toString()}
          status={(meta?.open || 0) > 0 ? 'GOOD' : 'WARNING'}
        />
        <MetricCard
          label="Total Volume"
          value={formatCurrency(meta?.totalVolume || 0)}
          status="ONLINE"
        />
        <MetricCard
          label="Total P&L"
          value={formatCurrency(meta?.totalPnl || 0)}
          status={(meta?.totalPnl || 0) >= 0 ? 'GOOD' : 'BAD'}
          delta={meta?.totalPnl || 0}
        />
      </div>

      {/* Top Markets Mini Cards */}
      {topMarkets.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {topMarkets.map((market, index) => (
            <div
              key={market.id || `market-${index}`}
              className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="font-medium text-white">{market.symbol}</span>
                <StatusIndicator
                  status={marketStatusToStatusType(market.status, market.ourPnl)}
                  showText={false}
                />
              </div>
              <p className="text-sm text-slate-400 mb-3 line-clamp-2">{market.question}</p>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="w-20 h-2 bg-slate-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-green-500 transition-all duration-300"
                      style={{ width: `${market.yesPrice * 100}%` }}
                    />
                  </div>
                  <span className="text-sm font-medium text-green-400">
                    {formatPercent(market.yesPrice)}
                  </span>
                </div>
                {market.ourPosition !== 'NONE' && (
                  <span className={`text-sm ${market.ourPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {formatCurrency(market.ourPnl)}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Markets Table */}
      <DataTableEnhanced
        data={sortedMarkets}
        columns={columns}
        pageSize={10}
        showPagination
        showFilter
      />
    </div>
  );
}
