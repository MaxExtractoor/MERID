import { useState } from 'react';
import { Clock, ShieldOff, Zap, RefreshCw, Radio, Settings, Filter, Lightbulb } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { DEFAULTS } from '../config/constants';
import { HelpPopover } from './HelpPopover';

interface SessionEvent {
  timestamp: number;
  category: string;
  severity: string;
  title: string;
  detail: string | null;
  hint: string | null;
  metadata: Record<string, unknown>;
}

interface SessionInfo {
  session_id: string;
  start_time: number;
  uptime_seconds: number;
  bracket: string | null;
}

interface SessionLogData {
  events: SessionEvent[];
  count: number;
  session?: SessionInfo;
}

const CATEGORY_ICONS: Record<string, typeof Clock> = {
  gate: ShieldOff,
  kill_switch: Zap,
  mode: Settings,
  reconciliation: RefreshCw,
  feed: Radio,
  system: Clock,
  operator: Settings,
};

const CATEGORY_COLORS: Record<string, string> = {
  gate: 'text-red-400',
  kill_switch: 'text-red-400',
  mode: 'text-blue-400',
  reconciliation: 'text-amber-400',
  feed: 'text-cyan-400',
  system: 'text-slate-400',
  operator: 'text-green-400',
};

const SEVERITY_STYLES: Record<string, string> = {
  critical: 'border-l-red-500 bg-red-500/5',
  warning: 'border-l-amber-500 bg-amber-500/5',
  info: 'border-l-slate-600 bg-slate-800/30',
};

const CATEGORIES = ['all', 'gate', 'kill_switch', 'mode', 'reconciliation', 'feed'] as const;

function formatTimestamp(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatRelative(ts: number): string {
  const ago = Math.round((Date.now() / 1000) - ts);
  if (ago < 60) return `${ago}s ago`;
  if (ago < 3600) return `${Math.round(ago / 60)}m ago`;
  return `${Math.round(ago / 3600)}h ago`;
}

export default function SessionLogPanel() {
  const [categoryFilter, setCategoryFilter] = useState<string>('all');

  const queryParam = categoryFilter === 'all' ? '' : `&category=${categoryFilter}`;
  const { data, loading, refetch } = useApiData<SessionLogData>(
    `/api/v1/system/session-log?limit=50${queryParam}`,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH },
  );

  const events = data?.events ?? [];

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-blue-400" />
          <h3 className="text-sm font-semibold text-slate-300">Session Log</h3>
          <HelpPopover title="Session Log">
            <p>Time-ordered record of safety-relevant events for this session: mode changes, kill-switch toggles, gate state transitions, feed outages, and reconciliation runs.</p>
            <p className="mt-1">Use the category filter to focus on specific event types. Events are kept for the current session only.</p>
          </HelpPopover>
        </div>
        <div className="flex items-center gap-2">
          {data?.session && (
            <span className="text-[10px] text-slate-600 font-mono" title={`Session ${data.session.session_id} started ${new Date(data.session.start_time * 1000).toLocaleTimeString()}`}>
              {data.session.session_id} · {Math.round(data.session.uptime_seconds / 60)}m
              {data.session.bracket && <span className="text-blue-400/70 ml-1">· {data.session.bracket}</span>}
            </span>
          )}
          <span className="text-[10px] text-slate-500">{events.length} events</span>
          <button
            type="button"
            onClick={() => refetch()}
            className="p-1 rounded hover:bg-slate-700 text-gray-400 hover:text-white transition-colors"
            title="Refresh"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Category filter */}
      <div className="flex items-center gap-1">
        <Filter className="w-3 h-3 text-slate-500" />
        {CATEGORIES.map(cat => (
          <button
            key={cat}
            type="button"
            onClick={() => setCategoryFilter(cat)}
            className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
              categoryFilter === cat
                ? 'bg-blue-600 text-white'
                : 'bg-slate-800 text-slate-500 hover:text-slate-300'
            }`}
          >
            {cat === 'all' ? 'All' : cat.replace('_', ' ')}
          </button>
        ))}
      </div>

      {/* Event list */}
      {events.length === 0 ? (
        <div className="text-center text-slate-600 py-6 text-xs">
          {loading ? 'Loading...' : 'No events yet this session'}
        </div>
      ) : (
        <div className="space-y-1 max-h-[300px] overflow-y-auto">
          {events.map((evt, i) => {
            const Icon = CATEGORY_ICONS[evt.category] ?? Clock;
            const iconColor = CATEGORY_COLORS[evt.category] ?? 'text-slate-400';
            const style = SEVERITY_STYLES[evt.severity] ?? SEVERITY_STYLES.info;

            return (
              <div
                key={i}
                className={`flex items-start gap-2 border-l-2 rounded-r px-2.5 py-1.5 text-[11px] ${style}`}
              >
                <Icon className={`w-3.5 h-3.5 flex-shrink-0 mt-0.5 ${iconColor}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-slate-200">{evt.title}</span>
                    <span className="text-slate-500 font-mono ml-auto flex-shrink-0" title={new Date(evt.timestamp * 1000).toISOString()}>
                      {formatTimestamp(evt.timestamp)}
                    </span>
                    <span className="text-slate-600 text-[9px]">{formatRelative(evt.timestamp)}</span>
                  </div>
                  {evt.detail && (
                    <p className="text-slate-500 truncate mt-0.5">{evt.detail}</p>
                  )}
                  {evt.hint && (
                    <div className="flex items-center gap-1 mt-0.5 text-[10px] text-blue-400/70 italic">
                      <Lightbulb className="w-2.5 h-2.5 flex-shrink-0" />
                      <span className="truncate">{evt.hint}</span>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
