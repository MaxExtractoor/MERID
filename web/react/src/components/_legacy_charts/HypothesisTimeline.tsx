/**
 * HypothesisTimeline — Chronological actions log with confidence-change sparklines.
 *
 * Renders a vertical timeline of cognitive actions (created, broken, retired,
 * confidence_adjusted, evidence_added, etc.) with inline confidence delta
 * indicators and actor attribution.
 */

import { useState } from 'react';
import {
  Plus, XCircle, Archive, TrendingUp, TrendingDown, FileText,
  Tag, ChevronDown, ChevronRight, Clock, User,
} from 'lucide-react';
import type { CognitiveAction } from '../../hooks/useRealityDebug';

/* ── Helpers ──────────────────────────────────────────────── */

function timeAgo(epochSec: number): string {
  const diff = Date.now() / 1000 - epochSec;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${(diff / 3600).toFixed(1)}h ago`;
  return `${(diff / 86400).toFixed(1)}d ago`;
}

/* ── Action icon + color mapping ──────────────────────────── */

const ACTION_META: Record<string, { icon: React.ElementType; color: string; label: string }> = {
  created:               { icon: Plus,         color: 'text-emerald-400', label: 'Created' },
  broken:                { icon: XCircle,      color: 'text-rose-400',    label: 'Broken' },
  retired:               { icon: Archive,      color: 'text-slate-400',   label: 'Retired' },
  confirmed:             { icon: TrendingUp,   color: 'text-blue-400',    label: 'Confirmed' },
  confidence_adjusted:   { icon: TrendingUp,   color: 'text-amber-400',   label: 'Confidence' },
  evidence_added:        { icon: FileText,     color: 'text-cyan-400',    label: 'Evidence' },
  regime_tag_changed:    { icon: Tag,          color: 'text-purple-400',  label: 'Tag Change' },
  updated:               { icon: TrendingUp,   color: 'text-blue-400',    label: 'Updated' },
};

function getActionMeta(action: string) {
  return ACTION_META[action] ?? { icon: Clock, color: 'text-slate-500', label: action };
}

/* ── Confidence delta badge ───────────────────────────────── */

function ConfidenceDelta({ oldVal, newVal }: { oldVal: number | null; newVal: number | null }) {
  if (oldVal == null || newVal == null) return null;
  const delta = newVal - oldVal;
  if (Math.abs(delta) < 0.001) return null;

  const isUp = delta > 0;
  const Icon = isUp ? TrendingUp : TrendingDown;
  const color = isUp ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' : 'text-rose-400 bg-rose-500/10 border-rose-500/20';

  return (
    <span className={`inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded border ${color}`}>
      <Icon className="w-2.5 h-2.5" />
      {isUp ? '+' : ''}{(delta * 100).toFixed(1)}%
    </span>
  );
}

/* ── Single timeline entry ────────────────────────────────── */

function TimelineEntry({ action, isLast }: { action: CognitiveAction; isLast: boolean }) {
  const meta = getActionMeta(action.action);
  const Icon = meta.icon;

  return (
    <div className="flex gap-3">
      {/* Vertical line + dot */}
      <div className="flex flex-col items-center">
        <div className={`w-6 h-6 rounded-full flex items-center justify-center bg-slate-800 border border-slate-700`}>
          <Icon className={`w-3 h-3 ${meta.color}`} />
        </div>
        {!isLast && <div className="w-px flex-1 bg-slate-700/50 min-h-[16px]" />}
      </div>

      {/* Content */}
      <div className="pb-4 flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-xs font-semibold ${meta.color}`}>{meta.label}</span>
          <ConfidenceDelta oldVal={action.old_confidence} newVal={action.new_confidence} />
          <span className="text-[10px] text-slate-600 ml-auto shrink-0">{timeAgo(action.created_at)}</span>
        </div>

        <p className="text-xs text-slate-300 mt-0.5 leading-relaxed truncate">{action.detail}</p>

        <div className="flex items-center gap-3 mt-1 text-[10px] text-slate-500">
          <span className="truncate font-mono">{action.market_id}</span>
          {action.actor && (
            <span className="flex items-center gap-0.5">
              <User className="w-2.5 h-2.5" /> {action.actor}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Main component ───────────────────────────────────────── */

interface HypothesisTimelineProps {
  actions: CognitiveAction[];
  maxVisible?: number;
}

export default function HypothesisTimeline({ actions, maxVisible = 20 }: HypothesisTimelineProps) {
  const [showAll, setShowAll] = useState(false);

  if (actions.length === 0) {
    return (
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-6 text-center">
        <Clock className="w-8 h-8 text-slate-600 mx-auto mb-2" />
        <p className="text-sm text-slate-500">No cognitive actions recorded</p>
      </div>
    );
  }

  // Sort newest first
  const sorted = [...actions].sort((a, b) => b.created_at - a.created_at);
  const visible = showAll ? sorted : sorted.slice(0, maxVisible);
  const hasMore = sorted.length > maxVisible;

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <Clock className="w-4 h-4 text-blue-400" />
          Action Timeline
          <span className="text-xs text-slate-500 bg-slate-700/50 px-2 py-0.5 rounded-full">
            {sorted.length}
          </span>
        </h3>
      </div>

      <div>
        {visible.map((a, i) => (
          <TimelineEntry key={a.id} action={a} isLast={i === visible.length - 1} />
        ))}
      </div>

      {hasMore && !showAll && (
        <button
          onClick={() => setShowAll(true)}
          className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 mt-2 transition-colors"
        >
          <ChevronDown className="w-3 h-3" />
          Show {sorted.length - maxVisible} more
        </button>
      )}
      {showAll && hasMore && (
        <button
          onClick={() => setShowAll(false)}
          className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-400 mt-2 transition-colors"
        >
          <ChevronRight className="w-3 h-3" />
          Collapse
        </button>
      )}
    </div>
  );
}
