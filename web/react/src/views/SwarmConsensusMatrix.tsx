/**
 * Swarm Consensus Matrix
 *
 * Displays a live matrix of agent consensus across all asset × timeframe
 * combinations.  Each cell shows direction, probability, confidence, and
 * size band.  Clicking a cell expands the full proposal breakdown with
 * per-agent votes and performance-weighted contributions.
 */

import { useState } from "react";
import { useApiData } from "../hooks/useApiData";
import { API_ENDPOINTS, DEFAULTS } from "../config/constants";
import ErrorBar from "../components/ErrorBar";

// ── Types ─────────────────────────────────────────────────────────────────

interface AgentProposal {
  agent_id: string;
  asset: string;
  timeframe: string;
  direction: "yes" | "no" | "neutral";
  probability: number;
  confidence: number;
  size_preference: "small" | "base" | "large";
  rationale: string;
  edge_estimate: number;
  agent_archetype: string;
  agent_track_record: Record<string, number> | null;
}

interface ConsensusView {
  asset: string;
  timeframe: string;
  timestamp: string;
  status: "forming" | "ready" | "conflicted" | "stale";
  consensus_direction: "yes" | "no" | "neutral";
  consensus_probability: number;
  consensus_confidence: number;
  total_agents: number;
  voting_agents: number;
  direction_breakdown: Record<string, number>;
  size_band: "small" | "reduced" | "base" | "large";
  size_rationale: string;
  confidence_factors: string[];
  disagreement_flags: string[];
  raw_proposals: AgentProposal[];
}

// ── Helpers ───────────────────────────────────────────────────────────────

const DIR_COLOR: Record<string, string> = {
  yes:     "text-emerald-300",
  no:      "text-red-300",
  neutral: "text-slate-400",
};

const DIR_BG: Record<string, string> = {
  yes:     "bg-emerald-500/15 border-emerald-500/30",
  no:      "bg-red-500/15 border-red-500/30",
  neutral: "bg-slate-700/30 border-slate-600/30",
};

const STATUS_BADGE: Record<string, string> = {
  ready:     "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  forming:   "bg-blue-500/20 text-blue-300 border-blue-500/30",
  conflicted:"bg-amber-500/20 text-amber-300 border-amber-500/30",
  stale:     "bg-slate-600/20 text-slate-400 border-slate-600/30",
};

const SIZE_COLOR: Record<string, string> = {
  large:   "text-emerald-300",
  base:    "text-blue-300",
  reduced: "text-amber-300",
  small:   "text-red-300",
};

const ARCHETYPE_ICON: Record<string, string> = {
  trend:          "📈",
  mean_reversion: "↩",
  momentum:       "⚡",
  contrarian:     "🔄",
  sentiment:      "💬",
  default:        "🤖",
};

function archetypeIcon(archetype: string): string {
  return ARCHETYPE_ICON[archetype] ?? ARCHETYPE_ICON.default;
}

function probBar(prob: number, direction: "yes" | "no" | "neutral") {
  const color = direction === "yes" ? "bg-emerald-500" : direction === "no" ? "bg-red-500" : "bg-slate-500";
  return (
    <div className="relative h-1 w-full rounded-full bg-slate-700/60 mt-1">
      <div
        className={`absolute top-0 left-0 h-1 rounded-full transition-all ${color}`}
        style={{ width: `${Math.round(prob * 100)}%` }}
      />
    </div>
  );
}

function ConfidenceDots({ confidence }: { confidence: number }) {
  const filled = Math.round(confidence * 5);
  return (
    <div className="flex gap-0.5">
      {Array.from({ length: 5 }).map((_, i) => (
        <div
          key={i}
          className={`h-1.5 w-1.5 rounded-full ${i < filled ? "bg-blue-400" : "bg-slate-700"}`}
        />
      ))}
    </div>
  );
}

// ── Cell component ────────────────────────────────────────────────────────

function ConsensusCell({
  view,
  onClick,
  selected,
}: {
  view: ConsensusView;
  onClick: () => void;
  selected: boolean;
}) {
  const dir = view.consensus_direction;
  const prob = Math.round(view.consensus_probability * 100);

  return (
    <button
      onClick={onClick}
      className={`rounded-xl border p-3 text-left w-full transition-all hover:scale-[1.02] ${
        selected ? "ring-2 ring-blue-500/60 " : ""
      }${DIR_BG[dir]}`}
    >
      <div className="flex items-center justify-between mb-1">
        <span className={`text-xs font-bold uppercase ${DIR_COLOR[dir]}`}>
          {dir === "yes" ? "YES" : dir === "no" ? "NO" : "—"}
        </span>
        <span className={`rounded-full border px-1.5 py-0.5 text-[9px] font-bold ${STATUS_BADGE[view.status]}`}>
          {view.status}
        </span>
      </div>

      <div className={`text-lg font-bold tabular-nums ${DIR_COLOR[dir]}`}>
        {prob}%
      </div>
      {probBar(view.consensus_probability, dir)}

      <div className="mt-2 flex items-center justify-between">
        <ConfidenceDots confidence={view.consensus_confidence} />
        <span className={`text-[10px] font-semibold ${SIZE_COLOR[view.size_band]}`}>
          {view.size_band.toUpperCase()}
        </span>
      </div>

      <div className="mt-1.5 flex items-center gap-1 text-[9px] text-slate-500">
        <span>{view.voting_agents} agents</span>
        {view.disagreement_flags.length > 0 && (
          <span className="text-amber-400">⚠ {view.disagreement_flags.length}</span>
        )}
      </div>
    </button>
  );
}

// ── Detail panel ──────────────────────────────────────────────────────────

function ConsensusDetail({ view }: { view: ConsensusView }) {
  const dir = view.consensus_direction;

  return (
    <div className={`rounded-2xl border p-5 ${DIR_BG[dir]} space-y-4`}>
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xl font-bold text-white">{view.asset}</span>
            <span className="text-slate-400 text-sm">{view.timeframe}</span>
            <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${STATUS_BADGE[view.status]}`}>
              {view.status}
            </span>
          </div>
          <div className="mt-1 text-xs text-slate-400">
            {new Date(view.timestamp).toLocaleString()}
          </div>
        </div>
        <div className="text-right">
          <div className={`text-3xl font-bold ${DIR_COLOR[dir]}`}>
            {Math.round(view.consensus_probability * 100)}%
          </div>
          <div className={`text-sm font-semibold ${DIR_COLOR[dir]}`}>
            {dir.toUpperCase()}
          </div>
        </div>
      </div>

      {/* Metrics row */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "Confidence", value: `${Math.round(view.consensus_confidence * 100)}%` },
          { label: "Agents", value: `${view.voting_agents}/${view.total_agents}` },
          { label: "Size Band", value: view.size_band.toUpperCase(), color: SIZE_COLOR[view.size_band] },
          { label: "Direction Split", value: Object.entries(view.direction_breakdown).map(([d, c]) => `${d}:${c}`).join(" / ") },
        ].map(({ label, value, color }) => (
          <div key={label} className="rounded-lg bg-slate-900/40 p-3">
            <div className="text-[10px] text-slate-500 uppercase tracking-wide">{label}</div>
            <div className={`text-sm font-bold mt-0.5 ${color ?? "text-white"}`}>{value}</div>
          </div>
        ))}
      </div>

      {/* Size rationale */}
      {view.size_rationale && (
        <div className="rounded-lg bg-slate-900/30 px-3 py-2 text-xs text-slate-400">
          <span className="font-semibold text-slate-300">Size rationale: </span>
          {view.size_rationale}
        </div>
      )}

      {/* Confidence factors */}
      {view.confidence_factors.length > 0 && (
        <div className="space-y-1">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Confidence Factors</div>
          {view.confidence_factors.map((f) => (
            <div key={f} className="flex items-center gap-2 text-xs text-emerald-300">
              <span>✓</span><span>{f}</span>
            </div>
          ))}
        </div>
      )}

      {/* Disagreement flags */}
      {view.disagreement_flags.length > 0 && (
        <div className="space-y-1">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Disagreements</div>
          {view.disagreement_flags.map((f) => (
            <div key={f} className="flex items-center gap-2 text-xs text-amber-300">
              <span>⚠</span><span>{f}</span>
            </div>
          ))}
        </div>
      )}

      {/* Agent proposals */}
      {view.raw_proposals.length > 0 && (
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500 mb-2">
            Agent Votes ({view.raw_proposals.length})
          </div>
          <div className="space-y-2">
            {view.raw_proposals.map((p, i) => (
              <div key={p.agent_id} className="rounded-lg bg-slate-900/50 border border-slate-700/30 p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-base">{archetypeIcon(p.agent_archetype)}</span>
                    <span className="text-xs font-mono font-bold text-white">{p.agent_id}</span>
                    <span className="text-[10px] text-slate-500">{p.agent_archetype}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className={`text-xs font-bold ${DIR_COLOR[p.direction]}`}>
                      {p.direction.toUpperCase()} {Math.round(p.probability * 100)}%
                    </span>
                    <span className={`text-[10px] font-semibold ${SIZE_COLOR[p.size_preference]}`}>
                      {p.size_preference}
                    </span>
                    <span className="text-[10px] text-slate-400">
                      edge {p.edge_estimate >= 0 ? "+" : ""}{p.edge_estimate.toFixed(1)}¢
                    </span>
                  </div>
                </div>
                {p.rationale && (
                  <div className="mt-1.5 text-[10px] text-slate-500 line-clamp-2">{p.rationale}</div>
                )}
                {p.agent_track_record && (
                  <div className="mt-1.5 flex gap-3 text-[9px] text-slate-600">
                    {Object.entries(p.agent_track_record).map(([k, v]) => (
                      <span key={k}>{k}: {typeof v === "number" ? v.toFixed(2) : v}</span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main view ─────────────────────────────────────────────────────────────

const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];

export default function SwarmConsensusMatrix() {
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [filterAsset, setFilterAsset] = useState<string>("ALL");
  const [filterStatus, setFilterStatus] = useState<string>("ALL");

  const { data: allConsensus, loading, error, refetch } = useApiData<Record<string, ConsensusView>>(
    API_ENDPOINTS.KALSHI_CONSENSUS_ALL,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SENTIMENT }
  );

  const views = allConsensus ? Object.values(allConsensus) : [];

  // Derive unique assets
  const assets = ["ALL", ...Array.from(new Set(views.map(v => v.asset))).sort()];
  const statuses = ["ALL", "ready", "forming", "conflicted", "stale"];

  const filtered = views.filter(v => {
    if (filterAsset !== "ALL" && v.asset !== filterAsset) return false;
    if (filterStatus !== "ALL" && v.status !== filterStatus) return false;
    return true;
  });

  // Group by asset for matrix layout
  const byAsset = filtered.reduce<Record<string, Record<string, ConsensusView>>>((acc, v) => {
    if (!acc[v.asset]) acc[v.asset] = {};
    acc[v.asset][v.timeframe] = v;
    return acc;
  }, {});

  const selectedView = selectedKey ? allConsensus?.[selectedKey] ?? null : null;

  // Summary stats
  const readyCount = views.filter(v => v.status === "ready").length;
  const conflictCount = views.filter(v => v.status === "conflicted").length;
  const bullishCount = views.filter(v => v.consensus_direction === "yes").length;
  const bearishCount = views.filter(v => v.consensus_direction === "no").length;

  return (
    <div className="space-y-6 text-white">
      <ErrorBar label="Swarm Consensus" error={error} onRetry={refetch} />
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Swarm Consensus Matrix</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Multi-agent voting across all asset × timeframe combinations
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" /> Ready
          <span className="w-2 h-2 rounded-full bg-blue-500 inline-block ml-2" /> Forming
          <span className="w-2 h-2 rounded-full bg-amber-500 inline-block ml-2" /> Conflicted
          <span className="w-2 h-2 rounded-full bg-slate-500 inline-block ml-2" /> Stale
        </div>
      </div>

      {/* Summary pills */}
      <div className="flex flex-wrap gap-3">
        {[
          { label: "Ready", count: readyCount, color: "text-emerald-300 bg-emerald-500/15 border-emerald-500/30" },
          { label: "Conflicted", count: conflictCount, color: "text-amber-300 bg-amber-500/15 border-amber-500/30" },
          { label: "Bullish", count: bullishCount, color: "text-emerald-300 bg-emerald-500/15 border-emerald-500/30" },
          { label: "Bearish", count: bearishCount, color: "text-red-300 bg-red-500/15 border-red-500/30" },
          { label: "Total Cells", count: views.length, color: "text-slate-300 bg-slate-700/30 border-slate-600/30" },
        ].map(({ label, count, color }) => (
          <div key={label} className={`rounded-xl border px-4 py-2 text-sm font-semibold ${color}`}>
            {count} {label}
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 uppercase tracking-wide">Asset</span>
          <div className="flex gap-1">
            {assets.map(a => (
              <button
                key={a}
                onClick={() => setFilterAsset(a)}
                className={`rounded-lg px-3 py-1 text-xs font-semibold transition-colors ${
                  filterAsset === a
                    ? "bg-blue-600/30 text-blue-300 border border-blue-500/40"
                    : "bg-slate-800/40 text-slate-400 border border-slate-700/30 hover:text-white"
                }`}
              >
                {a}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 uppercase tracking-wide">Status</span>
          <div className="flex gap-1">
            {statuses.map(s => (
              <button
                key={s}
                onClick={() => setFilterStatus(s)}
                className={`rounded-lg px-3 py-1 text-xs font-semibold transition-colors capitalize ${
                  filterStatus === s
                    ? "bg-blue-600/30 text-blue-300 border border-blue-500/40"
                    : "bg-slate-800/40 text-slate-400 border border-slate-700/30 hover:text-white"
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      </div>

      {loading && <div className="text-slate-500 text-sm">Loading consensus data…</div>}

      {!loading && views.length === 0 && (
        <div className="rounded-xl border border-slate-700/40 bg-slate-800/30 p-10 text-center">
          <div className="text-4xl mb-3">🤖</div>
          <div className="text-slate-400 text-sm">No consensus data yet.</div>
          <div className="text-slate-600 text-xs mt-1">
            Consensus populates as agents submit proposals via SwarmConsensusAggregator.
          </div>
        </div>
      )}

      {/* Matrix grid */}
      {Object.keys(byAsset).length > 0 && (
        <div className="space-y-6">
          {Object.entries(byAsset).sort(([a], [b]) => a.localeCompare(b)).map(([asset, tfMap]) => (
            <div key={asset}>
              <div className="flex items-center gap-2 mb-3">
                <span className="text-sm font-bold text-white">{asset}</span>
                <div className="flex-1 h-px bg-slate-700/40" />
              </div>
              <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${TIMEFRAMES.length}, minmax(0, 1fr))` }}>
                {TIMEFRAMES.map(tf => {
                  const view = tfMap[tf];
                  const key = `${asset}:${tf}`;
                  if (!view) {
                    return (
                      <div key={tf} className="rounded-xl border border-slate-700/20 bg-slate-800/10 p-3 text-center">
                        <div className="text-[10px] text-slate-600 font-semibold">{tf}</div>
                        <div className="text-[9px] text-slate-700 mt-1">no data</div>
                      </div>
                    );
                  }
                  return (
                    <div key={tf}>
                      <div className="text-[10px] text-slate-500 font-semibold mb-1 text-center">{tf}</div>
                      <ConsensusCell
                        view={view}
                        onClick={() => setSelectedKey(selectedKey === key ? null : key)}
                        selected={selectedKey === key}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Detail panel */}
      {selectedView && (
        <div className="mt-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">
              Consensus Detail — {selectedView.asset} {selectedView.timeframe}
            </h2>
            <button
              onClick={() => setSelectedKey(null)}
              className="text-slate-500 hover:text-white text-xs transition-colors"
            >
              ✕ Close
            </button>
          </div>
          <ConsensusDetail view={selectedView} />
        </div>
      )}
    </div>
  );
}
