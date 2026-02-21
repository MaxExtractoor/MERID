/**
 * CognitiveView — Reality-debug & hypothesis management dashboard.
 *
 * Shows:
 *   - Cognitive health gauge (healthy/degraded/unhealthy)
 *   - Active hypotheses with confidence bars, flip counts, evidence drawers
 *   - Reality debug panel (stuck models, disagreements, dynamics)
 *   - Regime tag cloud with category grouping
 *   - Hypothesis action timeline with confidence sparklines
 *   - Status distribution chart
 */

import { useState, useMemo } from 'react';
import { useCognitive, type Hypothesis, type EvidenceLink } from '../hooks/useCognitive';
import { useRealityDebug, useCognitiveActions } from '../hooks/useRealityDebug';
import RealityDebugPanel from '../components/charts/RealityDebugPanel';
import RegimeTagCloud, { type RegimeTagEntry } from '../components/charts/RegimeTagCloud';
import HypothesisTimeline from '../components/charts/HypothesisTimeline';
import {
  Brain, AlertTriangle, CheckCircle, XCircle,
  RefreshCw, ChevronDown, ChevronRight, Eye,
  TrendingUp, BarChart3, Zap, Clock, Tag,
  FileText, ThumbsUp, ThumbsDown, ExternalLink, User,
  Shield, Layers, Activity,
} from 'lucide-react';

/* ── Health badge ──────────────────────────────────────────── */

const HEALTH_CONFIG: Record<string, { label: string; color: string; bg: string; Icon: React.ElementType }> = {
  healthy:   { label: 'Healthy',   color: 'text-emerald-400', bg: 'bg-emerald-500/20 border-emerald-500/30', Icon: CheckCircle },
  degraded:  { label: 'Degraded',  color: 'text-amber-400',   bg: 'bg-amber-500/20 border-amber-500/30',   Icon: AlertTriangle },
  unhealthy: { label: 'Unhealthy', color: 'text-rose-400',    bg: 'bg-rose-500/20 border-rose-500/30',     Icon: XCircle },
};

const STATUS_COLORS: Record<string, string> = {
  active:    'bg-blue-500/20 text-blue-400 border-blue-500/30',
  confirmed: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  refuted:   'bg-rose-500/20 text-rose-400 border-rose-500/30',
  stale:     'bg-slate-500/20 text-slate-400 border-slate-500/30',
  broken:    'bg-rose-500/20 text-rose-400 border-rose-500/30',
  retired:   'bg-slate-500/20 text-slate-400 border-slate-500/30',
};

/* ── Tooltip wrapper ──────────────────────────────────────── */

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

/* ── Metric card ──────────────────────────────────────────── */

function MetricTile({ label, value, tooltip, Icon, color = 'text-blue-400' }: {
  label: string; value: string | number; tooltip: string; Icon: React.ElementType; color?: string;
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

/* ── Confidence bar ───────────────────────────────────────── */

function ConfidenceBar({ value, prior }: { value: number; prior?: number | null }) {
  const pct = Math.round(value * 100);
  const color = pct >= 70 ? 'bg-emerald-500' : pct >= 40 ? 'bg-amber-500' : 'bg-rose-500';
  const delta = prior != null ? value - prior : null;
  return (
    <div className="flex items-center gap-2 w-full">
      <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all duration-500`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-400 w-10 text-right">{pct}%</span>
      {delta != null && Math.abs(delta) > 0.001 && (
        <span className={`text-[10px] ${delta > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
          {delta > 0 ? '+' : ''}{(delta * 100).toFixed(1)}
        </span>
      )}
    </div>
  );
}

/* ── Evidence drawer ──────────────────────────────────────── */

function EvidenceDrawer({ links }: { links: EvidenceLink[] }) {
  if (links.length === 0) {
    return <p className="text-xs text-slate-500 py-1">No evidence links attached</p>;
  }

  const supporting = links.filter(e => e.supports);
  const contradicting = links.filter(e => !e.supports);

  return (
    <div className="space-y-2">
      {supporting.length > 0 && (
        <div>
          <div className="flex items-center gap-1 text-xs text-emerald-400 mb-1">
            <ThumbsUp className="w-3 h-3" /> Supporting ({supporting.length})
          </div>
          {supporting.map(e => <EvidenceRow key={e.id} ev={e} />)}
        </div>
      )}
      {contradicting.length > 0 && (
        <div>
          <div className="flex items-center gap-1 text-xs text-rose-400 mb-1">
            <ThumbsDown className="w-3 h-3" /> Contradicting ({contradicting.length})
          </div>
          {contradicting.map(e => <EvidenceRow key={e.id} ev={e} />)}
        </div>
      )}
    </div>
  );
}

function EvidenceRow({ ev }: { ev: EvidenceLink }) {
  const strengthPct = Math.round(ev.strength * 100);
  return (
    <div className="flex items-center gap-2 p-1.5 bg-slate-900/40 rounded text-xs">
      <FileText className="w-3 h-3 text-slate-500 shrink-0" />
      <span className="text-white truncate flex-1">{ev.title || ev.reference_id || ev.id}</span>
      <span className="text-[10px] text-slate-500 bg-slate-700/50 px-1 py-0.5 rounded">{ev.evidence_type}</span>
      <div className="w-8 h-1 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full ${ev.supports ? 'bg-emerald-500' : 'bg-rose-500'} rounded-full`} style={{ width: `${strengthPct}%` }} />
      </div>
      <span className="text-[10px] text-slate-500 w-6 text-right">{strengthPct}%</span>
      {ev.url && (
        <a href={ev.url} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300" aria-label="Open evidence link">
          <ExternalLink className="w-3 h-3" />
        </a>
      )}
    </div>
  );
}

/* ── Hypothesis card (expanded with evidence + regime tag) ── */

function HypothesisCard({ h }: { h: Hypothesis }) {
  const [expanded, setExpanded] = useState(false);
  const statusClass = STATUS_COLORS[h.status] ?? STATUS_COLORS.stale;
  const hasTag = h.regime_tag && h.regime_tag.label;

  return (
    <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4 hover:border-slate-600/50 transition-all">
      <div className="flex items-start justify-between gap-3 cursor-pointer" onClick={() => setExpanded(!expanded)} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); (() => setExpanded(!expanded))(); } }}>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className={`px-2 py-0.5 text-xs rounded-full border ${statusClass}`}>
              {h.status}
            </span>
            <span className="text-xs text-slate-500">{h.domain}</span>
            {hasTag && (
              <span className="flex items-center gap-1 text-xs text-purple-400 bg-purple-500/10 px-1.5 py-0.5 rounded border border-purple-500/20">
                <Tag className="w-2.5 h-2.5" /> {h.regime_tag.label}
              </span>
            )}
            {h.flip_count > 0 && (
              <Tip text={`Flipped ${h.flip_count} time(s) — indicates model instability`}>
                <span className="flex items-center gap-1 text-xs text-amber-400">
                  <Zap className="w-3 h-3" /> {h.flip_count}
                </span>
              </Tip>
            )}
            {h.owner && (
              <span className="flex items-center gap-1 text-[10px] text-slate-500">
                <User className="w-2.5 h-2.5" /> {h.owner}
              </span>
            )}
          </div>
          <p className="text-sm text-white truncate">{h.statement}</p>
        </div>
        {expanded ? <ChevronDown className="w-4 h-4 text-slate-500 mt-1" /> : <ChevronRight className="w-4 h-4 text-slate-500 mt-1" />}
      </div>

      <div className="mt-2">
        <ConfidenceBar value={h.confidence} prior={h.prior_confidence} />
      </div>

      {expanded && (
        <div className="mt-3 pt-3 border-t border-slate-700/50 space-y-3 animate-in fade-in duration-200">
          {/* Metadata grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div>
              <span className="text-slate-500">Evidence</span>
              <span className="ml-2 text-white">{h.evidence_count} items</span>
            </div>
            <div>
              <span className="text-slate-500">Updated</span>
              <span className="ml-2 text-white">{new Date(h.last_updated).toLocaleString()}</span>
            </div>
            <div>
              <span className="text-slate-500">Confidence</span>
              <span className="ml-2 text-white">{(h.confidence * 100).toFixed(1)}%</span>
            </div>
            <div>
              <span className="text-slate-500">Flips</span>
              <span className="ml-2 text-white">{h.flip_count}</span>
            </div>
          </div>

          {/* Regime tag detail */}
          {hasTag && (
            <div className="text-xs">
              <span className="text-slate-500">Regime:</span>
              <span className="ml-1 text-purple-300">{h.regime_tag.category}</span>
              <span className="text-slate-600 mx-1">/</span>
              <span className="text-white">{h.regime_tag.label}</span>
              {h.regime_tag.description && (
                <span className="text-slate-400 ml-2">— {h.regime_tag.description}</span>
              )}
            </div>
          )}

          {/* Broken reason */}
          {h.broken_reason && (
            <div className="text-xs text-rose-300 bg-rose-500/10 border border-rose-500/20 rounded p-2">
              <span className="font-medium">Broken:</span> {h.broken_reason}
            </div>
          )}

          {/* Evidence links drawer */}
          <EvidenceDrawer links={h.evidence_links ?? []} />
        </div>
      )}
    </div>
  );
}

/* ── Distribution mini-chart (CSS-only) ───────────────────── */

function StatusDistribution({ hypotheses }: { hypotheses: Hypothesis[] }) {
  const counts = useMemo(() => {
    const c = { active: 0, confirmed: 0, refuted: 0, stale: 0 };
    hypotheses.forEach(h => { if (h.status in c) c[h.status as keyof typeof c]++; });
    return c;
  }, [hypotheses]);
  const total = Math.max(hypotheses.length, 1);

  const segments = [
    { key: 'active', color: 'bg-blue-500', label: 'Active' },
    { key: 'confirmed', color: 'bg-emerald-500', label: 'Confirmed' },
    { key: 'refuted', color: 'bg-rose-500', label: 'Refuted' },
    { key: 'stale', color: 'bg-slate-500', label: 'Stale' },
  ];

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
      <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
        <BarChart3 className="w-4 h-4 text-purple-400" /> Status Distribution
      </h3>
      <div className="flex h-3 rounded-full overflow-hidden mb-3">
        {segments.map(s => (
          <div
            key={s.key}
            className={`${s.color} transition-all duration-500`}
            style={{ width: `${(counts[s.key as keyof typeof counts] / total) * 100}%` }}
          />
        ))}
      </div>
      <div className="grid grid-cols-4 gap-2">
        {segments.map(s => (
          <div key={s.key} className="text-center">
            <div className="text-lg font-bold text-white">{counts[s.key as keyof typeof counts]}</div>
            <div className="text-xs text-slate-400 flex items-center justify-center gap-1">
              <div className={`w-2 h-2 rounded-full ${s.color}`} />
              {s.label}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Collapsible section wrapper ──────────────────────────── */

function CollapsibleSection({
  title, icon: Icon, iconColor, badge, children, defaultOpen = true,
}: {
  title: string;
  icon: React.ElementType;
  iconColor: string;
  badge?: string | number;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between mb-3 group"
      >
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Icon className={`w-5 h-5 ${iconColor}`} />
          {title}
          {badge != null && (
            <span className="text-xs text-slate-500 bg-slate-700/50 px-2 py-0.5 rounded-full font-normal">
              {badge}
            </span>
          )}
        </h2>
        {open ? (
          <ChevronDown className="w-4 h-4 text-slate-500 group-hover:text-slate-300 transition-colors" />
        ) : (
          <ChevronRight className="w-4 h-4 text-slate-500 group-hover:text-slate-300 transition-colors" />
        )}
      </button>
      {open && children}
    </div>
  );
}

/* ── Main View ────────────────────────────────────────────── */

export default function CognitiveView() {
  const { snapshot, loading, error, refresh } = useCognitive();
  const { report, health: cogHealth, loading: debugLoading, refresh: refreshDebug } = useRealityDebug();
  const { actions, loading: actionsLoading, refresh: refreshActions } = useCognitiveActions();
  const [filter, setFilter] = useState<string>('all');

  const filteredHypotheses = useMemo(() => {
    if (!snapshot) return [];
    if (filter === 'all') return snapshot.hypotheses;
    return snapshot.hypotheses.filter(h => h.status === filter);
  }, [snapshot, filter]);

  // Extract regime tags from hypotheses for the tag cloud
  const regimeTags = useMemo<RegimeTagEntry[]>(() => {
    if (!snapshot) return [];
    const tagMap = new Map<string, RegimeTagEntry>();
    snapshot.hypotheses.forEach(h => {
      if (!h.regime_tag?.label) return;
      const key = `${h.regime_tag.category}:${h.regime_tag.label}`;
      const existing = tagMap.get(key);
      if (existing) {
        existing.count++;
        existing.confidence = Math.max(existing.confidence, h.confidence);
      } else {
        tagMap.set(key, {
          category: h.regime_tag.category,
          label: h.regime_tag.label,
          description: h.regime_tag.description,
          confidence: h.confidence,
          count: 1,
          status: h.status,
        });
      }
    });
    return Array.from(tagMap.values());
  }, [snapshot]);

  const handleRefreshAll = () => {
    refresh();
    refreshDebug();
    refreshActions();
  };

  if (loading && !snapshot) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3">
          <div className="w-12 h-12 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-slate-400 text-sm">Loading cognitive state...</span>
        </div>
      </div>
    );
  }

  if (error && !snapshot) {
    return (
      <div className="p-6">
        <div className="bg-rose-900/20 border border-rose-500/30 rounded-xl p-4">
          <h3 className="text-rose-400 font-semibold mb-1">Cognitive API Error</h3>
          <p className="text-rose-300 text-sm">{error}</p>
        </div>
      </div>
    );
  }

  const m = snapshot?.metrics;
  const health = HEALTH_CONFIG[m?.cognitive_health ?? 'healthy'];
  const HealthIcon = health.Icon;
  const isAnyLoading = loading || debugLoading || actionsLoading;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white flex items-center gap-3">
            <Brain className="w-8 h-8 text-purple-400" />
            Cognitive Layer
          </h1>
          <p className="text-slate-400 mt-1">Hypothesis management, reality-debug, and cognitive health</p>
        </div>
        <div className="flex items-center gap-3">
          {/* Cognitive health from reality debugger */}
          {cogHealth && (
            <Tip text={`${cogHealth.active_hypotheses} active, ${cogHealth.broken_hypotheses} broken, ${cogHealth.markets_covered} markets`}>
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <Activity className="w-3.5 h-3.5 text-cyan-400" />
                <span>{cogHealth.markets_covered} mkts</span>
                <span className="text-slate-600">|</span>
                <span>{cogHealth.unique_owners} owners</span>
              </div>
            </Tip>
          )}
          <Tip text="Overall cognitive health status based on hypothesis freshness, flip rate, and stuck models">
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border ${health.bg}`}>
              <HealthIcon className={`w-4 h-4 ${health.color}`} />
              <span className={`text-sm font-medium ${health.color}`}>{health.label}</span>
            </div>
          </Tip>
          <button type="button" onClick={handleRefreshAll} className="p-2 hover:bg-slate-800 rounded-lg transition-colors" title="Refresh all" aria-label="Refresh">
            <RefreshCw className={`w-4 h-4 text-slate-400 ${isAnyLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Metric tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricTile label="Total Hypotheses" value={m?.total_hypotheses ?? 0} tooltip="Total number of hypotheses tracked across all domains" Icon={Brain} color="text-purple-400" />
        <MetricTile label="Active" value={m?.active_hypotheses ?? 0} tooltip="Hypotheses currently being evaluated with incoming evidence" Icon={Eye} color="text-blue-400" />
        <MetricTile label="Flip Rate" value={`${((m?.flip_rate ?? 0) * 100).toFixed(1)}%`} tooltip="Percentage of hypotheses that changed direction recently — high flip rate indicates model instability" Icon={TrendingUp} color="text-amber-400" />
        <MetricTile label="Stuck Models" value={m?.stuck_models ?? 0} tooltip="Models that haven't updated in an abnormally long time — may need manual review" Icon={Clock} color="text-rose-400" />
      </div>

      {/* Distribution + Stuck models */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <StatusDistribution hypotheses={snapshot?.hypotheses ?? []} />

        {/* Stuck models panel */}
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
          <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-400" /> Stuck Models
          </h3>
          {(snapshot?.stuck_models ?? []).length === 0 ? (
            <div className="text-sm text-slate-500 py-4 text-center">No stuck models detected</div>
          ) : (
            <div className="space-y-2 max-h-48 overflow-y-auto">
              {(snapshot?.stuck_models ?? []).map((sm, i) => (
                <div key={i} className="flex items-center gap-3 p-2 bg-amber-500/10 border border-amber-500/20 rounded-lg">
                  <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
                  <div className="min-w-0">
                    <div className="text-sm text-white font-medium truncate">{sm.model_id}</div>
                    <div className="text-xs text-amber-300">{sm.reason}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Reality Debug Panel */}
      <CollapsibleSection
        title="Reality Debugger"
        icon={Shield}
        iconColor="text-rose-400"
        badge={report ? `${report.stuck_count} stuck · ${report.disagreement_count} disagree` : undefined}
        defaultOpen={!!(report && (report.stuck_count > 0 || report.disagreement_count > 0))}
      >
        <RealityDebugPanel report={report} />
      </CollapsibleSection>

      {/* Regime Tag Cloud */}
      <CollapsibleSection
        title="Regime Tags"
        icon={Layers}
        iconColor="text-purple-400"
        badge={regimeTags.length}
        defaultOpen={regimeTags.length > 0}
      >
        <RegimeTagCloud tags={regimeTags} />
      </CollapsibleSection>

      {/* Filter tabs */}
      <div className="flex items-center gap-2">
        {['all', 'active', 'confirmed', 'refuted', 'stale'].map(f => (
          <button type="button"
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
              filter === f
                ? 'bg-purple-600 text-white'
                : 'bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-white'
            }`}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
        <span className="text-xs text-slate-500 ml-2">{filteredHypotheses.length} hypotheses</span>
      </div>

      {/* Hypothesis list */}
      <div className="space-y-3">
        {filteredHypotheses.length === 0 ? (
          <div className="text-center py-12 text-slate-500">
            <Brain className="w-12 h-12 mx-auto mb-3 opacity-30" />
            <p>No hypotheses match the current filter</p>
          </div>
        ) : (
          filteredHypotheses.map(h => <HypothesisCard key={h.id} h={h} />)
        )}
      </div>

      {/* Action Timeline */}
      <CollapsibleSection
        title="Action Timeline"
        icon={Clock}
        iconColor="text-blue-400"
        badge={actions.length}
        defaultOpen={actions.length > 0}
      >
        <HypothesisTimeline actions={actions} />
      </CollapsibleSection>
    </div>
  );
}
