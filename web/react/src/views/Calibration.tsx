/**
 * Calibration View — Forecaster Brier stats + per-cell order-flow metrics
 *
 * Data (all verified live routes under /api/v1/kalshi):
 * - GET /api/v1/kalshi/calibration/stats      → {stats: {forecaster: [{bucket, ewma_brier, n_resolved, weight, ...}]}}
 * - GET /api/v1/kalshi/calibration/forecasters → {forecasters: [...], count}
 * - GET /api/v1/kalshi/calibration/cell-metrics → {cells: {"ASSET/tf": {...}}}
 */

import { useEffect } from 'react';
import { useKalshiStore, selectConnected } from '../store';
import { Target, Activity } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { apiUrl } from '../config/apiBase';
import { useApiQuery } from '../hooks/useTanStackQuery';

interface BucketStat {
  bucket: string;
  ewma_brier: number;
  n_resolved: number;
  brier_sum?: number;
  brier_sum_sq?: number;
  weight: number;
}

interface CalibrationStatsResponse {
  forecasters: number;
  bucket_filter: string | null;
  stats: Record<string, BucketStat[]>;
  error?: string;
}

interface ForecasterListResponse {
  forecasters: string[];
  count: number;
}

interface CellMetrics {
  asset: string;
  timeframe: string;
  candidates: number;
  vetoes: number;
  orders_submitted: number;
  fills: number;
  avg_edge: number;
  fill_rate: number;
  cost_cents: number;
  fill_cents: number;
  pnl_cents: number;
  veto_reasons?: Record<string, number>;
  last_order_ts?: number | null;
  last_fill_ts?: number | null;
}

interface CellMetricsResponse {
  cells: Record<string, CellMetrics>;
  count: number;
  error?: string;
}

const cents = (c: number): string => `$${(c / 100).toFixed(2)}`;

const Calibration = () => {
  const refreshAll = useKalshiStore(state => state.refreshAll);
  const connected = useKalshiStore(selectConnected);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  const statsQuery = useApiQuery<CalibrationStatsResponse>(
    apiUrl('/api/v1/kalshi/calibration/stats'),
    { refetchInterval: 60_000, staleTime: 30_000 }
  );
  const forecastersQuery = useApiQuery<ForecasterListResponse>(
    apiUrl('/api/v1/kalshi/calibration/forecasters'),
    { refetchInterval: 60_000, staleTime: 30_000 }
  );
  const cellsQuery = useApiQuery<CellMetricsResponse>(
    apiUrl('/api/v1/kalshi/calibration/cell-metrics'),
    { refetchInterval: 30_000, staleTime: 15_000 }
  );

  const stats: Record<string, BucketStat[]> = statsQuery.data?.stats ?? {};
  const forecasterIds = forecastersQuery.data?.forecasters ?? Object.keys(stats);
  const cells = Object.entries(cellsQuery.data?.cells ?? {}) as Array<[string, CellMetrics]>;
  const queryError = statsQuery.error ?? cellsQuery.error;

  // Flatten {forecaster: [bucket rows]} for the table.
  const statRows = Object.entries(stats).flatMap(([forecaster, buckets]) =>
    (buckets ?? []).map((b: BucketStat) => ({ forecaster, ...b }))
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Target className="w-8 h-8 text-rose-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Calibration</h1>
            <p className="text-sm text-slate-400">
              Forecaster Brier scores and per-cell order-flow metrics
              {forecasterIds.length > 0 && ` — ${forecasterIds.length} forecaster(s)`}
            </p>
          </div>
        </div>
        <Badge variant={connected ? 'success' : 'danger'}>
          {connected ? 'Connected' : 'Disconnected'}
        </Badge>
      </div>

      {queryError && (
        <div className="text-xs text-red-400" role="alert">
          Failed to load calibration data: {String(queryError)}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Forecaster Calibration (Brier)</CardTitle>
        </CardHeader>
        <CardContent>
          {statRows.length === 0 ? (
            <div className="text-center py-8 text-slate-400">
              <Activity className="w-12 h-12 mx-auto mb-4 text-slate-600" />
              <p>No calibration data available</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                    <th className="text-left p-3">Forecaster</th>
                    <th className="text-left p-3">Bucket</th>
                    <th className="text-right p-3">Resolved</th>
                    <th className="text-right p-3">EWMA Brier</th>
                    <th className="text-right p-3">Consensus Weight</th>
                  </tr>
                </thead>
                <tbody>
                  {statRows.map((row) => (
                    <tr key={`${row.forecaster}:${row.bucket}`} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                      <td className="p-3 font-medium text-white">{row.forecaster}</td>
                      <td className="p-3">
                        <Badge variant="info">{row.bucket}</Badge>
                      </td>
                      <td className="p-3 text-right font-mono">{row.n_resolved}</td>
                      <td className="p-3 text-right font-mono">{row.ewma_brier.toFixed(4)}</td>
                      <td className="p-3 text-right font-mono">{(row.weight * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Per-Cell Order-Flow Metrics (asset × timeframe)</CardTitle>
        </CardHeader>
        <CardContent>
          {cells.length === 0 ? (
            <div className="text-center py-8 text-slate-400">
              <p>No cell metrics available</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                    <th className="text-left p-3">Cell</th>
                    <th className="text-right p-3">Candidates</th>
                    <th className="text-right p-3">Vetoes</th>
                    <th className="text-right p-3">Orders</th>
                    <th className="text-right p-3">Fills</th>
                    <th className="text-right p-3">Fill Rate</th>
                    <th className="text-right p-3">Avg Edge</th>
                    <th className="text-right p-3">PnL</th>
                  </tr>
                </thead>
                <tbody>
                  {cells.map(([key, cell]) => (
                    <tr key={key} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                      <td className="p-3">
                        <div className="font-medium text-white">{cell.asset}/{cell.timeframe}</div>
                        {cell.veto_reasons && Object.keys(cell.veto_reasons).length > 0 && (
                          <div className="text-[10px] text-slate-500 mt-0.5">
                            vetoes: {Object.entries(cell.veto_reasons).map(([r, n]) => `${r}:${n}`).join(', ')}
                          </div>
                        )}
                      </td>
                      <td className="p-3 text-right font-mono">{cell.candidates}</td>
                      <td className="p-3 text-right font-mono">{cell.vetoes}</td>
                      <td className="p-3 text-right font-mono">{cell.orders_submitted}</td>
                      <td className="p-3 text-right font-mono">{cell.fills}</td>
                      <td className="p-3 text-right font-mono">{(cell.fill_rate * 100).toFixed(0)}%</td>
                      <td className="p-3 text-right font-mono">{cell.avg_edge.toFixed(4)}</td>
                      <td className={`p-3 text-right font-mono ${cell.pnl_cents >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {cents(cell.pnl_cents)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default Calibration;
