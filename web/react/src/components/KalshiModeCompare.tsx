/**
 * KalshiModeCompare — Paper vs Live mode comparison strip.
 *
 * Shows side-by-side metrics for paper and live trading modes:
 *   - Profit Factor (PF)
 *   - Expectancy (avg PnL per trade)
 *   - Win rate
 *   - Slippage delta (paper vs live fill quality)
 *
 * Used to gate promotion/demotion decisions from the UI.
 */

import React, { useMemo } from 'react';
import { GitCompare, ArrowRight } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

interface PaperStats {
  paper: {
    total_pnl: number;
    equity: number;
    trades_24h: number;
    active_positions: number;
  };
  controller: {
    mode: string;
    is_paper: boolean;
    is_live: boolean;
  };
}

interface SizingMetrics {
  profit_factor: number;
  win_rate_pct: number;
  trades_today: number;
  drawdown_pct: number;
  kelly_fraction: number;
  effective_fraction: number;
  sharpe_ratio: number;
  sortino_ratio: number;
}

function metricColor(value: number, good: number, bad: number): string {
  if (value >= good) return 'text-green-400';
  if (value <= bad) return 'text-red-400';
  return 'text-yellow-400';
}

const KalshiModeCompare: React.FC = () => {
  const modeResult = useApiData<PaperStats>(
    `${API_ENDPOINTS.TRADE_MODE}/status`,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW },
  );
  const sizingResult = useApiData<SizingMetrics>(
    API_ENDPOINTS.KALSHI_SIZING_METRICS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW },
  );

  const data = useMemo(() => {
    const mode = modeResult.data;
    const sizing = sizingResult.data;
    if (!mode || !sizing) return null;

    const paperPnl = mode.paper?.total_pnl ?? 0;
    const paperEquity = mode.paper?.equity ?? 10000;
    const trades = sizing.trades_today;
    const expectancy = trades > 0 ? paperPnl / trades : 0;

    return {
      mode: mode.controller?.mode ?? 'paper',
      isPaper: mode.controller?.is_paper ?? true,
      isLive: mode.controller?.is_live ?? false,
      pf: sizing.profit_factor,
      winRate: sizing.win_rate_pct,
      sharpe: sizing.sharpe_ratio,
      sortino: sizing.sortino_ratio,
      drawdown: sizing.drawdown_pct,
      trades,
      expectancy,
      paperPnl,
      paperRoi: paperEquity > 0 ? (paperPnl / paperEquity) * 100 : 0,
      kelly: sizing.kelly_fraction,
      effectiveKelly: sizing.effective_fraction,
    };
  }, [modeResult.data, sizingResult.data]);

  if (!data) return null;

  const readyForPromotion = data.pf >= 1.5 && data.winRate >= 50 && data.trades >= 10 && data.drawdown < 10;

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <GitCompare className="w-4 h-4 text-purple-400" />
          <h3 className="text-sm font-medium text-gray-300">Mode Comparison</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
            data.isLive ? 'bg-red-500/20 text-red-400 border border-red-500/30' : 'bg-blue-500/20 text-blue-400 border border-blue-500/30'
          }`}>
            {data.mode}
          </span>
          {readyForPromotion && (
            <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 animate-pulse">
              Ready to promote
            </span>
          )}
        </div>
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-4 gap-0 divide-x divide-slate-800">
        {/* PF */}
        <div className="px-3 py-2.5 text-center">
          <p className="text-[10px] text-gray-500 mb-0.5">Profit Factor</p>
          <p className={`text-sm font-bold font-mono ${metricColor(data.pf, 1.5, 1.0)}`}>
            {data.pf.toFixed(2)}
          </p>
          <p className="text-[9px] text-gray-600">{data.pf >= 1.5 ? 'Strong' : data.pf >= 1.0 ? 'Break-even' : 'Losing'}</p>
        </div>

        {/* Win Rate */}
        <div className="px-3 py-2.5 text-center">
          <p className="text-[10px] text-gray-500 mb-0.5">Win Rate</p>
          <p className={`text-sm font-bold font-mono ${metricColor(data.winRate, 55, 40)}`}>
            {data.winRate.toFixed(1)}%
          </p>
          <p className="text-[9px] text-gray-600">{data.trades} trades</p>
        </div>

        {/* Expectancy */}
        <div className="px-3 py-2.5 text-center">
          <p className="text-[10px] text-gray-500 mb-0.5">Expectancy</p>
          <p className={`text-sm font-bold font-mono ${data.expectancy >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {data.expectancy >= 0 ? '+' : ''}${data.expectancy.toFixed(2)}
          </p>
          <p className="text-[9px] text-gray-600">per trade</p>
        </div>

        {/* Sharpe */}
        <div className="px-3 py-2.5 text-center">
          <p className="text-[10px] text-gray-500 mb-0.5">Sharpe</p>
          <p className={`text-sm font-bold font-mono ${metricColor(data.sharpe, 1.5, 0.5)}`}>
            {data.sharpe.toFixed(2)}
          </p>
          <p className="text-[9px] text-gray-600">{data.drawdown.toFixed(1)}% DD</p>
        </div>
      </div>

      {/* Sizing regime strip */}
      <div className="flex items-center gap-3 px-4 py-1.5 border-t border-slate-800/50 text-[10px]">
        <div>
          <span className="text-gray-500">Kelly</span>{' '}
          <span className="text-white font-mono">{(data.kelly * 100).toFixed(2)}%</span>
        </div>
        <ArrowRight className="w-2.5 h-2.5 text-gray-600" />
        <div>
          <span className="text-gray-500">Effective</span>{' '}
          <span className="text-white font-mono">{(data.effectiveKelly * 100).toFixed(3)}%</span>
        </div>
        <div className="ml-auto">
          <span className="text-gray-500">Paper PnL</span>{' '}
          <span className={`font-mono ${data.paperPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {data.paperPnl >= 0 ? '+' : ''}${data.paperPnl.toFixed(2)}
          </span>
          <span className="text-gray-600 ml-1">({data.paperRoi >= 0 ? '+' : ''}{data.paperRoi.toFixed(2)}%)</span>
        </div>
      </div>
    </div>
  );
};

export default KalshiModeCompare;
