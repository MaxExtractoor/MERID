/**
 * Breach & Alert Log Panel
 *
 * Table of recent risk breaches with time, rule, instrument, action,
 * severity, and value vs threshold. Polls /api/metrics/breach_log.
 */

import React from 'react';
import { ShieldAlert, AlertTriangle, AlertOctagon, Info, RefreshCw } from 'lucide-react';
import { useApiData } from '../../hooks/useApiData';

interface Breach {
  ts: string;
  rule: string;
  instrument: string;
  value: number;
  threshold: number;
  action: string;
  severity: string;
}

interface BreachAlertLogProps {
  className?: string;
  limit?: number;
}

const SEVERITY_STYLES: Record<string, { icon: typeof AlertOctagon; color: string; bg: string }> = {
  CRITICAL: { icon: AlertOctagon, color: 'text-red-400', bg: 'bg-red-500/10' },
  WARNING: { icon: AlertTriangle, color: 'text-amber-400', bg: 'bg-amber-500/10' },
  INFO: { icon: Info, color: 'text-blue-400', bg: 'bg-blue-500/10' },
};

function formatTime(ts: string): string {
  if (!ts) return '--';
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return ts.slice(11, 19);
  }
}

export function BreachAlertLog({ className = '', limit = 20 }: BreachAlertLogProps) {
  const { data: rawData, loading, refetch } = useApiData<{ breaches: Breach[]; total: number }>(
    `/api/metrics/breach_log?limit=${limit}`,
    { pollingInterval: 10000 },
  );
  const breaches = rawData?.breaches ?? [];
  const total = rawData?.total ?? 0;

  return (
    <div className={`bg-slate-900/70 rounded-xl border border-slate-800 p-4 ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 text-amber-400" />
          <h3 className="text-sm font-semibold text-slate-300">Breach & Alert Log</h3>
          {total > 0 && (
            <span className="text-[10px] bg-amber-500/20 text-amber-400 px-1.5 py-0.5 rounded-full font-medium">
              {total}
            </span>
          )}
        </div>
        <button onClick={() => refetch()} className="p-1 rounded hover:bg-slate-800" title="Refresh">
          <RefreshCw className={`w-3.5 h-3.5 text-slate-500 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Content */}
      {loading && breaches.length === 0 ? (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-10 bg-slate-800 rounded animate-pulse" />
          ))}
        </div>
      ) : breaches.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-8 text-slate-600">
          <ShieldAlert className="w-8 h-8 mb-2 opacity-30" />
          <span className="text-sm">No breaches recorded</span>
          <span className="text-[10px] mt-1">Risk controls are holding</span>
        </div>
      ) : (
        <div className="max-h-[360px] overflow-y-auto">
          <table className="w-full text-[11px]">
            <thead className="sticky top-0 bg-slate-900/95 z-10">
              <tr className="border-b border-slate-700/50">
                <th className="text-left px-2 py-1.5 text-slate-500 font-medium w-8"></th>
                <th className="text-left px-2 py-1.5 text-slate-500 font-medium">Time</th>
                <th className="text-left px-2 py-1.5 text-slate-500 font-medium">Rule</th>
                <th className="text-left px-2 py-1.5 text-slate-500 font-medium">Instrument</th>
                <th className="text-left px-2 py-1.5 text-slate-500 font-medium">Action</th>
                <th className="text-right px-2 py-1.5 text-slate-500 font-medium">Value</th>
                <th className="text-right px-2 py-1.5 text-slate-500 font-medium">Limit</th>
              </tr>
            </thead>
            <tbody>
              {breaches.map((b, i) => {
                const style = SEVERITY_STYLES[b.severity] || SEVERITY_STYLES.INFO;
                const Icon = style.icon;
                return (
                  <tr
                    key={`${b.ts}-${i}`}
                    className={`${style.bg} border-b border-slate-800/50 hover:bg-slate-700/30 transition-colors`}
                  >
                    <td className="px-2 py-1.5">
                      <Icon className={`w-3.5 h-3.5 ${style.color}`} />
                    </td>
                    <td className="px-2 py-1.5 text-slate-500 font-mono whitespace-nowrap">
                      {formatTime(b.ts)}
                    </td>
                    <td className="px-2 py-1.5 text-slate-300 font-semibold truncate max-w-[160px]">
                      {b.rule}
                    </td>
                    <td className="px-2 py-1.5 text-slate-400 truncate max-w-[100px]">
                      {b.instrument}
                    </td>
                    <td className="px-2 py-1.5">
                      <span className={`font-medium px-1.5 py-0.5 rounded text-[10px] ${
                        b.action.includes('block') || b.action.includes('halt') || b.action.includes('kill')
                          ? 'bg-red-500/20 text-red-400'
                          : b.action.includes('reduce') || b.action.includes('warn')
                          ? 'bg-amber-500/20 text-amber-400'
                          : 'bg-slate-700 text-slate-400'
                      }`}>
                        {b.action}
                      </span>
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono text-slate-400">
                      {b.value !== 0 ? b.value : '--'}
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono text-slate-500">
                      {b.threshold !== 0 ? b.threshold : '--'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
