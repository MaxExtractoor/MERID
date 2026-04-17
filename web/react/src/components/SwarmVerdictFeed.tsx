/**
 * SwarmVerdictFeed — Real-time rolling log of swarm consensus verdicts.
 *
 * Polls /api/v1/kalshi/swarm/verdicts (newest-first) and renders each
 * READY consensus as a compact card showing direction, probability,
 * confidence, size band, agents, and rationale.
 *
 * Designed to slot into any sidebar or dashboard column.
 */

import React from 'react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

// ── Types ─────────────────────────────────────

interface SwarmVerdict {
  ts: string;
  asset: string;
  timeframe: string;
  /** "bullish" | "bearish" | "neutral" — mapped from yes/no/neutral by the API */
  direction: string;
  /** 0–1 decimal probability (e.g. 0.63 = 63 %) */
  probability: number;
  /** 0–1 decimal confidence (e.g. 0.72 = 72 %) */
  confidence: number;
  /** "small" | "reduced" | "base" | "large" | "halted" */
  size_band: string;
  /** List of contributing agent IDs */
  agents: string[];
  rationale: string;
}

interface VerdictsResponse {
  verdicts: SwarmVerdict[];
  count: number;
}

// ── Helpers ───────────────────────────────────

function directionColors(direction: string): string {
  const d = (direction ?? '').toLowerCase();
  if (d === 'bullish' || d === 'yes') return 'text-emerald-400 bg-emerald-400/10';
  if (d === 'bearish' || d === 'no')  return 'text-red-400 bg-red-400/10';
  return 'text-gray-400 bg-gray-400/10';
}

function directionLabel(direction: string): string {
  const d = (direction ?? '').toLowerCase();
  if (d === 'bullish' || d === 'yes') return 'YES';
  if (d === 'bearish' || d === 'no')  return 'NO';
  return 'HOLD';
}

/** size_band values: "small" | "reduced" | "base" | "large" | "halted" */
function sizeBandColor(band: string): string {
  switch ((band || '').toLowerCase()) {
    case 'large':   return 'text-amber-400';
    case 'base':    return 'text-blue-400';
    case 'reduced': return 'text-slate-300';
    case 'small':   return 'text-slate-500';
    case 'halted':  return 'text-red-500';
    default:        return 'text-gray-400';
  }
}

function confBar(conf: number): string {
  // conf is 0–1 (e.g. 0.72 = 72 %)
  const filled = Math.round(conf * 5);
  return '▓'.repeat(filled) + '░'.repeat(5 - filled);
}

function timeAgo(ts: string): string {
  const ms = Date.now() - new Date(ts).getTime();
  const s = Math.floor(ms / 1000);
  if (s < 60)  return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60)  return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24)  return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// ── Component ─────────────────────────────────

interface SwarmVerdictFeedProps {
  maxItems?: number;
  compact?: boolean;   // true → single-line cards for sidebar use
}

const SwarmVerdictFeed: React.FC<SwarmVerdictFeedProps> = ({
  maxItems = 10,
  compact = false,
}) => {
  const { data, loading } = useApiData<VerdictsResponse>(
    API_ENDPOINTS.SWARM_VERDICTS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST },
  );

  const verdicts = (data?.verdicts ?? []).slice(0, maxItems);

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-gray-300 uppercase tracking-wider">
            Swarm Verdict Feed
          </span>
          {loading && (
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
          )}
        </div>
        <span className="text-xs text-gray-500">{verdicts.length} verdicts</span>
      </div>

      {/* Feed */}
      {verdicts.length === 0 ? (
        <div className="px-4 py-6 text-center text-gray-500 text-xs">
          {loading ? 'Loading…' : 'No verdicts yet — swarm forming consensus.'}
        </div>
      ) : (
        <div className="divide-y divide-slate-800/60">
          {verdicts.map((v) => {
            const stableKey = `${v.ts}-${v.asset}-${v.timeframe}`;
            return compact
              ? <CompactVerdictRow key={stableKey} v={v} />
              : <VerdictCard key={stableKey} v={v} />;
          })}
        </div>
      )}
    </div>
  );
};

// ── Full card (dashboard) ──────────────────────

const VerdictCard: React.FC<{ v: SwarmVerdict }> = ({ v }) => (
  <div className="px-4 py-3 hover:bg-slate-800/40 transition-colors">
    {/* Row 1: asset + timeframe + direction badge + time */}
    <div className="flex items-center justify-between mb-1.5">
      <div className="flex items-center gap-2">
        <span className="text-sm font-bold text-white">
          {(v.asset ?? '').toUpperCase()}
          <span className="text-gray-500 font-normal ml-1">{v.timeframe}</span>
        </span>
        <span className={`px-1.5 py-0.5 rounded text-xs font-bold ${directionColors(v.direction)}`}>
          {directionLabel(v.direction)}
        </span>
      </div>
      <span className="text-xs text-gray-500">{timeAgo(v.ts)}</span>
    </div>

    {/* Row 2: metrics */}
    <div className="flex items-center gap-3 text-xs mb-1.5">
      <span className="text-gray-300">
        P(YES) <span className="font-semibold text-white">{((v.probability ?? 0) * 100).toFixed(1)}%</span>
      </span>
      <span className="text-gray-500">·</span>
      <span className="font-mono text-gray-400" title={`Confidence: ${((v.confidence ?? 0) * 100).toFixed(0)}%`}>{confBar(v.confidence ?? 0)}</span>
      <span className="text-gray-300">
        <span className="font-semibold text-white">{((v.confidence ?? 0) * 100).toFixed(0)}%</span> conf
      </span>
      <span className="text-gray-500">·</span>
      <span className={`font-semibold ${sizeBandColor(v.size_band)}`}>
        {v.size_band || '—'}
      </span>
      <span className="text-gray-500">·</span>
      <span className="text-gray-400">{Array.isArray(v.agents) ? v.agents.length : 0}A</span>
    </div>

    {/* Row 3: rationale */}
    {v.rationale && (
      <p className="text-xs text-gray-500 leading-snug truncate" title={v.rationale}>
        {v.rationale}
      </p>
    )}
  </div>
);

// ── Compact row (sidebar) ──────────────────────

const CompactVerdictRow: React.FC<{ v: SwarmVerdict }> = ({ v }) => (
  <div className="flex items-center gap-2 px-3 py-2 hover:bg-slate-800/40 transition-colors text-xs">
    <span className={`px-1 py-0.5 rounded font-bold text-[10px] ${directionColors(v.direction)}`}>
      {directionLabel(v.direction)}
    </span>
    <span className="font-semibold text-white">{(v.asset ?? '').toUpperCase()}</span>
    <span className="text-gray-500">{v.timeframe}</span>
    <span className="text-gray-300 ml-1">{((v.probability ?? 0) * 100).toFixed(0)}%</span>
    <span className={`ml-auto font-semibold ${sizeBandColor(v.size_band)}`}>{v.size_band}</span>
    <span className="text-gray-600">{timeAgo(v.ts)}</span>
  </div>
);

export default SwarmVerdictFeed;
