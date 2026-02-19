/**
 * RegimeTagCloud — Grouped regime tags with category badges and confidence bars.
 *
 * Renders hypothesis regime tags grouped by category (macro/regime, policy,
 * micro/idiosyncratic, crypto/narrative, infra/incident) with confidence
 * indicators and hypothesis counts per tag.
 */

import { Tag, Layers } from 'lucide-react';

/* ── Types ────────────────────────────────────────────────── */

export interface RegimeTagEntry {
  category: string;
  label: string;
  description: string;
  confidence: number;
  count: number;
  status: string;
}

interface RegimeTagCloudProps {
  tags: RegimeTagEntry[];
}

/* ── Category styling ─────────────────────────────────────── */

const CATEGORY_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  'macro/regime':         { bg: 'bg-blue-500/10',   text: 'text-blue-400',   border: 'border-blue-500/20' },
  'policy':              { bg: 'bg-purple-500/10',  text: 'text-purple-400', border: 'border-purple-500/20' },
  'micro/idiosyncratic': { bg: 'bg-emerald-500/10', text: 'text-emerald-400', border: 'border-emerald-500/20' },
  'crypto/narrative':    { bg: 'bg-amber-500/10',   text: 'text-amber-400',  border: 'border-amber-500/20' },
  'infra/incident':      { bg: 'bg-rose-500/10',    text: 'text-rose-400',   border: 'border-rose-500/20' },
};

function getCategoryStyle(category: string) {
  return CATEGORY_STYLES[category] ?? { bg: 'bg-slate-500/10', text: 'text-slate-400', border: 'border-slate-500/20' };
}

/* ── Confidence bar ───────────────────────────────────────── */

function ConfidenceMini({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 70 ? 'bg-emerald-500' : pct >= 40 ? 'bg-amber-500' : 'bg-rose-500';
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-12 h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-slate-500 tabular-nums">{pct}%</span>
    </div>
  );
}

/* ── Tag pill ─────────────────────────────────────────────── */

function TagPill({ tag }: { tag: RegimeTagEntry }) {
  const style = getCategoryStyle(tag.category);
  const isBroken = tag.status === 'broken';
  return (
    <div
      className={`
        inline-flex items-center gap-2 px-2.5 py-1.5 rounded-lg border
        ${isBroken ? 'bg-slate-800/50 border-slate-700/30 opacity-60' : `${style.bg} ${style.border}`}
      `}
      title={tag.description}
    >
      <Tag className={`w-3 h-3 ${isBroken ? 'text-slate-600' : style.text}`} />
      <span className={`text-xs font-medium ${isBroken ? 'text-slate-500 line-through' : style.text}`}>
        {tag.label}
      </span>
      {tag.count > 1 && (
        <span className="text-[10px] text-slate-500 bg-slate-700/50 px-1 py-0.5 rounded">
          ×{tag.count}
        </span>
      )}
      <ConfidenceMini value={tag.confidence} />
    </div>
  );
}

/* ── Main component ───────────────────────────────────────── */

export default function RegimeTagCloud({ tags }: RegimeTagCloudProps) {
  if (tags.length === 0) {
    return (
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-6 text-center">
        <Layers className="w-8 h-8 text-slate-600 mx-auto mb-2" />
        <p className="text-sm text-slate-500">No regime tags available</p>
      </div>
    );
  }

  // Group by category
  const grouped = tags.reduce<Record<string, RegimeTagEntry[]>>((acc, t) => {
    const cat = t.category || 'uncategorized';
    (acc[cat] ??= []).push(t);
    return acc;
  }, {});

  const categories = Object.keys(grouped).sort();

  return (
    <div className="space-y-3">
      {categories.map(cat => {
        const style = getCategoryStyle(cat);
        const catTags = grouped[cat];
        return (
          <div key={cat}>
            <div className="flex items-center gap-2 mb-2">
              <span className={`text-xs font-semibold uppercase tracking-wider ${style.text}`}>
                {cat}
              </span>
              <span className="text-[10px] text-slate-600">
                {catTags.length} tag{catTags.length !== 1 ? 's' : ''}
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              {catTags
                .sort((a, b) => b.confidence - a.confidence)
                .map((t, i) => <TagPill key={`${t.label}-${i}`} tag={t} />)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
