/**
 * RealityDebugPanel — Visualizes the reality debugger output.
 *
 * Sections:
 *   - Stuck Models: markets with high Brier error and stale hypotheses
 *   - Conceptual Disagreements: agents with similar probs but different stories
 *   - Hypothesis Dynamics: per-market flip rate, rigidity, flailing flags
 */

import { useState } from 'react';
import {
  Lock, Shuffle, Users, ChevronDown, ChevronRight,
  Clock, Zap, BarChart3, ArrowRight,
} from 'lucide-react';
import type {
  RealityDebugReport,
  StuckModel,
  ConceptualDisagreement,
  HypothesisDynamics,
} from '../../hooks/useRealityDebug';

/* ── Helpers ──────────────────────────────────────────────── */

function formatLag(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}

function SeverityDot({ level }: { level: 'critical' | 'warning' | 'info' }) {
  const colors = {
    critical: 'bg-rose-500',
    warning: 'bg-amber-500',
    info: 'bg-blue-500',
  };
  return <div className={`w-2 h-2 rounded-full ${colors[level]} shrink-0`} />;
}

/* ── Collapsible section ──────────────────────────────────── */

function Section({
  title, icon: Icon, iconColor, count, children, defaultOpen = true,
}: {
  title: string;
  icon: React.ElementType;
  iconColor: string;
  count: number;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-800/80 transition-colors"
      >
        <div className="flex items-center gap-2">
          <Icon className={`w-4 h-4 ${iconColor}`} />
          <span className="text-sm font-semibold text-white">{title}</span>
          <span className="text-xs text-slate-500 bg-slate-700/50 px-2 py-0.5 rounded-full">
            {count}
          </span>
        </div>
        {open ? (
          <ChevronDown className="w-4 h-4 text-slate-500" />
        ) : (
          <ChevronRight className="w-4 h-4 text-slate-500" />
        )}
      </button>
      {open && <div className="px-4 pb-4 space-y-2">{children}</div>}
    </div>
  );
}

/* ── Stuck Model Card ─────────────────────────────────────── */

function StuckModelCard({ sm }: { sm: StuckModel }) {
  const severity = sm.brier_score >= 0.7 ? 'critical' : sm.brier_score >= 0.5 ? 'warning' : 'info';
  return (
    <div className="flex items-start gap-3 p-3 bg-slate-900/50 border border-slate-700/40 rounded-lg">
      <SeverityDot level={severity} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-sm font-medium text-white truncate">{sm.market_id}</span>
          <span className="text-xs text-rose-400 bg-rose-500/10 px-1.5 py-0.5 rounded">
            Brier {sm.brier_score.toFixed(3)}
          </span>
        </div>
        <div className="flex flex-wrap gap-3 text-xs text-slate-400">
          <span className="flex items-center gap-1">
            <Clock className="w-3 h-3" /> Lag: {formatLag(sm.lag_seconds)}
          </span>
          <span className="flex items-center gap-1">
            <Lock className="w-3 h-3" /> {sm.stale_hypotheses} stale
          </span>
          {sm.owners.length > 0 && (
            <span className="flex items-center gap-1">
              <Users className="w-3 h-3" /> {sm.owners.join(', ')}
            </span>
          )}
        </div>
        {sm.suggestion && (
          <p className="text-xs text-amber-300/80 mt-1.5 leading-relaxed">{sm.suggestion}</p>
        )}
      </div>
    </div>
  );
}

/* ── Disagreement Card ────────────────────────────────────── */

function DisagreementCard({ d }: { d: ConceptualDisagreement }) {
  return (
    <div className="p-3 bg-slate-900/50 border border-slate-700/40 rounded-lg">
      <div className="flex items-center gap-2 mb-2">
        <SeverityDot level="warning" />
        <span className="text-sm font-medium text-white truncate">{d.market_id}</span>
        <span className="text-xs text-slate-500">
          spread {(d.probability_spread * 100).toFixed(1)}%
        </span>
      </div>
      <div className="flex items-center gap-2 text-xs mb-2">
        {d.agents.map((a, i) => (
          <span key={a.agent_id} className="flex items-center gap-1">
            {i > 0 && <span className="text-slate-600">vs</span>}
            <span className="text-blue-400 font-medium">{a.agent_id}</span>
            <span className="text-slate-500">({(a.probability * 100).toFixed(1)}%)</span>
          </span>
        ))}
      </div>
      <div className="flex items-center gap-2 text-xs">
        <div className="flex flex-wrap gap-1">
          {d.regime_tags_a.map(t => (
            <span key={t} className="px-1.5 py-0.5 bg-blue-500/15 text-blue-400 rounded border border-blue-500/20">
              {t}
            </span>
          ))}
        </div>
        <ArrowRight className="w-3 h-3 text-slate-600 shrink-0" />
        <div className="flex flex-wrap gap-1">
          {d.regime_tags_b.map(t => (
            <span key={t} className="px-1.5 py-0.5 bg-purple-500/15 text-purple-400 rounded border border-purple-500/20">
              {t}
            </span>
          ))}
        </div>
      </div>
      {d.suggestion && (
        <p className="text-xs text-amber-300/80 mt-2 leading-relaxed">{d.suggestion}</p>
      )}
    </div>
  );
}

/* ── Dynamics Card ────────────────────────────────────────── */

function DynamicsCard({ marketId, dyn }: { marketId: string; dyn: HypothesisDynamics }) {
  const flags: { label: string; color: string }[] = [];
  if (dyn.rigidity_flag) flags.push({ label: 'Rigid', color: 'text-amber-400 bg-amber-500/10 border-amber-500/20' });
  if (dyn.flailing_flag) flags.push({ label: 'Flailing', color: 'text-rose-400 bg-rose-500/10 border-rose-500/20' });

  return (
    <div className="p-3 bg-slate-900/50 border border-slate-700/40 rounded-lg">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm font-medium text-white truncate">{marketId}</span>
        {flags.map(f => (
          <span key={f.label} className={`text-xs px-1.5 py-0.5 rounded border ${f.color}`}>
            {f.label}
          </span>
        ))}
      </div>
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 text-xs">
        <div>
          <span className="text-slate-500 block">Actions</span>
          <span className="text-white font-medium">{dyn.total_actions}</span>
        </div>
        <div>
          <span className="text-slate-500 block">Flips</span>
          <span className="text-white font-medium">{dyn.flips}</span>
        </div>
        <div>
          <span className="text-slate-500 block">Updates</span>
          <span className="text-white font-medium">{dyn.updates}</span>
        </div>
        <div>
          <span className="text-slate-500 block">Created</span>
          <span className="text-white font-medium">{dyn.creations}</span>
        </div>
        <div>
          <span className="text-slate-500 block">Broken</span>
          <span className="text-white font-medium">{dyn.breakages}</span>
        </div>
        <div>
          <span className="text-slate-500 block">Flip/day</span>
          <span className="text-white font-medium">{dyn.flip_rate_per_day.toFixed(2)}</span>
        </div>
      </div>
      {dyn.mean_lag_after_surprise_s !== null && (
        <div className="text-xs text-slate-400 mt-1.5">
          Mean lag after surprise: {formatLag(dyn.mean_lag_after_surprise_s)}
        </div>
      )}
    </div>
  );
}

/* ── Main Panel ───────────────────────────────────────────── */

export default function RealityDebugPanel({ report }: { report: RealityDebugReport | null }) {
  if (!report) {
    return (
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-6 text-center">
        <BarChart3 className="w-8 h-8 text-slate-600 mx-auto mb-2" />
        <p className="text-sm text-slate-500">Reality debug data not available</p>
      </div>
    );
  }

  const dynamicsEntries = Object.entries(report.hypothesis_dynamics);

  return (
    <div className="space-y-4">
      {/* Summary bar */}
      <div className="flex flex-wrap gap-4 text-xs text-slate-400">
        <span>{report.markets_analyzed} markets analyzed</span>
        <span className={report.stuck_count > 0 ? 'text-rose-400' : ''}>
          {report.stuck_count} stuck
        </span>
        <span className={report.disagreement_count > 0 ? 'text-amber-400' : ''}>
          {report.disagreement_count} disagreements
        </span>
      </div>

      {/* Stuck Models */}
      <Section
        title="Stuck Models"
        icon={Lock}
        iconColor="text-rose-400"
        count={report.stuck_models.length}
        defaultOpen={report.stuck_models.length > 0}
      >
        {report.stuck_models.length === 0 ? (
          <p className="text-xs text-slate-500 py-2">No stuck models detected</p>
        ) : (
          report.stuck_models.map((sm, i) => <StuckModelCard key={`${sm.market_id}-${i}`} sm={sm} />)
        )}
      </Section>

      {/* Conceptual Disagreements */}
      <Section
        title="Conceptual Disagreements"
        icon={Shuffle}
        iconColor="text-amber-400"
        count={report.conceptual_disagreements.length}
        defaultOpen={report.conceptual_disagreements.length > 0}
      >
        {report.conceptual_disagreements.length === 0 ? (
          <p className="text-xs text-slate-500 py-2">No hidden disagreements detected</p>
        ) : (
          report.conceptual_disagreements.map((d, i) => (
            <DisagreementCard key={`${d.market_id}-${i}`} d={d} />
          ))
        )}
      </Section>

      {/* Hypothesis Dynamics */}
      <Section
        title="Hypothesis Dynamics"
        icon={Zap}
        iconColor="text-blue-400"
        count={dynamicsEntries.length}
        defaultOpen={dynamicsEntries.some(([, d]) => d.rigidity_flag || d.flailing_flag)}
      >
        {dynamicsEntries.length === 0 ? (
          <p className="text-xs text-slate-500 py-2">No dynamics data available</p>
        ) : (
          dynamicsEntries.map(([mid, dyn]) => (
            <DynamicsCard key={mid} marketId={mid} dyn={dyn} />
          ))
        )}
      </Section>
    </div>
  );
}
