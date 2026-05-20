/**
 * VolDashboardBottomRow - Bottom row panels for volatility dashboard
 * 
 * Contains Volume & Alerts Panel and AI Insights + Consensus Signals.
 * 
 * Tier 4: KalshiVolDashboardView.tsx Split (929→4 files)
 */

import { AlertCircle, AlertTriangle, Activity, Zap, Bot } from '../../ui/icons';
import { fmtTimestamp } from '../../utils/formatters';
import KalshiInsightsPanel from '../../components/KalshiInsightsPanel';
import type { LiquidityAlertData, VolumeChange, VolumeAnomaly } from './types';

interface BottomRowPanelsProps {
  alertTab: 'alerts' | 'liq-alerts' | 'changes' | 'anomalies';
  setAlertTab: (tab: 'alerts' | 'liq-alerts' | 'changes' | 'anomalies') => void;
  alerts: LiquidityAlertData[];
  liqAlerts: LiquidityAlertData[];
  volChanges: VolumeChange[];
  volAnomalies: VolumeAnomaly[];
  consensusSigs: Array<{ ticker: string; direction: string; confidence: number; vote_count: number; agents: string[] }>;
  consensusRate: number;
}

export function BottomRowPanels({
  alertTab,
  setAlertTab,
  alerts,
  liqAlerts,
  volChanges,
  volAnomalies,
  consensusSigs,
  consensusRate,
}: BottomRowPanelsProps) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* 6. Volume & Alerts Panel */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
        {/* Tab bar */}
        <div className="flex items-center gap-0 border-b border-slate-800">
          {([
            { id: 'alerts' as const, label: 'Vol Alerts', icon: AlertCircle, count: alerts.length },
            { id: 'liq-alerts' as const, label: 'Liq Alerts', icon: AlertTriangle, count: liqAlerts.length },
            { id: 'changes' as const, label: 'Changes', icon: Activity, count: volChanges.length },
            { id: 'anomalies' as const, label: 'Anomalies', icon: Zap, count: volAnomalies.length },
          ]).map(t => (
            <button
              key={t.id}
              type="button"
              onClick={() => setAlertTab(t.id)}
              className={`flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium border-b-2 transition-colors ${
                alertTab === t.id
                  ? 'border-orange-400 text-orange-400'
                  : 'border-transparent text-gray-500 hover:text-gray-300'
              }`}
            >
              <t.icon className="w-3 h-3" />
              {t.label}
              {t.count > 0 && (
                <span className="px-1 py-0.5 rounded text-[9px] bg-slate-700 text-gray-400">{t.count}</span>
              )}
            </button>
          ))}
        </div>

        <div className="max-h-[240px] overflow-y-auto divide-y divide-slate-800/50">
          {/* Liquidity Alerts tab */}
          {alertTab === 'alerts' && (
            alerts.length === 0 ? (
              <div className="px-4 py-6 text-center text-xs text-gray-500">No liquidity alerts. Book health is good.</div>
            ) : (
              alerts.slice(-30).reverse().map((a) => (
                <div key={`${a.market_id}:${a.ts}:${a.kind}`} className="px-4 py-2 flex items-start gap-2">
                  <AlertTriangle className={`w-3 h-3 mt-0.5 shrink-0 ${a.severity === 'critical' ? 'text-red-400' : 'text-yellow-400'}`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-mono text-gray-400">{a.market_id}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                        a.kind === 'wide_spread' ? 'bg-orange-500/20 text-orange-400' :
                        a.kind === 'thin_book' ? 'bg-red-500/20 text-red-400' :
                        a.kind === 'spread_spike' ? 'bg-yellow-500/20 text-yellow-400' :
                        'bg-blue-500/20 text-blue-400'
                      }`}>{(a.kind ?? '').replace('_', ' ')}</span>
                    </div>
                    <p className="text-[11px] text-gray-400 mt-0.5">{a.msg}</p>
                  </div>
                  <span className="text-[10px] text-gray-600 shrink-0">{fmtTimestamp(a.ts * 1000, { timeOnly: true })}</span>
                </div>
              ))
            )
          )}

          {/* Liquidity Alerts tab */}
          {alertTab === 'liq-alerts' && (
            liqAlerts.length === 0 ? (
              <div className="px-4 py-6 text-center text-xs text-gray-500">No liquidity alerts active.</div>
            ) : (
              liqAlerts.slice(-30).reverse().map((a) => (
                <div key={`${a.market_id}:${a.ts}:${a.kind}`} className="px-4 py-2 flex items-start gap-2">
                  <AlertTriangle className={`w-3 h-3 mt-0.5 shrink-0 ${a.severity === 'critical' ? 'text-red-400' : 'text-yellow-400'}`} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-mono text-gray-400">{a.market_id}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                        a.severity === 'critical' ? 'bg-red-500/20 text-red-400' :
                        'bg-yellow-500/20 text-yellow-400'
                      }`}>{(a.kind ?? '').replace(/_/g, ' ')}</span>
                    </div>
                    <p className="text-[11px] text-gray-400 mt-0.5">{a.msg}</p>
                  </div>
                  <span className="text-[10px] text-gray-600 shrink-0">{fmtTimestamp(a.ts * 1000, { timeOnly: true })}</span>
                </div>
              ))
            )
          )}

          {/* Volume Changes tab */}
          {alertTab === 'changes' && (
            volChanges.length === 0 ? (
              <div className="px-4 py-6 text-center text-xs text-gray-500">No volume changes detected.</div>
            ) : (
              volChanges.slice(0, 30).map((c) => (
                <div key={`${c.ticker}:${c.ts}`} className="px-4 py-2 flex items-center gap-3">
                  <Activity className={`w-3 h-3 shrink-0 ${c.direction === 'up' ? 'text-green-400' : 'text-red-400'}`} />
                  <span className="text-[10px] font-mono text-white w-28 truncate">{c.ticker}</span>
                  <span className={`text-[10px] font-mono font-bold ${
                    c.direction === 'up' ? 'text-green-400' : 'text-red-400'
                  }`}>
                    {c.direction === 'up' ? '+' : ''}{(c.change_pct ?? 0).toFixed(1)}%
                  </span>
                  <span className="text-[10px] text-gray-500 ml-auto">
                    {(c.curr_volume ?? 0).toLocaleString()} ct
                  </span>
                  <span className="text-[10px] text-gray-600">{new Date(c.ts).toLocaleTimeString()}</span>
                </div>
              ))
            )
          )}

          {/* Volume Anomalies tab */}
          {alertTab === 'anomalies' && (
            volAnomalies.length === 0 ? (
              <div className="px-4 py-6 text-center text-xs text-gray-500">No volume anomalies detected.</div>
            ) : (
              volAnomalies.slice(0, 30).map((a) => (
                <div key={`${a.ticker}:${a.ts}:${a.severity}`} className="px-4 py-2 flex items-center gap-3">
                  <Zap className={`w-3 h-3 shrink-0 ${
                    a.severity === 'high' ? 'text-red-400' :
                    a.severity === 'medium' ? 'text-yellow-400' : 'text-blue-400'
                  }`} />
                  <span className="text-[10px] font-mono text-white w-28 truncate">{a.ticker}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                    a.severity === 'high' ? 'bg-red-500/20 text-red-400' :
                    a.severity === 'medium' ? 'bg-yellow-500/20 text-yellow-400' :
                    'bg-blue-500/20 text-blue-400'
                  }`}>{a.severity}</span>
                  <span className="text-[10px] text-gray-400 font-mono">z={(a.z_score ?? 0).toFixed(1)}</span>
                  <span className="text-[10px] text-gray-500 ml-auto">{(a.volume ?? 0).toLocaleString()} ct</span>
                  <span className="text-[10px] text-gray-600">{new Date(a.ts).toLocaleTimeString()}</span>
                </div>
              ))
            )
          )}
        </div>
      </div>

      {/* 7. AI Insights + Consensus Signals */}
      <div className="space-y-4">
        <KalshiInsightsPanel />

        {/* Consensus Signals from swarm */}
        {consensusSigs.length > 0 && (
          <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
            <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800">
              <Bot className="w-4 h-4 text-violet-400" />
              <h3 className="text-sm font-medium text-gray-300">Swarm Consensus Signals</h3>
              <span className="ml-auto text-[10px] text-gray-500">
                {consensusSigs.length} active · {((consensusRate ?? 0) * 100).toFixed(0)}% rate
              </span>
            </div>
            <div className="divide-y divide-slate-800/50 max-h-[200px] overflow-y-auto">
              {consensusSigs.slice(0, 10).map((sig) => (
                <div key={sig.ticker} className="px-4 py-2 flex items-center gap-3">
                  <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                    sig.direction === 'bullish' ? 'bg-green-400' :
                    sig.direction === 'bearish' ? 'bg-red-400' : 'bg-gray-500'
                  }`} />
                  <span className="text-[11px] font-mono text-white truncate flex-1">{sig.ticker}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                    sig.direction === 'bullish' ? 'bg-green-500/20 text-green-400' :
                    sig.direction === 'bearish' ? 'bg-red-500/20 text-red-400' :
                    'bg-slate-700 text-gray-400'
                  }`}>{sig.direction}</span>
                  <span className="text-[10px] text-gray-500 font-mono w-12 text-right">
                    {((sig.confidence ?? 0) * 100).toFixed(0)}%
                  </span>
                  <span className="text-[10px] text-gray-600 w-14 text-right">
                    {sig.vote_count} vote{sig.vote_count !== 1 ? 's' : ''}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
