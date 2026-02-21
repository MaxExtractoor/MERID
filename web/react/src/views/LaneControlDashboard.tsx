/**
 * Lane Control Dashboard
 *
 * Displays the live state of every trading lane (asset × timeframe),
 * cross-timeframe signal alignment, deployment phase per agent, and
 * auto-promoter status.  Operators can inspect gate results and
 * manually trigger promotions or rollbacks from this view.
 */

import { useState, useCallback } from "react";
import { useApiData } from "../hooks/useApiData";
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from "../config/constants";
import ErrorBar from "../components/ErrorBar";

// ── Types ─────────────────────────────────────────────────────────────────

interface LaneSnapshot {
  timeframe: string;
  weight: number;
  avg_score: number;
  avg_confidence: number;
  signal_count: number;
  direction: "bullish" | "bearish" | "neutral";
  stale: boolean;
}

interface XtfSignal {
  asset: string;
  timestamp: string;
  composite_score: number;
  dominant_direction: "bullish" | "bearish" | "neutral";
  alignment_score: number;
  overall_confidence: number;
  active_timeframes: number;
  total_timeframes: number;
  sources: string[];
  is_aligned: boolean;
  has_trend_confirmation: boolean;
  conflict_flags: string[];
  lanes: LaneSnapshot[];
}

interface AgentDeployment {
  agent_name: string;
  mode: "PAPER" | "SHADOW" | "LIVE" | "HALTED";
  promoted_at: string | null;
  rollback_count: number;
  last_rollback_reason: string | null;
  live_trades: number;
  shadow_trades: number;
}

interface DeploymentStatus {
  agents: Record<string, AgentDeployment>;
  live: string[];
  shadow: string[];
  paper: string[];
  halted: string[];
  live_count: number;
  shadow_count: number;
  total_agents: number;
  max_live_agents: number;
  recent_transitions: Array<{
    ts: string;
    agent: string;
    from: string;
    to: string;
    reason: string;
  }>;
}

interface AutoPromoterStatus {
  running: boolean;
  eval_interval_seconds: number;
  eval_count: number;
  last_eval_ago_seconds: number | null;
  total_promotions: number;
  recent_evaluations: Array<{
    agent: string;
    from_phase: string;
    to_phase: string;
    timestamp: string;
    promoted: boolean;
    blocked_by: string | null;
    gates: Array<{
      gate: string;
      passed: boolean;
      actual: number;
      required: number;
      detail: string;
    }>;
  }>;
}

// ── Helpers ───────────────────────────────────────────────────────────────

const DIRECTION_COLOR: Record<string, string> = {
  bullish: "text-emerald-400",
  bearish: "text-red-400",
  neutral: "text-slate-400",
};

const DIRECTION_BG: Record<string, string> = {
  bullish: "bg-emerald-500/15 border-emerald-500/30",
  bearish: "bg-red-500/15 border-red-500/30",
  neutral: "bg-slate-700/40 border-slate-600/30",
};

const MODE_COLOR: Record<string, string> = {
  LIVE:   "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
  SHADOW: "bg-amber-500/20 text-amber-300 border-amber-500/40",
  PAPER:  "bg-blue-500/20 text-blue-300 border-blue-500/40",
  HALTED: "bg-red-500/20 text-red-300 border-red-500/40",
};

function scoreBar(score: number) {
  const pct = Math.round(((score + 1) / 2) * 100);
  const color = score > 0.1 ? "bg-emerald-500" : score < -0.1 ? "bg-red-500" : "bg-slate-500";
  return (
    <div className="relative h-1.5 w-full rounded-full bg-slate-700/60">
      <div
        className={`absolute top-0 h-1.5 rounded-full transition-all ${color}`}
        style={{ left: "50%", width: `${Math.abs(pct - 50)}%`, transform: score < 0 ? "translateX(-100%)" : "none" }}
      />
      <div className="absolute top-0 left-1/2 h-1.5 w-px bg-slate-500" />
    </div>
  );
}

function AlignmentRing({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = pct >= 65 ? "#10b981" : pct >= 40 ? "#f59e0b" : "#ef4444";
  const r = 20;
  const circ = 2 * Math.PI * r;
  const dash = (pct / 100) * circ;
  return (
    <svg width="52" height="52" viewBox="0 0 52 52">
      <circle cx="26" cy="26" r={r} fill="none" stroke="#334155" strokeWidth="4" />
      <circle
        cx="26" cy="26" r={r} fill="none"
        stroke={color} strokeWidth="4"
        strokeDasharray={`${dash} ${circ}`}
        strokeLinecap="round"
        transform="rotate(-90 26 26)"
      />
      <text x="26" y="30" textAnchor="middle" fontSize="11" fill={color} fontWeight="700">
        {pct}%
      </text>
    </svg>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────

function XtfCard({ signal }: { signal: XtfSignal }) {
  const [expanded, setExpanded] = useState(false);
  const dir = signal.dominant_direction;

  return (
    <div className={`rounded-xl border p-4 ${DIRECTION_BG[dir]} transition-all`}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="text-base font-bold text-white">{signal.asset}</span>
          <span className={`text-xs font-semibold uppercase tracking-wide ${DIRECTION_COLOR[dir]}`}>
            {dir}
          </span>
          {signal.is_aligned && (
            <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] font-bold text-emerald-300 border border-emerald-500/30">
              ALIGNED
            </span>
          )}
          {signal.has_trend_confirmation && (
            <span className="rounded-full bg-blue-500/20 px-2 py-0.5 text-[10px] font-bold text-blue-300 border border-blue-500/30">
              CONFIRMED
            </span>
          )}
        </div>
        <div className="flex items-center gap-4">
          <AlignmentRing score={signal.alignment_score} />
          <div className="text-right">
            <div className="text-xs text-slate-400">Score</div>
            <div className={`text-sm font-bold ${DIRECTION_COLOR[dir]}`}>
              {signal.composite_score >= 0 ? "+" : ""}{(signal.composite_score * 100).toFixed(1)}
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-slate-400">Conf</div>
            <div className="text-sm font-bold text-white">
              {(signal.overall_confidence * 100).toFixed(0)}%
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-slate-400">TFs</div>
            <div className="text-sm font-bold text-white">
              {signal.active_timeframes}/{signal.total_timeframes}
            </div>
          </div>
          <button
            onClick={() => setExpanded(e => !e)}
            className="text-slate-400 hover:text-white transition-colors text-xs"
          >
            {expanded ? "▲" : "▼"}
          </button>
        </div>
      </div>

      {signal.conflict_flags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {signal.conflict_flags.map((f, i) => (
            <span key={i} className="rounded bg-amber-500/15 px-2 py-0.5 text-[10px] text-amber-300 border border-amber-500/30">
              ⚠ {f}
            </span>
          ))}
        </div>
      )}

      {expanded && (
        <div className="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-6">
          {signal.lanes.map(lane => (
            <div
              key={lane.timeframe}
              className={`rounded-lg border p-2 text-center ${lane.stale ? "opacity-40" : ""} ${DIRECTION_BG[lane.direction]}`}
            >
              <div className="text-[10px] font-bold text-slate-300 mb-1">{lane.timeframe}</div>
              {scoreBar(lane.avg_score)}
              <div className={`mt-1 text-[10px] font-semibold ${DIRECTION_COLOR[lane.direction]}`}>
                {lane.direction}
              </div>
              <div className="text-[9px] text-slate-500 mt-0.5">
                {lane.signal_count} sig · {(lane.avg_confidence * 100).toFixed(0)}%
              </div>
              {lane.stale && <div className="text-[9px] text-slate-600 mt-0.5">stale</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AgentRow({ dep }: { dep: AgentDeployment }) {
  return (
    <tr className="border-b border-slate-700/40 hover:bg-slate-800/30 transition-colors">
      <td className="py-2 px-3 text-sm font-mono text-white">{dep.agent_name}</td>
      <td className="py-2 px-3">
        <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${MODE_COLOR[dep.mode]}`}>
          {dep.mode}
        </span>
      </td>
      <td className="py-2 px-3 text-xs text-slate-300 tabular-nums">{dep.live_trades}</td>
      <td className="py-2 px-3 text-xs text-slate-300 tabular-nums">{dep.shadow_trades}</td>
      <td className="py-2 px-3 text-xs text-slate-400 tabular-nums">{dep.rollback_count}</td>
      <td className="py-2 px-3 text-xs text-slate-500 max-w-[200px] truncate">
        {dep.last_rollback_reason ?? "—"}
      </td>
      <td className="py-2 px-3 text-xs text-slate-500">
        {dep.promoted_at ? new Date(dep.promoted_at).toLocaleString() : "—"}
      </td>
    </tr>
  );
}

function GateRow({ gate }: { gate: AutoPromoterStatus["recent_evaluations"][0]["gates"][0] }) {
  return (
    <div className={`flex items-center gap-2 text-xs py-0.5 ${gate.passed ? "text-emerald-300" : "text-red-300"}`}>
      <span>{gate.passed ? "✓" : "✗"}</span>
      <span className="font-mono">{gate.gate}</span>
      <span className="text-slate-400 ml-auto">{gate.detail}</span>
    </div>
  );
}

// ── Main view ─────────────────────────────────────────────────────────────

export default function LaneControlDashboard() {
  const [expandedEval, setExpandedEval] = useState<number | null>(null);

  const { data: xtfAll, loading: xtfLoading, error: xtfError, refetch: xtfRefetch } = useApiData<Record<string, XtfSignal>>(
    API_ENDPOINTS.XTF_SIGNALS_ALL,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SENTIMENT }
  );

  const { data: deployStatus, loading: deployLoading, error: deployError, refetch: deployRefetch } = useApiData<DeploymentStatus>(
    API_ENDPOINTS.KALSHI_DEPLOYMENT_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );

  const { data: promoterStatus, error: promoterError, refetch: promoterRefetch } = useApiData<AutoPromoterStatus>(
    API_ENDPOINTS.AUTO_PROMOTER_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );

  const handleSync = useCallback(async () => {
    try {
      await fetch(`${API_BASE_URL}${API_ENDPOINTS.XTF_SYNC}`, { method: "POST" });
    } catch { /* ignore */ }
  }, []);

  const xtfSignals = xtfAll ? Object.values(xtfAll) : [];
  const agents = deployStatus ? Object.values(deployStatus.agents) : [];

  return (
    <div className="space-y-6 text-white">
      <ErrorBar label="XTF Signals" error={xtfError} onRetry={xtfRefetch} />
      <ErrorBar label="Deployment Status" error={deployError} onRetry={deployRefetch} />
      <ErrorBar label="Auto-Promoter" error={promoterError} onRetry={promoterRefetch} />
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Lane Control Dashboard</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Cross-timeframe signal alignment · Deployment phases · Auto-promoter
          </p>
        </div>
        <button
          onClick={handleSync}
          className="rounded-lg bg-blue-600/20 border border-blue-500/30 px-4 py-2 text-sm text-blue-300 hover:bg-blue-600/30 transition-colors"
        >
          ↻ Sync Signals
        </button>
      </div>

      {/* Deployment summary pills */}
      {deployStatus && (
        <div className="flex flex-wrap gap-3">
          {[
            { label: "Live", count: deployStatus.live_count, color: "text-emerald-300 bg-emerald-500/15 border-emerald-500/30" },
            { label: "Shadow", count: deployStatus.shadow_count, color: "text-amber-300 bg-amber-500/15 border-amber-500/30" },
            { label: "Paper", count: deployStatus.paper.length, color: "text-blue-300 bg-blue-500/15 border-blue-500/30" },
            { label: "Halted", count: deployStatus.halted.length, color: "text-red-300 bg-red-500/15 border-red-500/30" },
          ].map(({ label, count, color }) => (
            <div key={label} className={`rounded-xl border px-4 py-2 text-sm font-semibold ${color}`}>
              {count} {label}
            </div>
          ))}
          {promoterStatus && (
            <div className={`rounded-xl border px-4 py-2 text-sm font-semibold ${promoterStatus.running ? "text-emerald-300 bg-emerald-500/15 border-emerald-500/30" : "text-slate-400 bg-slate-700/30 border-slate-600/30"}`}>
              Auto-Promoter {promoterStatus.running ? "ON" : "OFF"} · {promoterStatus.total_promotions} promotions
            </div>
          )}
        </div>
      )}

      {/* Cross-Timeframe Signal Grid */}
      <section>
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">
          Cross-Timeframe Signals
        </h2>
        {xtfLoading && <div className="text-slate-500 text-sm">Loading signals…</div>}
        {!xtfLoading && xtfSignals.length === 0 && (
          <div className="rounded-xl border border-slate-700/40 bg-slate-800/30 p-6 text-center text-slate-500 text-sm">
            No cross-timeframe signals yet. Signals populate as agents submit proposals.
          </div>
        )}
        <div className="space-y-3">
          {xtfSignals.map(sig => (
            <XtfCard key={sig.asset} signal={sig} />
          ))}
        </div>
      </section>

      {/* Agent Deployment Table */}
      <section>
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">
          Agent Deployment Phases
        </h2>
        {deployLoading && <div className="text-slate-500 text-sm">Loading deployment status…</div>}
        {!deployLoading && agents.length === 0 && (
          <div className="rounded-xl border border-slate-700/40 bg-slate-800/30 p-6 text-center text-slate-500 text-sm">
            No agents registered yet.
          </div>
        )}
        {agents.length > 0 && (
          <div className="rounded-xl border border-slate-700/40 bg-slate-800/20 overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-slate-700/40">
                  {["Agent", "Mode", "Live Trades", "Shadow Trades", "Rollbacks", "Last Rollback Reason", "Promoted At"].map(h => (
                    <th key={h} className="py-2 px-3 text-[10px] font-semibold uppercase tracking-wider text-slate-500">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {agents.map(dep => <AgentRow key={dep.agent_name} dep={dep} />)}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Auto-Promoter Recent Evaluations */}
      {promoterStatus && promoterStatus.recent_evaluations.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">
            Auto-Promoter Evaluations
          </h2>
          <div className="space-y-2">
            {promoterStatus.recent_evaluations.slice().reverse().map((ev, i) => (
              <button
                key={i}
                type="button"
                className={`w-full text-left rounded-xl border p-3 transition-colors ${
                  ev.promoted
                    ? "bg-emerald-500/10 border-emerald-500/30"
                    : ev.blocked_by
                    ? "bg-slate-800/30 border-slate-700/40"
                    : "bg-slate-800/20 border-slate-700/30"
                }`}
                onClick={() => setExpandedEval(expandedEval === i ? null : i)}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-mono font-bold text-white">{ev.agent}</span>
                    <span className="text-xs text-slate-400">{ev.from_phase} → {ev.to_phase}</span>
                    {ev.promoted && (
                      <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[10px] font-bold text-emerald-300 border border-emerald-500/30">
                        PROMOTED
                      </span>
                    )}
                    {ev.blocked_by && (
                      <span className="rounded-full bg-red-500/20 px-2 py-0.5 text-[10px] font-bold text-red-300 border border-red-500/30">
                        BLOCKED
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-slate-500">
                      {new Date(ev.timestamp).toLocaleTimeString()}
                    </span>
                    <span className="text-slate-500 text-xs">{expandedEval === i ? "▲" : "▼"}</span>
                  </div>
                </div>

                {ev.blocked_by && (
                  <div className="mt-1 text-xs text-red-400 truncate">{ev.blocked_by}</div>
                )}

                {expandedEval === i && ev.gates.length > 0 && (
                  <div className="mt-3 rounded-lg bg-slate-900/50 p-3 space-y-1">
                    {ev.gates.map((g, gi) => <GateRow key={gi} gate={g} />)}
                  </div>
                )}
              </button>
            ))}
          </div>
        </section>
      )}

      {/* Recent Transitions */}
      {deployStatus && deployStatus.recent_transitions.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">
            Recent Transitions
          </h2>
          <div className="rounded-xl border border-slate-700/40 bg-slate-800/20 overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-slate-700/40">
                  {["Time", "Agent", "From", "To", "Reason"].map(h => (
                    <th key={h} className="py-2 px-3 text-[10px] font-semibold uppercase tracking-wider text-slate-500">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {deployStatus.recent_transitions.slice().reverse().map((t, i) => (
                  <tr key={i} className="border-b border-slate-700/30 hover:bg-slate-800/30">
                    <td className="py-2 px-3 text-xs text-slate-400 tabular-nums whitespace-nowrap">
                      {new Date(t.ts).toLocaleTimeString()}
                    </td>
                    <td className="py-2 px-3 text-xs font-mono text-white">{t.agent}</td>
                    <td className="py-2 px-3">
                      <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${MODE_COLOR[t.from as keyof typeof MODE_COLOR] ?? "text-slate-400"}`}>
                        {t.from}
                      </span>
                    </td>
                    <td className="py-2 px-3">
                      <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold ${MODE_COLOR[t.to as keyof typeof MODE_COLOR] ?? "text-slate-400"}`}>
                        {t.to}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-xs text-slate-400 max-w-[240px] truncate">{t.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
