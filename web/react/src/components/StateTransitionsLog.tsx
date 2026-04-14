/**
 * StateTransitionsLog — chronological list of risk state change events.
 *
 * Feeds from /api/v1/kalshi/risk/state-transitions.
 * Shows zone changes, profit-lock transitions, halt activations, etc.
 */

import { Clock, RefreshCw } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import type { StateTransition } from '../types/kalshi';

interface TransitionsResponse {
  transitions: StateTransition[];
  total: number;
}

const EVENT_COLORS: Record<string, string> = {
  zone_change:         'text-yellow-400 bg-yellow-500/10',
  profit_lock_change:  'text-blue-400   bg-blue-500/10',
  drawdown_halt:       'text-red-400    bg-red-500/10',
  kill_switch:         'text-red-500    bg-red-500/20',
  manual_halt:         'text-orange-400 bg-orange-500/10',
  current_state:       'text-slate-400  bg-slate-700/40',
};

function eventColorClass(type: string): string {
  return EVENT_COLORS[type] ?? 'text-slate-300 bg-slate-700/40';
}

function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return ts;
  }
}

interface Props {
  limit?: number;
  /** Show a compact scrollable table only (no header). */
  embedded?: boolean;
}

export function StateTransitionsLog({ limit = 30, embedded = false }: Props) {
  const { data, loading, error, refetch } = useApiData<TransitionsResponse>(
    `${API_ENDPOINTS.KALSHI_RISK_STATE_TRANSITIONS}?limit=${limit}`,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );

  const transitions = data?.transitions ?? [];

  if (!embedded) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
        <div className="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-slate-400" />
            <h3 className="text-sm font-semibold text-white">Risk State Transitions</h3>
            {data?.total != null && (
              <span className="text-xs text-slate-500">({data.total} buffered)</span>
            )}
          </div>
          <button
            type="button"
            onClick={refetch}
            className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white"
            title="Refresh"
            aria-label="Refresh transitions"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
        <TransitionTable transitions={transitions} error={error?.message} />
      </div>
    );
  }

  return <TransitionTable transitions={transitions} error={error?.message} />;
}

function TransitionTable({ transitions, error }: { transitions: StateTransition[]; error?: string }) {
  if (error) {
    return (
      <div className="px-5 py-4 text-sm text-slate-500">
        State transitions unavailable: {error}
      </div>
    );
  }

  if (transitions.length === 0) {
    return (
      <div className="px-5 py-8 text-center text-sm text-slate-600">
        No transitions recorded yet.
      </div>
    );
  }

  return (
    <div className="max-h-72 overflow-y-auto">
      <table className="w-full text-sm">
        <thead className="bg-slate-800/50 sticky top-0">
          <tr>
            <th className="px-4 py-2 text-left text-xs font-medium text-slate-400 whitespace-nowrap">Time</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-slate-400">Type</th>
            <th className="px-4 py-2 text-left text-xs font-medium text-slate-400">Detail</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/50">
          {transitions.map((t, i) => (
            <tr key={i} className="hover:bg-slate-800/30">
              <td className="px-4 py-2 text-xs text-slate-500 font-mono whitespace-nowrap">
                {formatTs(t.ts)}
              </td>
              <td className="px-4 py-2">
                <span className={`text-xs px-2 py-0.5 rounded font-medium ${eventColorClass(t.event_type)}`}>
                  {t.event_type}
                </span>
              </td>
              <td className="px-4 py-2 text-xs text-slate-300">{t.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
