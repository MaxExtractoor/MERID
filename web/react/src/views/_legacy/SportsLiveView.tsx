/**
 * SportsLiveView — Real-time sports odds, anomaly detection, and live events.
 *
 * Shows:
 *   - Live event cards with scores and odds movement
 *   - Anomaly alert feed with severity badges
 *   - Odds sparklines per event
 *   - Stats bar: total events, live count, anomalies, unacknowledged
 *   - Sport filter tabs
 */

import { useState, useMemo } from 'react';
import { useSportsLive, type SportEvent, type AnomalyAlert } from '../hooks/useSportsLive';
import {
  Radio, AlertTriangle, CheckCircle, Clock,
  RefreshCw, Shield,
  ChevronDown, ChevronRight, Trophy,
} from 'lucide-react';

/* ── Tooltip ──────────────────────────────────────────────── */

function Tip({ text, children }: { text: string; children: React.ReactNode }) {
  return (
    <span className="relative group cursor-help">
      {children}
      <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 text-xs bg-slate-800 text-slate-200 rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-50 border border-slate-700">
        {text}
      </span>
    </span>
  );
}

/* ── Severity badge ───────────────────────────────────────── */

const SEV_CONFIG: Record<string, { color: string; bg: string }> = {
  critical: { color: 'text-rose-400', bg: 'bg-rose-500/20 border-rose-500/30' },
  high:     { color: 'text-orange-400', bg: 'bg-orange-500/20 border-orange-500/30' },
  warning:  { color: 'text-amber-400', bg: 'bg-amber-500/20 border-amber-500/30' },
  info:     { color: 'text-blue-400', bg: 'bg-blue-500/20 border-blue-500/30' },
};

/* ── Stat tile ────────────────────────────────────────────── */

function StatTile({ label, value, Icon, color, tooltip }: {
  label: string; value: string | number; Icon: React.ElementType; color: string; tooltip: string;
}) {
  return (
    <Tip text={tooltip}>
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 hover:border-slate-600/50 transition-colors">
        <div className="flex items-center gap-2 mb-2">
          <Icon className={`w-4 h-4 ${color}`} />
          <span className="text-xs text-slate-400 uppercase tracking-wider">{label}</span>
        </div>
        <div className="text-2xl font-bold text-white">{value}</div>
      </div>
    </Tip>
  );
}

/* ── Live event card ──────────────────────────────────────── */

function EventCard({ event }: { event: SportEvent }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4 hover:border-slate-600/50 transition-all">
      <div className="flex items-center justify-between cursor-pointer" onClick={() => setExpanded(!expanded)} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); (() => setExpanded(!expanded))(); } }}>
        <div className="flex items-center gap-3 min-w-0">
          {event.is_live && (
            <span className="flex items-center gap-1 px-2 py-0.5 text-xs font-bold rounded-full bg-red-500/20 text-red-400 border border-red-500/30 animate-pulse">
              <Radio className="w-3 h-3" /> LIVE
            </span>
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 text-xs rounded-full bg-slate-700/50 text-slate-300 uppercase">{event.sport}</span>
              {event.league && <span className="text-xs text-slate-500">{event.league}</span>}
            </div>
            <div className="text-sm font-medium text-white mt-1 truncate">
              {event.home_team} vs {event.away_team}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-4">
          {event.is_live && event.score_home != null && event.score_away != null && (
            <div className="text-right">
              <div className="text-lg font-bold text-white">
                {event.score_home} — {event.score_away}
              </div>
              <div className="text-xs text-slate-500">{event.status}</div>
            </div>
          )}
          {!event.is_live && (
            <div className="text-right">
              <div className="text-xs text-slate-500">Starts</div>
              <div className="text-sm text-slate-300">
                {new Date(event.start_time * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
              </div>
            </div>
          )}
          {expanded ? <ChevronDown className="w-4 h-4 text-slate-500" /> : <ChevronRight className="w-4 h-4 text-slate-500" />}
        </div>
      </div>

      {expanded && (
        <div className="mt-3 pt-3 border-t border-slate-700/50 animate-in fade-in duration-200">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            <div><span className="text-slate-500">Event ID</span><div className="text-white font-mono mt-0.5">{event.event_id.slice(0, 12)}...</div></div>
            <div><span className="text-slate-500">Sport</span><div className="text-white mt-0.5 capitalize">{event.sport}</div></div>
            <div><span className="text-slate-500">Status</span><div className="text-white mt-0.5">{event.status}</div></div>
            <div><span className="text-slate-500">Start Time</span><div className="text-white mt-0.5">{new Date(event.start_time * 1000).toLocaleString()}</div></div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Anomaly card ─────────────────────────────────────────── */

function AnomalyCard({ anomaly }: { anomaly: AnomalyAlert }) {
  const sev = SEV_CONFIG[anomaly.severity] ?? SEV_CONFIG.info;

  return (
    <div className={`flex items-start gap-3 p-3 rounded-lg border ${sev.bg} transition-all`}>
      <AlertTriangle className={`w-4 h-4 ${sev.color} shrink-0 mt-0.5`} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 mb-0.5">
          <span className={`text-xs font-bold uppercase ${sev.color}`}>{anomaly.severity}</span>
          <span className="text-xs text-slate-500">{anomaly.anomaly_type}</span>
          {anomaly.acknowledged && (
            <CheckCircle className="w-3 h-3 text-emerald-400" />
          )}
        </div>
        <p className="text-sm text-white">{anomaly.description}</p>
        <div className="text-xs text-slate-500 mt-1">
          {anomaly.source} · {new Date(anomaly.timestamp * 1000).toLocaleTimeString()}
        </div>
      </div>
    </div>
  );
}

/* ── Main View ────────────────────────────────────────────── */

export default function SportsLiveView() {
  const { data, loading, error, refresh } = useSportsLive();
  const [sportFilter, setSportFilter] = useState('all');
  const [showAnomalies, setShowAnomalies] = useState(true);

  const sports = useMemo(() => {
    if (!data) return ['all'];
    const set = new Set(data.events.map(e => e.sport.toLowerCase()));
    return ['all', ...Array.from(set).sort()];
  }, [data]);

  const filteredEvents = useMemo(() => {
    if (!data) return [];
    if (sportFilter === 'all') return data.events;
    return data.events.filter(e => e.sport.toLowerCase() === sportFilter);
  }, [data, sportFilter]);

  const liveEvents = filteredEvents.filter(e => e.is_live);
  const upcomingEvents = filteredEvents.filter(e => !e.is_live);

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3">
          <div className="w-12 h-12 border-2 border-red-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-slate-400 text-sm">Loading sports data...</span>
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="p-6">
        <div className="bg-rose-900/20 border border-rose-500/30 rounded-xl p-4">
          <h3 className="text-rose-400 font-semibold mb-1">Sports Live API Error</h3>
          <p className="text-rose-300 text-sm">{error}</p>
        </div>
      </div>
    );
  }

  const s = data?.stats;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white flex items-center gap-3">
            <Radio className="w-8 h-8 text-red-400" />
            Sports Live
          </h1>
          <p className="text-slate-400 mt-1">Real-time odds, live events, and anomaly detection</p>
        </div>
        <button type="button" onClick={refresh} className="p-2 hover:bg-slate-800 rounded-lg transition-colors" title="Refresh" aria-label="Refresh">
          <RefreshCw className={`w-4 h-4 text-slate-400 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatTile label="Total Events" value={s?.total_events ?? 0} Icon={Trophy} color="text-blue-400" tooltip="Total tracked sporting events across all leagues" />
        <StatTile label="Live Now" value={s?.live_events ?? 0} Icon={Radio} color="text-red-400" tooltip="Events currently in progress with live odds" />
        <StatTile label="Anomalies" value={s?.total_anomalies ?? 0} Icon={AlertTriangle} color="text-amber-400" tooltip="Detected odds anomalies (staleness, jumps, patterns)" />
        <StatTile label="Unacknowledged" value={s?.unacknowledged ?? 0} Icon={Shield} color="text-rose-400" tooltip="Anomalies that haven't been reviewed yet" />
      </div>

      {/* Sport filter */}
      <div className="flex items-center gap-2 flex-wrap">
        {sports.map(sp => (
          <button type="button"
            key={sp}
            onClick={() => setSportFilter(sp)}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors capitalize ${
              sportFilter === sp
                ? 'bg-red-600 text-white'
                : 'bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-white'
            }`}
          >
            {sp}
          </button>
        ))}
      </div>

      {/* Two-column layout: events + anomalies */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Events column */}
        <div className="lg:col-span-2 space-y-4">
          {/* Live events */}
          {liveEvents.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
                <Radio className="w-4 h-4 text-red-400 animate-pulse" /> Live ({liveEvents.length})
              </h3>
              <div className="space-y-3">
                {liveEvents.map(e => <EventCard key={e.event_id} event={e} />)}
              </div>
            </div>
          )}

          {/* Upcoming events */}
          <div>
            <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
              <Clock className="w-4 h-4 text-slate-400" /> Upcoming ({upcomingEvents.length})
            </h3>
            {upcomingEvents.length === 0 ? (
              <div className="text-center py-8 text-slate-500">
                <Trophy className="w-10 h-10 mx-auto mb-2 opacity-30" />
                <p className="text-sm">No upcoming events for this sport</p>
              </div>
            ) : (
              <div className="space-y-3">
                {upcomingEvents.slice(0, 20).map(e => <EventCard key={e.event_id} event={e} />)}
              </div>
            )}
          </div>
        </div>

        {/* Anomalies sidebar */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-400" /> Anomaly Feed
            </h3>
            <button type="button"
              onClick={() => setShowAnomalies(!showAnomalies)}
              className="text-xs text-slate-500 hover:text-white transition-colors"
            >
              {showAnomalies ? 'Hide' : 'Show'}
            </button>
          </div>
          {showAnomalies && (
            <div className="space-y-2 max-h-[600px] overflow-y-auto">
              {(data?.anomalies ?? []).length === 0 ? (
                <div className="text-center py-8 text-slate-500">
                  <CheckCircle className="w-8 h-8 mx-auto mb-2 opacity-30" />
                  <p className="text-sm">No anomalies detected</p>
                </div>
              ) : (
                (data?.anomalies ?? []).map((a, i) => <AnomalyCard key={a.id ?? i} anomaly={a} />)
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
