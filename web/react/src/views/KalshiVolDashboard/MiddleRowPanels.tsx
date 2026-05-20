/**
 * VolDashboardMiddleRow - Middle row panels for volatility dashboard
 * 
 * Contains Agent Performance Grid and Equity & Vol Chart.
 * 
 * Tier 4: KalshiVolDashboardView.tsx Split (929→4 files)
 */

import { BarChart3, TrendingUp, Bot } from '../../ui/icons';
import { AGENT_STATUS } from '../../config/constants';
import type { SizingMetrics } from '../../types/kalshi';
import type { VolDashGridStatus, PnlPoint } from './types';
import { TIER_COLORS } from './types';
import { pctBar } from './TopRowCards';

interface MiddleRowPanelsProps {
  grid: VolDashGridStatus | undefined;
  sizing: SizingMetrics | undefined;
  pnlPoints: PnlPoint[];
  consensusRate: number;
  engineRunning: boolean;
}

export function MiddleRowPanels({
  grid,
  sizing,
  pnlPoints,
  consensusRate,
  engineRunning,
}: MiddleRowPanelsProps) {
  const tierStyle = TIER_COLORS[sizing?.drawdown_tier ?? 'normal'] ?? TIER_COLORS.normal;
  const latestPnlPoint = pnlPoints.length > 0 ? pnlPoints[pnlPoints.length - 1] : null;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* 4. Agent Performance Grid */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800">
          <BarChart3 className="w-4 h-4 text-orange-400" />
          <h3 className="text-sm font-medium text-gray-300">Agent Performance Grid</h3>
          <span className="ml-auto text-[10px] text-gray-500">{grid?.agent_count ?? 0} agents</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-800 text-gray-500 text-[10px] uppercase">
                <th className="text-left p-2 pl-4">Agent</th>
                <th className="text-right p-2">WR%</th>
                <th className="text-right p-2">PF</th>
                <th className="text-right p-2">Sharpe</th>
                <th className="text-right p-2">Fills</th>
                <th className="text-right p-2 pr-4">Size f</th>
              </tr>
            </thead>
            <tbody>
              {(!grid?.agents || grid.agents.length === 0) ? (
                <tr><td colSpan={6} className="text-center py-6 text-gray-500">
                  No agents running — start the grid from Overview
                </td></tr>
              ) : (
                grid.agents.map(a => (
                  <tr key={a.name} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                    <td className="p-2 pl-4">
                      <div className="flex items-center gap-1.5">
                        <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                          a.status === AGENT_STATUS.RUNNING ? 'bg-green-400 animate-pulse' :
                          a.status === AGENT_STATUS.PAUSED ? 'bg-yellow-400' : 'bg-gray-500'
                        }`} />
                        <div>
                          <div className="text-white font-mono text-[11px]">{a.asset}/{a.timeframe}</div>
                          {a.errors != null && a.errors > 0 && (
                            <div className="text-[9px] text-red-400">{a.errors} err</div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className={`p-2 text-right font-mono ${
                      (a.win_rate ?? 0) >= 55 ? 'text-green-400' :
                      (a.win_rate ?? 0) >= 45 ? 'text-yellow-400' : 'text-red-400'
                    }`}>
                      {((a.win_rate ?? 0)).toFixed(0)}%
                    </td>
                    <td className={`p-2 text-right font-mono ${
                      (a.pf ?? 0) >= 1.5 ? 'text-green-400' :
                      (a.pf ?? 0) >= 1.0 ? 'text-yellow-400' : 'text-red-400'
                    }`}>
                      {(a.pf ?? 0).toFixed(2)}
                    </td>
                    <td className="p-2 text-right font-mono text-blue-400">{(a.sharpe ?? 0).toFixed(2)}</td>
                    <td className="p-2 text-right font-mono text-gray-300">{a.fills ?? a.cycles ?? 0}</td>
                    <td className="p-2 pr-4 text-right font-mono text-white">{(a.size_factor ?? 0).toFixed(2)}×</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {/* Swarm consensus rate footer */}
        {engineRunning && (
          <div className="px-4 py-2 border-t border-slate-800 flex items-center gap-3 text-[10px] text-gray-500">
            <Bot className="w-3 h-3" />
            <span>Swarm consensus rate: <span className="text-white font-mono">{((consensusRate ?? 0) * 100).toFixed(0)}%</span></span>
            <span className="ml-auto text-green-400">engine running</span>
          </div>
        )}
      </div>

      {/* 5. Equity & Vol Chart */}
      <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 space-y-3">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-green-400" />
          <h3 className="text-sm font-medium text-gray-300">Equity & Vol</h3>
          {sizing && (
            <span className={`ml-auto px-2 py-0.5 rounded text-[10px] font-bold ${tierStyle.text} ${tierStyle.bg}`}>
              {(sizing?.drawdown_tier ?? 'normal').toUpperCase()}
            </span>
          )}
        </div>

        {pnlPoints.length > 0 ? (
          <>
            {/* Sparkline with drawdown-tier color shading */}
            <div className="flex items-end gap-px h-20 relative">
              {pnlPoints.slice(-40).map((p, i) => {
                const slice = pnlPoints.slice(-40);
                const max = Math.max(...slice.map(pp => pp.equity));
                const min = Math.min(...slice.map(pp => pp.equity));
                const range = max - min || 1;
                const h = ((p.equity - min) / range) * 100;
                const base = pnlPoints[0]?.equity ?? 0;
                const tier = sizing?.drawdown_tier ?? 'normal';
                const barColor =
                  tier === 'halt' ? 'bg-red-500/70' :
                  tier === 'downsize' ? 'bg-orange-500/70' :
                  tier === 'warning' ? 'bg-yellow-500/70' :
                  p.equity >= base ? 'bg-green-500/60' : 'bg-red-500/60';
                return (
                  <div
                    key={i}
                    className={`flex-1 rounded-sm ${barColor} transition-all`}
                    style={{ height: `${Math.max(4, h)}%` }}
                    title={`${p.ts}: $${(p.equity ?? 0).toFixed(2)} | rvol=${((p.realized_vol ?? 0)*100).toFixed(1)}%`}
                  />
                );
              })}
            </div>

            {/* Vol overlay bars */}
            <div className="space-y-1">
              <div className="flex justify-between text-[10px] text-gray-500">
                <span>Realized Vol</span>
                <span className={`font-mono ${
                  (latestPnlPoint?.realized_vol ?? 0) > (latestPnlPoint?.target_vol ?? 0.15)
                    ? 'text-red-400' : 'text-green-400'
                }`}>{((latestPnlPoint?.realized_vol ?? 0) * 100).toFixed(1)}%</span>
              </div>
              {pctBar(
                (latestPnlPoint?.realized_vol ?? 0) * 100,
                (latestPnlPoint?.target_vol ?? sizing?.target_vol ?? 0.15) * 200,
                (latestPnlPoint?.realized_vol ?? 0) > (latestPnlPoint?.target_vol ?? 0.15)
                  ? 'bg-red-500' : 'bg-green-500',
              )}
              <div className="flex justify-between text-[10px] text-gray-500">
                <span>Target Vol</span>
                <span className="font-mono text-purple-400">{((latestPnlPoint?.target_vol ?? sizing?.target_vol ?? 0) * 100).toFixed(1)}%</span>
              </div>
            </div>

            {/* Summary stats */}
            <div className="grid grid-cols-3 gap-2 text-xs">
              <div>
                <span className="text-gray-500">Equity</span>
                <p className={`font-mono ${
                  (latestPnlPoint?.equity ?? 0) >= (pnlPoints[0]?.equity ?? 0)
                    ? 'text-green-400' : 'text-red-400'
                }`}>${(latestPnlPoint?.equity ?? 0).toFixed(2)}</p>
              </div>
              <div>
                <span className="text-gray-500">Vol Scale</span>
                <p className="text-white font-mono">{(sizing?.vol_scale ?? 1).toFixed(2)}×</p>
              </div>
              <div>
                <span className="text-gray-500">Kelly Util</span>
                <p className="text-white font-mono">{(sizing?.kelly_utilization_pct ?? 0).toFixed(0)}%</p>
              </div>
            </div>

            {/* Risk-adj metrics */}
            {sizing && (
              <div className="flex items-center gap-3 text-[10px] pt-1 border-t border-slate-800 flex-wrap">
                <span className="text-gray-500">Risk-Adj:</span>
                <span>Sharpe <span className="font-mono text-blue-400">{(sizing.sharpe_ratio ?? 0).toFixed(2)}</span></span>
                <span>Sortino <span className="font-mono text-purple-400">{(sizing.sortino_ratio ?? 0).toFixed(2)}</span></span>
                <span>Calmar <span className="font-mono text-teal-400">{(sizing.calmar_ratio ?? 0).toFixed(2)}</span></span>
                <span>WR <span className="font-mono text-white">{(sizing.win_rate_pct ?? 0).toFixed(0)}%</span></span>
                <span>PF <span className="font-mono text-white">{(sizing.profit_factor ?? 0).toFixed(2)}</span></span>
              </div>
            )}
          </>
        ) : (
          <div className="flex flex-col items-center justify-center h-24 gap-2 text-xs text-gray-500">
            <TrendingUp className="w-6 h-6 opacity-30" />
            No PnL history yet — trades will populate this chart
          </div>
        )}
      </div>
    </div>
  );
}
