/**
 * TickTimeline — compact live tick event timeline for OperatorDashboard.
 *
 * Shows:
 *  - Connection indicator (live / reconnecting)
 *  - Rolling stats bar (avg latency, order rate, fill rate, error rate)
 *  - Scrollable list of recent TickSummary rows
 *  - Expandable granular event sub-list per tick
 */
import { useState } from 'react';
import { Activity, Zap, Clock, Wifi, WifiOff } from '../ui/icons';
import { useTickStream, TickSummary, TickEvent } from '../hooks/useTickStream';

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatTs(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

function eventColor(event: string): string {
  switch (event) {
    case 'order_submitted': return 'text-blue-400';
    case 'fill_received': return 'text-emerald-400';
    case 'order_rejected': return 'text-amber-400';
    case 'risk_checked': return 'text-violet-400';
    case 'stop_loss_triggered': return 'text-red-400';
    case 'tick_error': return 'text-red-500';
    case 'session_gated': return 'text-slate-500';
    default: return 'text-slate-400';
  }
}

function TickSummaryRow({ summary, events }: { summary: TickSummary; events: TickEvent[] }) {
  const [expanded, setExpanded] = useState(false);
  const hasError = !!summary.error;
  const hasOrders = summary.orders_submitted > 0;
  const hasFills = summary.fills_confirmed > 0;
  const subEvents = events.filter((e) => e.tick_id === summary.tick_id && e.event !== 'tick_summary');

  return (
    <div className="border border-slate-800 rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className={`w-full flex items-center gap-2 px-3 py-2 text-xs transition-colors ${
          hasError
            ? 'bg-red-950/30 hover:bg-red-950/50'
            : hasOrders
            ? 'bg-blue-950/20 hover:bg-blue-950/40'
            : 'bg-slate-900/60 hover:bg-slate-800/60'
        }`}
      >
        {/* Status dot */}
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
          hasError ? 'bg-red-500' :
          hasFills ? 'bg-emerald-400' :
          hasOrders ? 'bg-blue-400' : 'bg-slate-600'
        }`} />

        {/* Time */}
        <span className="text-slate-500 font-mono w-[68px] shrink-0">{formatTs(summary.ts)}</span>

        {/* Agent */}
        <span className="text-slate-300 font-medium truncate max-w-[90px] shrink-0">{summary.agent_id}</span>

        {/* Mode badge */}
        <span className={`px-1 py-0.5 rounded text-[10px] font-mono shrink-0 ${
          summary.mode === 'live' ? 'bg-red-500/20 text-red-400' : 'bg-slate-700 text-slate-400'
        }`}>{summary.mode}</span>

        {/* Markets */}
        <span className="text-slate-500 shrink-0">{summary.markets_resolved}m</span>

        {/* Signals */}
        <span className="text-slate-500 shrink-0">{summary.signals_evaluated}sig</span>

        {/* Orders */}
        {hasOrders && (
          <span className="text-blue-400 font-medium shrink-0">{summary.orders_submitted}ord</span>
        )}

        {/* Fills */}
        {hasFills && (
          <span className="text-emerald-400 font-medium shrink-0">{summary.fills_confirmed}fill</span>
        )}

        {/* Risk blocked */}
        {summary.risk_blocked > 0 && (
          <span className="text-amber-400 shrink-0">{summary.risk_blocked}blk</span>
        )}

        {/* Error */}
        {hasError && (
          <span className="text-red-400 truncate ml-1 shrink">{summary.error}</span>
        )}

        {/* Latency */}
        <span className="ml-auto text-slate-600 font-mono shrink-0">{formatMs(summary.duration_ms)}</span>

        {/* Expand indicator */}
        {subEvents.length > 0 && (
          <span className="text-slate-600 shrink-0">{expanded ? '▲' : '▼'}</span>
        )}
      </button>

      {expanded && subEvents.length > 0 && (
        <div className="border-t border-slate-800 bg-slate-950/40 px-4 py-2 space-y-1">
          {subEvents.map((ev, i) => (
            <div key={i} className="flex items-center gap-2 text-[11px]">
              <span className={`font-mono w-[110px] shrink-0 ${eventColor(ev.event)}`}>{ev.event}</span>
              {ev.market_id != null && (
                <span className="text-slate-500 font-mono truncate max-w-[160px]">{String(ev.market_id)}</span>
              )}
              {ev.allowed != null && (
                <span className={ev.allowed ? 'text-emerald-500' : 'text-red-500'}>
                  {ev.allowed ? 'allowed' : 'blocked'}
                </span>
              )}
              {ev.reason != null && (
                <span className="text-slate-600 truncate">{String(ev.reason)}</span>
              )}
              {ev.contracts != null && (
                <span className="text-slate-400">x{String(ev.contracts)}</span>
              )}
              {ev.fill_price_cents != null && (
                <span className="text-slate-500">${(Number(ev.fill_price_cents) / 100).toFixed(2)}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StatsBar({ summaries }: { summaries: TickSummary[] }) {
  if (summaries.length === 0) return null;
  const n = summaries.length;
  const avgMs = summaries.reduce((s, t) => s + t.duration_ms, 0) / n;
  const totalOrders = summaries.reduce((s, t) => s + t.orders_submitted, 0);
  const totalFills = summaries.reduce((s, t) => s + t.fills_confirmed, 0);
  const errorCount = summaries.filter((t) => t.error).length;
  const errorRate = (errorCount / n) * 100;

  return (
    <div className="grid grid-cols-4 gap-2 text-center">
      <div className="bg-slate-800/60 rounded-lg py-1.5 px-2">
        <p className="text-[10px] text-slate-500 uppercase">Avg Latency</p>
        <p className="text-xs font-mono font-bold text-slate-200">{formatMs(avgMs)}</p>
      </div>
      <div className="bg-slate-800/60 rounded-lg py-1.5 px-2">
        <p className="text-[10px] text-slate-500 uppercase">Orders</p>
        <p className="text-xs font-mono font-bold text-blue-400">{totalOrders}</p>
      </div>
      <div className="bg-slate-800/60 rounded-lg py-1.5 px-2">
        <p className="text-[10px] text-slate-500 uppercase">Fills</p>
        <p className="text-xs font-mono font-bold text-emerald-400">{totalFills}</p>
      </div>
      <div className={`rounded-lg py-1.5 px-2 ${errorRate > 5 ? 'bg-red-950/40' : 'bg-slate-800/60'}`}>
        <p className="text-[10px] text-slate-500 uppercase">Err Rate</p>
        <p className={`text-xs font-mono font-bold ${errorRate > 5 ? 'text-red-400' : 'text-slate-400'}`}>
          {(errorRate ?? 0).toFixed(0)}%
        </p>
      </div>
    </div>
  );
}

export default function TickTimeline() {
  const { summaries, events, connected, lastTs } = useTickStream();
  const recentSummaries = summaries.slice(-50).reverse();

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-blue-400" />
          <h3 className="text-sm font-semibold text-slate-200">Tick Timeline</h3>
          <span className="text-xs text-slate-500">({summaries.length} ticks)</span>
        </div>
        <div className="flex items-center gap-2">
          {lastTs && (
            <span className="text-[10px] text-slate-600 font-mono flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {formatTs(lastTs)}
            </span>
          )}
          <span className={`flex items-center gap-1 text-[10px] font-medium ${
            connected ? 'text-emerald-400' : 'text-amber-400'
          }`}>
            {connected ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
            {connected ? 'Live' : 'Reconnecting…'}
          </span>
        </div>
      </div>

      {/* Stats bar */}
      <StatsBar summaries={summaries} />

      {/* Timeline */}
      <div className="max-h-[420px] overflow-y-auto space-y-1 pr-1">
        {recentSummaries.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 text-slate-600 gap-2">
            <Zap className="w-6 h-6 opacity-40" />
            <span className="text-sm">Waiting for tick data…</span>
            <span className="text-xs opacity-60">Agent cycles will appear here in real time</span>
          </div>
        ) : (
          recentSummaries.map((s) => (
            <TickSummaryRow key={s.tick_id} summary={s} events={events} />
          ))
        )}
      </div>
    </div>
  );
}
