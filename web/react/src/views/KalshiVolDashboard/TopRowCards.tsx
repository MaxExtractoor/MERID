/**
 * VolDashboardTopRow - Top row cards for volatility dashboard
 * 
 * Contains Venue & Mode Card, Volatility Targeting Card, and Risk Limits Card.
 * 
 * Tier 4: KalshiVolDashboardView.tsx Split (929→4 files)
 */

import { Wifi, Shield, AlertTriangle, WifiOff, ShieldOff, Target } from '../../ui/icons';
import type { KalshiRiskSummary, SizingMetrics } from '../../types/kalshi';
import type { VolDashHealthStatus } from './types';
import { TIER_COLORS } from './types';

// Progress bar component (moved from types.ts to avoid JSX in .ts file)
export function pctBar(value: number, max: number, color: string) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

interface TopRowCardsProps {
  health: VolDashHealthStatus | undefined;
  risk: KalshiRiskSummary | undefined;
  sizing: SizingMetrics | undefined;
  killActive: boolean;
  canTrade: boolean;
  killReason: string | null;
  currentMode: string;
  isConnected: boolean;
  healthColor: string;
  gridAgentCount: number;
  assetExposure: Array<{ asset: string; notional: number; cap: number }>;
}

export function TopRowCards({
  health,
  risk,
  sizing,
  killActive,
  canTrade,
  killReason,
  currentMode,
  isConnected,
  healthColor,
  gridAgentCount,
  assetExposure,
}: TopRowCardsProps) {
  const tierStyle = TIER_COLORS[sizing?.drawdown_tier ?? 'normal'] ?? TIER_COLORS.normal;
  const dailyPnlUsd = typeof risk?.daily_pnl_usd === 'number'
    ? risk.daily_pnl_usd
    : (typeof risk?.daily_total_pnl_usd === 'number' ? risk.daily_total_pnl_usd : 0);
  const drawdownPct = typeof risk?.drawdown_pct === 'number' ? risk.drawdown_pct : 0;
  const totalNotionalUsd = typeof risk?.total_notional_usd === 'number' ? risk.total_notional_usd : 0;
  const maxDailyLoss = risk?.limits?.max_daily_loss_usd ?? 500;
  const maxNotional = risk?.limits?.max_notional_usd ?? 10000;
  const drawdownHalt = (risk?.limits?.drawdown_halt_pct ?? 0.15) * 100;

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {/* 1. Venue & Mode Card */}
      <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 space-y-3">
        <div className="flex items-center gap-2">
          {isConnected ? <Wifi className="w-4 h-4 text-green-400" /> : <WifiOff className="w-4 h-4 text-red-400" />}
          <h3 className="text-sm font-medium text-gray-300">Venue Status</h3>
          <span className="ml-auto text-xs font-bold">{healthColor.replace('text-', '').toUpperCase()}</span>
        </div>

        {/* Trading gate status */}
        {killActive || !canTrade ? (
          <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-red-500/20 border border-red-500/30 text-[10px] text-red-400 font-medium">
            <ShieldOff className="w-3 h-3 shrink-0" />
            Kill switch — {killReason ?? risk?.kill_switch_reason ?? 'manual'}
          </div>
        ) : (
          <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-green-500/10 border border-green-500/20 text-[10px] text-green-400">
            <Shield className="w-3 h-3 shrink-0" />
            Trading enabled — {currentMode?.toUpperCase?.() ?? 'UNKNOWN'} mode
          </div>
        )}

        <div className="grid grid-cols-2 gap-2 text-xs">
          <div>
            <span className="text-gray-500">WS Events</span>
            <p className="text-white font-mono">{health?.ws?.events_forwarded?.toLocaleString() ?? 0}</p>
          </div>
          <div>
            <span className="text-gray-500">Tickers</span>
            <p className="text-white font-mono">{health?.ws?.subscribed_tickers ?? 0}</p>
          </div>
          <div>
            <span className="text-gray-500">Rate /min</span>
            <p className={`font-mono ${
              (health?.rate_limits?.orders_this_minute ?? 0) >= 25 ? 'text-red-400' :
              (health?.rate_limits?.orders_this_minute ?? 0) >= 15 ? 'text-yellow-400' : 'text-white'
            }`}>
              {health?.rate_limits?.orders_this_minute ?? 0}/{health?.rate_limits?.max_per_minute ?? 30}
            </p>
          </div>
          <div>
            <span className="text-gray-500">Markets</span>
            <p className="text-white font-mono">{health?.catalog?.market_count ?? 0}</p>
          </div>
          <div>
            <span className="text-gray-500">Agents</span>
            <p className="text-white font-mono">{gridAgentCount} active</p>
          </div>
          <div>
            <span className="text-gray-500">Daily Trades</span>
            <p className="text-white font-mono">{risk?.daily_trades ?? 0}</p>
          </div>
        </div>

        {/* Hourly rate bar */}
        <div className="space-y-0.5">
          <div className="flex justify-between text-[10px] text-gray-500">
            <span>Orders/hr</span>
            <span>{health?.rate_limits?.orders_this_hour ?? 0} / {health?.rate_limits?.max_per_hour ?? 1800}</span>
          </div>
          {pctBar(
            health?.rate_limits?.orders_this_hour ?? 0,
            health?.rate_limits?.max_per_hour ?? 1800,
            (health?.rate_limits?.orders_this_hour ?? 0) >= 1440 ? 'bg-red-500' : 'bg-cyan-500',
          )}
        </div>

        {health?.issues && health.issues.length > 0 && (
          <div className="flex items-start gap-1.5 text-[10px] text-yellow-400">
            <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />
            <span>{health.issues.slice(0, 2).join(' · ')}</span>
          </div>
        )}
      </div>

      {/* 2. Volatility Targeting Card */}
      <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 space-y-3">
        <div className="flex items-center gap-2">
          <Target className="w-4 h-4 text-purple-400" />
          <h3 className="text-sm font-medium text-gray-300">Vol Targeting</h3>
          {sizing && (
            <span className={`ml-auto px-2 py-0.5 rounded text-[10px] font-bold ${tierStyle.text} ${tierStyle.bg}`}>
              {(sizing?.drawdown_tier ?? 'normal').toUpperCase()}
            </span>
          )}
        </div>

        {sizing ? (
          <>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div>
                <span className="text-gray-500">Target Vol</span>
                <p className="text-white font-mono">{((sizing.target_vol ?? 0) * 100).toFixed(1)}%</p>
              </div>
              <div>
                <span className="text-gray-500">Realized Vol</span>
                <p className={`font-mono ${(sizing.realized_vol ?? 0) > (sizing.target_vol ?? 0) ? 'text-red-400' : 'text-green-400'}`}>
                  {((sizing.realized_vol ?? 0) * 100).toFixed(1)}%
                </p>
              </div>
              <div>
                <span className="text-gray-500">Kelly f</span>
                <p className="text-white font-mono">{(sizing.kelly_fraction ?? 0).toFixed(3)}</p>
              </div>
              <div>
                <span className="text-gray-500">Kelly Util</span>
                <p className="text-white font-mono">{(sizing.kelly_utilization_pct ?? 0).toFixed(0)}%</p>
              </div>
              <div>
                <span className="text-gray-500">Vol Scale</span>
                <p className="text-white font-mono">{(sizing.vol_scale ?? 0).toFixed(2)}×</p>
              </div>
              <div>
                <span className="text-gray-500">ATR</span>
                <p className="text-white font-mono">{(sizing.atr_value ?? 0).toFixed(0)}</p>
              </div>
            </div>

            <div className="space-y-1">
              <div className="flex justify-between text-[10px]">
                <span className="text-gray-500">Effective Fraction</span>
                <span className="text-white font-mono">{((sizing.effective_fraction ?? 0) * 100).toFixed(2)}%</span>
              </div>
              {pctBar((sizing.effective_fraction ?? 0) * 100, 5, 'bg-purple-500')}
            </div>
          </>
        ) : (
          <p className="text-xs text-gray-500">Loading sizing data...</p>
        )}
      </div>

      {/* 3. Risk Limits Card */}
      <div className="bg-slate-900 rounded-xl p-4 border border-slate-800 space-y-3">
        <div className="flex items-center gap-2">
          <Shield className={`w-4 h-4 ${risk?.kill_switch_active ? 'text-red-400' : 'text-green-400'}`} />
          <h3 className="text-sm font-medium text-gray-300">Risk Limits</h3>
        </div>

        {risk ? (
          <>
            {/* Daily PnL gauge */}
            <div className="space-y-1">
              <div className="flex justify-between text-xs">
                <span className="text-gray-500">Daily PnL</span>
                <span className={`font-mono ${dailyPnlUsd >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  ${(dailyPnlUsd ?? 0).toFixed(2)}
                  <span className="text-gray-600 ml-1">/ -${(maxDailyLoss ?? 0).toFixed(0)}</span>
                </span>
              </div>
              {pctBar(
                Math.abs(dailyPnlUsd),
                maxDailyLoss,
                dailyPnlUsd >= 0 ? 'bg-green-500' : 'bg-red-500',
              )}
            </div>

            {/* Drawdown gauge */}
            <div className="space-y-1">
              <div className="flex justify-between text-xs">
                <span className="text-gray-500">Drawdown</span>
                <span className={`font-mono ${drawdownPct < 5 ? 'text-green-400' : drawdownPct < 10 ? 'text-yellow-400' : 'text-red-400'}`}>
                  {(drawdownPct ?? 0).toFixed(1)}%
                  <span className="text-gray-600 ml-1">/ {(drawdownHalt ?? 0).toFixed(0)}% halt</span>
                </span>
              </div>
              {pctBar(drawdownPct, drawdownHalt, 'bg-orange-500')}
            </div>

            {/* Notional gauge */}
            <div className="space-y-1">
              <div className="flex justify-between text-xs">
                <span className="text-gray-500">Notional</span>
                <span className="text-white font-mono">${(totalNotionalUsd ?? 0).toFixed(0)}
                  <span className="text-gray-600 ml-1">/ ${(maxNotional ?? 0).toFixed(0)}</span>
                </span>
              </div>
              {pctBar(totalNotionalUsd, maxNotional, 'bg-blue-500')}
            </div>

            {/* Per-asset exposure */}
            {assetExposure.length > 0 && (
              <div className="space-y-1.5 pt-1">
                <span className="text-[10px] text-gray-500 uppercase tracking-wider">Per-Asset Exposure</span>
                {assetExposure.map(a => (
                  <div key={a.asset} className="flex items-center gap-2 text-[10px]">
                    <span className="text-gray-400 w-14 capitalize">{a.asset}</span>
                    <div className="flex-1">
                      {pctBar(a.notional, a.cap, 'bg-cyan-500')}
                    </div>
                    <span className="text-gray-500 font-mono w-16 text-right">${(a.notional ?? 0).toFixed(0)}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        ) : (
          <p className="text-xs text-gray-500">Loading risk data...</p>
        )}
      </div>
    </div>
  );
}
