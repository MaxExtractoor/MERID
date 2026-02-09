/**
 * BettingConsensusView — Swarm-driven sports & event betting page.
 *
 * For each event shows:
 *   - "What the books think" (sportsbook consensus)
 *   - "What prediction markets think" (Kalshi, if matched)
 *   - "What MERID thinks" (swarm probability)
 *   - Edge vs books / prediction markets
 *   - Live badge + score for in-play events
 *   - Expandable detail: prob bars, agent breakdown, plan status
 *   - Metrics sidebar: win rate, ROI, PnL
 */

import { useMemo, useState } from "react";
import {
  useBettingConsensus,
  useBettingMetrics,
  type BettingConsensusData,
} from "../hooks/useBettingConsensus";
import { isStub } from "../utils/stub";
import {
  AlertTriangle,
  ArrowUpDown,
  Activity,
  BarChart3,
  ChevronDown,
  ChevronRight,
  Clock,
  DollarSign,
  Filter,
  Trophy,
  Users,
  Zap,
  TrendingUp,
  TrendingDown,
  Minus,
} from "lucide-react";

/* ── Constants ─────────────────────────────────────────────────── */

type SortKey = "edge" | "start_time" | "sport" | "confidence" | "opinions";
type SortDir = "asc" | "desc";

const SPORTS = ["all", "nfl", "nba", "mlb", "nhl", "soccer", "mma", "politics", "crypto"];

const SPORT_COLORS: Record<string, string> = {
  nfl: "bg-green-500/20 text-green-400",
  nba: "bg-orange-500/20 text-orange-400",
  mlb: "bg-red-500/20 text-red-400",
  nhl: "bg-blue-500/20 text-blue-400",
  soccer: "bg-emerald-500/20 text-emerald-400",
  mma: "bg-rose-500/20 text-rose-400",
  politics: "bg-purple-500/20 text-purple-400",
  crypto: "bg-amber-500/20 text-amber-400",
};

const STANCE_CONFIG: Record<string, { label: string; classes: string; Icon: React.ElementType }> = {
  strong_yes: { label: "Strong Edge", classes: "text-emerald-400", Icon: TrendingUp },
  weak_yes: { label: "Weak Edge", classes: "text-emerald-300", Icon: TrendingUp },
  neutral: { label: "No Edge", classes: "text-slate-400", Icon: Minus },
  weak_no: { label: "Fade", classes: "text-red-300", Icon: TrendingDown },
  strong_no: { label: "Strong Fade", classes: "text-red-400", Icon: TrendingDown },
};

/* ── Main View ─────────────────────────────────────────────────── */

export default function BettingConsensusView() {
  const { events, rawResponse, loading, liveCount } = useBettingConsensus(12_000);
  const { metrics, rawResponse: metricsRaw } = useBettingMetrics(30_000);

  const [selectedSport, setSelectedSport] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("edge");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [expandedEvent, setExpandedEvent] = useState<string | null>(null);
  const [stateFilter, setStateFilter] = useState<"all" | "pre" | "live">("all");

  const stubbed = isStub(rawResponse);

  const filtered = useMemo(() => {
    let list = [...events];
    if (selectedSport !== "all") {
      list = list.filter((e) => e.event?.sport === selectedSport);
    }
    if (stateFilter !== "all") {
      list = list.filter((e) => e.state === stateFilter);
    }
    list.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "edge":
          cmp = Math.abs(b.max_edge) - Math.abs(a.max_edge);
          break;
        case "start_time":
          cmp = (a.event?.start_time ?? 0) - (b.event?.start_time ?? 0);
          break;
        case "sport":
          cmp = (a.event?.sport ?? "").localeCompare(b.event?.sport ?? "");
          break;
        case "confidence":
          cmp = b.swarm_confidence - a.swarm_confidence;
          break;
        case "opinions":
          cmp = b.swarm_opinion_count - a.swarm_opinion_count;
          break;
      }
      return sortDir === "desc" ? cmp : -cmp;
    });
    return list;
  }, [events, selectedSport, stateFilter, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    else { setSortKey(key); setSortDir("desc"); }
  };

  return (
    <div className="flex flex-col gap-6 p-6" data-testid="betting-consensus-view">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Trophy className="w-6 h-6 text-yellow-400" />
            Swarm Betting — Consensus View
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Sportsbook odds · Prediction markets · MERID swarm edge
          </p>
        </div>
        <div className="flex items-center gap-4 text-sm">
          {liveCount > 0 && (
            <div className="flex items-center gap-1.5 px-3 py-1 bg-red-500/20 border border-red-500/40 rounded-full text-red-400 text-xs font-medium animate-pulse">
              <Zap className="w-3 h-3" /> {liveCount} LIVE
            </div>
          )}
          {metrics && !isStub(metricsRaw) && (
            <>
              <div className="text-center">
                <div className="text-slate-400">Events</div>
                <div className="text-lg font-semibold text-white">{metrics.active_events}</div>
              </div>
              <div className="text-center">
                <div className="text-slate-400">Win Rate</div>
                <div className="text-lg font-semibold text-emerald-400">
                  {(metrics.win_rate * 100).toFixed(0)}%
                </div>
              </div>
              <div className="text-center">
                <div className="text-slate-400">ROI</div>
                <div className={`text-lg font-semibold ${metrics.roi >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {metrics.roi >= 0 ? "+" : ""}{(metrics.roi * 100).toFixed(1)}%
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Stub banner */}
      {stubbed && (
        <div className="flex items-center gap-2 px-4 py-2 bg-amber-500/10 border border-amber-500/30 rounded-lg text-amber-400 text-sm" data-testid="betting-stub-banner">
          <AlertTriangle className="w-4 h-4" />
          Betting consensus data is simulated — connect odds API for real data
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <Filter className="w-4 h-4 text-slate-500" />
        {SPORTS.map((sp) => (
          <button
            key={sp}
            onClick={() => setSelectedSport(sp)}
            className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
              selectedSport === sp
                ? "bg-blue-500/20 text-blue-400 border-blue-500/50"
                : "bg-slate-800 text-slate-400 border-slate-700 hover:border-slate-500"
            }`}
          >
            {sp === "all" ? "All" : sp.toUpperCase()}
          </button>
        ))}
        <div className="w-px h-5 bg-slate-700" />
        {(["all", "pre", "live"] as const).map((s) => (
          <button
            key={s}
            onClick={() => setStateFilter(s)}
            className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
              stateFilter === s
                ? "bg-blue-500/20 text-blue-400 border-blue-500/50"
                : "bg-slate-800 text-slate-400 border-slate-700 hover:border-slate-500"
            }`}
          >
            {s === "all" ? "All States" : s === "pre" ? "Pre-Game" : "Live"}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2 text-xs text-slate-500">
          <ArrowUpDown className="w-3 h-3" />
          {(["edge", "start_time", "confidence", "opinions"] as SortKey[]).map((k) => (
            <button key={k} onClick={() => toggleSort(k)}
              className={`px-2 py-0.5 rounded ${sortKey === k ? "bg-slate-700 text-white" : "hover:text-slate-300"}`}
            >
              {k === "start_time" ? "Time" : k.charAt(0).toUpperCase() + k.slice(1)}
              {sortKey === k && (sortDir === "desc" ? " ↓" : " ↑")}
            </button>
          ))}
        </div>
      </div>

      {/* Main: cards + sidebar */}
      <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
        <div className="xl:col-span-3 flex flex-col gap-3">
          {loading && events.length === 0 && (
            <div className="text-center text-slate-500 py-12">Loading betting events...</div>
          )}
          {!loading && filtered.length === 0 && (
            <div className="text-center text-slate-500 py-12" data-testid="betting-empty">
              No events found{selectedSport !== "all" ? ` for "${selectedSport.toUpperCase()}"` : ""}
            </div>
          )}
          {filtered.map((c) => (
            <EventCard
              key={c.event_id}
              consensus={c}
              expanded={expandedEvent === c.event_id}
              onToggle={() => setExpandedEvent(expandedEvent === c.event_id ? null : c.event_id)}
            />
          ))}
        </div>

        <div className="flex flex-col gap-4">
          <MetricsSidebar metrics={metrics} stubbed={isStub(metricsRaw)} />
        </div>
      </div>
    </div>
  );
}

/* ── Event Card ─────────────────────────────────────────────────── */

function EventCard({
  consensus: c,
  expanded,
  onToggle,
}: {
  consensus: BettingConsensusData;
  expanded: boolean;
  onToggle: () => void;
}) {
  const ev = c.event;
  if (!ev) return null;

  const isLive = c.state === "live";
  const stanceCfg = STANCE_CONFIG[c.stance] ?? STANCE_CONFIG.neutral;
  const StanceIcon = stanceCfg.Icon;

  const startStr = ev.start_time
    ? new Date(ev.start_time * 1000).toLocaleDateString("en-US", {
        month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
      })
    : "—";

  const outcomes = ev.outcomes ?? [];

  return (
    <div
      className={`bg-slate-800/60 border rounded-xl transition-colors ${
        isLive ? "border-red-500/40 bg-red-950/10" : "border-slate-700/60 hover:border-slate-600"
      }`}
      data-testid="betting-event-card"
    >
      <button onClick={onToggle} className="w-full flex items-center gap-4 p-4 text-left">
        {expanded ? <ChevronDown className="w-4 h-4 text-slate-500 shrink-0" /> : <ChevronRight className="w-4 h-4 text-slate-500 shrink-0" />}

        {/* Live badge or sport badge */}
        {isLive ? (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-red-500/30 text-red-400 animate-pulse shrink-0">
            LIVE
          </span>
        ) : (
          <span className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase ${SPORT_COLORS[ev.sport] ?? "bg-slate-500/20 text-slate-400"} shrink-0`}>
            {ev.league || ev.sport}
          </span>
        )}

        {/* Title + score */}
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-white truncate">{ev.title}</div>
          {isLive && ev.score_home !== null && ev.score_away !== null && (
            <div className="text-xs text-red-300 mt-0.5">
              {ev.away_team} {ev.score_away} — {ev.score_home} {ev.home_team}
              {ev.period && ` · ${ev.period}`}
              {ev.clock && ` ${ev.clock}`}
            </div>
          )}
        </div>

        {/* Prob columns for primary outcomes */}
        {outcomes.slice(0, 2).map((oc) => {
          const bookP = c.sportsbook_consensus_prob[oc.id] ?? 0;
          const swarmP = c.swarm_prob[oc.id] ?? 0;
          const edge = c.edge_vs_books[oc.id] ?? 0;
          return (
            <div key={oc.id} className="text-center shrink-0 w-24">
              <div className="text-[10px] text-slate-500 truncate">{oc.name}</div>
              <div className="flex items-center justify-center gap-1.5 text-xs">
                <span className="text-slate-400">{(bookP * 100).toFixed(0)}%</span>
                <span className="text-slate-600">→</span>
                <span className={edge > 0.02 ? "text-emerald-400 font-semibold" : edge < -0.02 ? "text-red-400 font-semibold" : "text-slate-300"}>
                  {(swarmP * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          );
        })}

        {/* Stance */}
        <div className={`flex items-center gap-1 text-xs shrink-0 w-24 ${stanceCfg.classes}`}>
          <StanceIcon className="w-3 h-3" />
          <span>{stanceCfg.label}</span>
        </div>

        {/* Edge */}
        <div className={`text-xs font-mono shrink-0 w-14 text-center ${c.max_edge >= 0.05 ? "text-emerald-400" : c.max_edge >= 0.03 ? "text-yellow-400" : "text-slate-500"}`}>
          {(c.max_edge * 100).toFixed(1)}%
        </div>

        {/* Agents */}
        <div className="flex items-center gap-1 text-xs text-slate-500 shrink-0 w-16">
          <Users className="w-3 h-3" />
          <span className="text-emerald-400">{c.swarm_supporting_agents}</span>
          <span>/</span>
          <span className="text-red-400">{c.swarm_opposing_agents}</span>
        </div>

        {/* Time */}
        <div className="flex items-center gap-1 text-[11px] text-slate-500 shrink-0 w-28">
          <Clock className="w-3 h-3" />
          {isLive ? "In Progress" : startStr}
        </div>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-4 border-t border-slate-700/40">
          <div className="grid grid-cols-3 gap-4 mt-3">
            {/* Probability comparison bars */}
            <div>
              <div className="text-[10px] text-slate-500 mb-2 uppercase tracking-wide">
                Books vs Swarm
              </div>
              {outcomes.map((oc) => {
                const bookP = c.sportsbook_consensus_prob[oc.id] ?? 0;
                const swarmP = c.swarm_prob[oc.id] ?? 0;
                const predP = c.prediction_market_prob[oc.id];
                const edge = c.edge_vs_books[oc.id] ?? 0;
                return (
                  <div key={oc.id} className="mb-2">
                    <div className="flex justify-between text-[11px] mb-0.5">
                      <span className="text-white">{oc.name}</span>
                      <span className={edge >= 0 ? "text-emerald-400" : "text-red-400"}>
                        {edge >= 0 ? "+" : ""}{(edge * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="flex items-center gap-2 text-[10px] text-slate-500">
                      <span className="w-8">Book</span>
                      <div className="relative flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                        <div className="absolute inset-y-0 left-0 bg-slate-500/60 rounded-full" style={{ width: `${bookP * 100}%` }} />
                        <div className={`absolute inset-y-0 left-0 rounded-full ${edge >= 0 ? "bg-emerald-500/70" : "bg-red-500/70"}`} style={{ width: `${swarmP * 100}%` }} />
                      </div>
                      <span className="w-10 text-right">{(bookP * 100).toFixed(0)}%</span>
                    </div>
                    <div className="flex items-center gap-2 text-[10px] text-slate-500 mt-0.5">
                      <span className="w-8">Swarm</span>
                      <div className="relative flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                        <div className={`absolute inset-y-0 left-0 rounded-full ${edge >= 0 ? "bg-emerald-500/50" : "bg-red-500/50"}`} style={{ width: `${swarmP * 100}%` }} />
                      </div>
                      <span className="w-10 text-right">{(swarmP * 100).toFixed(0)}%</span>
                    </div>
                    {predP !== undefined && (
                      <div className="flex items-center gap-2 text-[10px] text-slate-500 mt-0.5">
                        <span className="w-8">Kalshi</span>
                        <div className="relative flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                          <div className="absolute inset-y-0 left-0 bg-blue-500/50 rounded-full" style={{ width: `${predP * 100}%` }} />
                        </div>
                        <span className="w-10 text-right">{(predP * 100).toFixed(0)}%</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Agent + confidence */}
            <div>
              <div className="text-[10px] text-slate-500 mb-2 uppercase tracking-wide">Swarm Info</div>
              <div className="text-xs space-y-1.5">
                <div className="flex justify-between">
                  <span className="text-slate-500">Confidence</span>
                  <span className="text-white">{(c.swarm_confidence * 100).toFixed(0)}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Opinions</span>
                  <span className="text-white">{c.swarm_opinion_count}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Supporting</span>
                  <span className="text-emerald-400">{c.swarm_supporting_agents}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Opposing</span>
                  <span className="text-red-400">{c.swarm_opposing_agents}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Books</span>
                  <span className="text-white">{c.book_count}</span>
                </div>
                {c.arbitrage_flag && (
                  <div className="flex items-center gap-1 text-amber-400 mt-1">
                    <Zap className="w-3 h-3" /> Arb opportunity detected
                  </div>
                )}
              </div>
            </div>

            {/* Plans */}
            <div>
              <div className="text-[10px] text-slate-500 mb-2 uppercase tracking-wide">Active Plans</div>
              <div className="flex gap-3 text-xs">
                <div><span className="text-slate-500">Proposed:</span> <span className="text-white">{c.active_plans.proposed}</span></div>
                <div><span className="text-slate-500">Approved:</span> <span className="text-blue-400">{c.active_plans.approved}</span></div>
                <div><span className="text-slate-500">Executing:</span> <span className="text-emerald-400">{c.active_plans.executing}</span></div>
              </div>
              {c.prediction_market_source && (
                <div className="mt-2 text-[11px] text-blue-400">
                  Matched on {c.prediction_market_source.toUpperCase()}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Metrics Sidebar ────────────────────────────────────────────── */

function MetricsSidebar({
  metrics,
  stubbed,
}: {
  metrics: ReturnType<typeof useBettingMetrics>["metrics"];
  stubbed: boolean;
}) {
  if (stubbed || !metrics) {
    return (
      <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-4">
        <h3 className="text-sm font-semibold text-slate-400 flex items-center gap-2">
          <BarChart3 className="w-4 h-4" /> Betting Metrics
        </h3>
        <p className="text-xs text-slate-500 mt-2">
          No betting data yet — metrics will appear after bets are settled.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Performance */}
      <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-4">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-3">
          <Trophy className="w-4 h-4 text-yellow-400" /> Performance
        </h3>
        <div className="grid grid-cols-2 gap-3 text-center">
          <div>
            <div className="text-[10px] text-slate-500">Win Rate</div>
            <div className={`text-xl font-bold ${metrics.win_rate >= 0.55 ? "text-emerald-400" : metrics.win_rate >= 0.45 ? "text-amber-400" : "text-red-400"}`}>
              {(metrics.win_rate * 100).toFixed(0)}%
            </div>
          </div>
          <div>
            <div className="text-[10px] text-slate-500">ROI</div>
            <div className={`text-xl font-bold ${metrics.roi >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {metrics.roi >= 0 ? "+" : ""}{(metrics.roi * 100).toFixed(1)}%
            </div>
          </div>
        </div>
        <div className="text-center mt-2">
          <div className="text-[10px] text-slate-500">Total PnL</div>
          <div className={`text-lg font-bold ${metrics.total_pnl_usd >= 0 ? "text-emerald-400" : "text-red-400"}`}>
            ${metrics.total_pnl_usd.toLocaleString()}
          </div>
        </div>
        <div className="text-center text-[11px] text-slate-500 mt-1">
          {metrics.total_bets} bets · ${metrics.total_staked_usd.toLocaleString()} staked
        </div>
      </div>

      {/* Activity */}
      <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-4">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-3">
          <Activity className="w-4 h-4 text-blue-400" /> Activity
        </h3>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="text-slate-500">Active Events</div>
          <div className="text-right text-white">{metrics.active_events}</div>
          <div className="text-slate-500">Live Events</div>
          <div className="text-right text-red-400">{metrics.live_events}</div>
          <div className="text-slate-500">Wins</div>
          <div className="text-right text-emerald-400">{metrics.wins}</div>
          <div className="text-slate-500">Losses</div>
          <div className="text-right text-red-400">{metrics.losses}</div>
        </div>
      </div>

      {/* Plans */}
      <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-4">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-3">
          <DollarSign className="w-4 h-4 text-green-400" /> Plans
        </h3>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="text-slate-500">Proposed</div>
          <div className="text-right text-white">{metrics.plans.proposed ?? 0}</div>
          <div className="text-slate-500">Approved</div>
          <div className="text-right text-blue-400">{metrics.plans.approved ?? 0}</div>
          <div className="text-slate-500">Executing</div>
          <div className="text-right text-emerald-400">{metrics.plans.executing ?? 0}</div>
          <div className="text-slate-500">Settled</div>
          <div className="text-right text-slate-300">{metrics.plans.settled ?? 0}</div>
        </div>
      </div>
    </div>
  );
}
