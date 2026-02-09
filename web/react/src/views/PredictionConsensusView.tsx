/**
 * PredictionConsensusView — First-class prediction markets view.
 *
 * Shows all active Kalshi markets with:
 *   - Event title, category, expiry
 *   - market_prob vs swarm_prob + edge
 *   - Stance pill (Strong YES / Weak NO / etc.)
 *   - Agent counts + active plan counts
 *   - Filterable by category, sortable by edge/confidence/expiry
 *   - Click to expand: agent rationales, prob bars, plan history
 *   - Brier score summary + agent leaderboard (sidebar)
 */

import { useMemo, useState } from "react";
import {
  usePredictionConsensus,
  usePredictionMetrics,
  type PredictionSymbolSummary,
} from "../hooks/usePredictionConsensus";
import PredictionEdgePill from "../components/PredictionEdgePill";
import { isStub } from "../utils/stub";
import {
  AlertTriangle,
  ArrowUpDown,
  BarChart3,
  Clock,
  Filter,
  Target,
  Users,
  ChevronDown,
  ChevronRight,
  Trophy,
  Activity,
} from "lucide-react";

/* ── Types ─────────────────────────────────────────────────────── */

type SortKey = "edge" | "confidence" | "expiry" | "volume" | "opinions";
type SortDir = "asc" | "desc";

const CATEGORIES = ["all", "macro", "politics", "equities", "crypto", "sports", "weather", "entertainment", "other"];

const CATEGORY_COLORS: Record<string, string> = {
  macro: "bg-blue-500/20 text-blue-400",
  politics: "bg-purple-500/20 text-purple-400",
  equities: "bg-amber-500/20 text-amber-400",
  crypto: "bg-orange-500/20 text-orange-400",
  sports: "bg-green-500/20 text-green-400",
  weather: "bg-cyan-500/20 text-cyan-400",
  entertainment: "bg-pink-500/20 text-pink-400",
  other: "bg-slate-500/20 text-slate-400",
};

/* ── Main View ─────────────────────────────────────────────────── */

export default function PredictionConsensusView() {
  const { symbols, rawResponse, loading } = usePredictionConsensus(12_000);
  const { metrics, rawResponse: metricsRaw } = usePredictionMetrics(30_000);

  const [selectedCategory, setSelectedCategory] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("edge");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null);

  const stubbed = isStub(rawResponse);

  const filtered = useMemo(() => {
    let list = [...symbols];
    if (selectedCategory !== "all") {
      list = list.filter((s) => s.category === selectedCategory);
    }
    list.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "edge":
          cmp = Math.abs(b.edge) - Math.abs(a.edge);
          break;
        case "confidence":
          cmp = b.confidence - a.confidence;
          break;
        case "expiry":
          cmp = (a.expiry ?? "z").localeCompare(b.expiry ?? "z");
          break;
        case "volume":
          cmp = b.volume - a.volume;
          break;
        case "opinions":
          cmp = b.opinion_count - a.opinion_count;
          break;
      }
      return sortDir === "desc" ? cmp : -cmp;
    });
    return list;
  }, [symbols, selectedCategory, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  return (
    <div className="flex flex-col gap-6 p-6" data-testid="prediction-consensus-view">
      {/* ── Header ─────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Target className="w-6 h-6 text-blue-400" />
            Prediction Markets — Swarm Consensus
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Kalshi markets · Swarm probability vs market odds · Edge detection
          </p>
        </div>
        {metrics && !isStub(metricsRaw) && (
          <div className="flex items-center gap-4 text-sm">
            <div className="text-center">
              <div className="text-slate-400">Active Markets</div>
              <div className="text-lg font-semibold text-white">
                {metrics.universe.active_instruments}
              </div>
            </div>
            <div className="text-center">
              <div className="text-slate-400">Resolved</div>
              <div className="text-lg font-semibold text-white">
                {metrics.brier.resolved_count}
              </div>
            </div>
            <div className="text-center">
              <div className="text-slate-400">Swarm Brier</div>
              <div
                className={`text-lg font-semibold ${
                  metrics.brier.swarm_brier !== null && metrics.brier.swarm_brier < 0.25
                    ? "text-emerald-400"
                    : "text-amber-400"
                }`}
              >
                {metrics.brier.swarm_brier?.toFixed(3) ?? "—"}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── Stub banner ────────────────────────────────────────── */}
      {stubbed && (
        <div
          className="flex items-center gap-2 px-4 py-2 bg-amber-500/10 border border-amber-500/30 rounded-lg text-amber-400 text-sm"
          data-testid="prediction-stub-banner"
        >
          <AlertTriangle className="w-4 h-4" />
          Prediction consensus data is simulated — connect live Kalshi feed for real data
        </div>
      )}

      {/* ── Filters + Sort ─────────────────────────────────────── */}
      <div className="flex items-center gap-3 flex-wrap">
        <Filter className="w-4 h-4 text-slate-500" />
        {CATEGORIES.map((cat) => (
          <button
            key={cat}
            onClick={() => setSelectedCategory(cat)}
            className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
              selectedCategory === cat
                ? "bg-blue-500/20 text-blue-400 border-blue-500/50"
                : "bg-slate-800 text-slate-400 border-slate-700 hover:border-slate-500"
            }`}
          >
            {cat === "all" ? "All" : cat.charAt(0).toUpperCase() + cat.slice(1)}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2 text-xs text-slate-500">
          <ArrowUpDown className="w-3 h-3" />
          {(["edge", "confidence", "expiry", "volume", "opinions"] as SortKey[]).map((k) => (
            <button
              key={k}
              onClick={() => toggleSort(k)}
              className={`px-2 py-0.5 rounded ${
                sortKey === k ? "bg-slate-700 text-white" : "hover:text-slate-300"
              }`}
            >
              {k.charAt(0).toUpperCase() + k.slice(1)}
              {sortKey === k && (sortDir === "desc" ? " ↓" : " ↑")}
            </button>
          ))}
        </div>
      </div>

      {/* ── Main content: cards + sidebar ──────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
        {/* Market cards */}
        <div className="xl:col-span-3 flex flex-col gap-3">
          {loading && symbols.length === 0 && (
            <div className="text-center text-slate-500 py-12">Loading prediction markets...</div>
          )}

          {!loading && filtered.length === 0 && (
            <div className="text-center text-slate-500 py-12" data-testid="prediction-empty">
              No prediction markets found
              {selectedCategory !== "all" ? ` in "${selectedCategory}"` : ""}
            </div>
          )}

          {filtered.map((sym) => (
            <PredictionMarketCard
              key={sym.symbol}
              sym={sym}
              expanded={expandedSymbol === sym.symbol}
              onToggle={() =>
                setExpandedSymbol(expandedSymbol === sym.symbol ? null : sym.symbol)
              }
            />
          ))}
        </div>

        {/* Sidebar: Brier leaderboard */}
        <div className="flex flex-col gap-4">
          <BrierSidebar metrics={metrics} stubbed={isStub(metricsRaw)} />
        </div>
      </div>
    </div>
  );
}

/* ── Market Card ────────────────────────────────────────────────── */

function PredictionMarketCard({
  sym,
  expanded,
  onToggle,
}: {
  sym: PredictionSymbolSummary;
  expanded: boolean;
  onToggle: () => void;
}) {
  const totalPlans =
    sym.active_plans.proposed + sym.active_plans.approved + sym.active_plans.executing;

  const expiryStr = sym.expiry
    ? new Date(sym.expiry).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

  return (
    <div
      className="bg-slate-800/60 border border-slate-700/60 rounded-xl hover:border-slate-600 transition-colors"
      data-testid="prediction-market-card"
    >
      {/* Header row */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-4 p-4 text-left"
      >
        {expanded ? (
          <ChevronDown className="w-4 h-4 text-slate-500 shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-slate-500 shrink-0" />
        )}

        {/* Category badge */}
        <span
          className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase ${
            CATEGORY_COLORS[sym.category] ?? CATEGORY_COLORS.other
          }`}
        >
          {sym.category}
        </span>

        {/* Title + ticker */}
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-white truncate">{sym.title}</div>
          <div className="text-[11px] text-slate-500 truncate">{sym.ticker}</div>
        </div>

        {/* Prob columns */}
        <div className="text-center shrink-0 w-16">
          <div className="text-[10px] text-slate-500">Market</div>
          <div className="text-sm font-semibold text-slate-300">
            {(sym.market_prob * 100).toFixed(0)}%
          </div>
        </div>
        <div className="text-center shrink-0 w-16">
          <div className="text-[10px] text-slate-500">Swarm</div>
          <div
            className={`text-sm font-semibold ${
              sym.edge >= 0 ? "text-emerald-400" : "text-red-400"
            }`}
          >
            {(sym.swarm_prob * 100).toFixed(0)}%
          </div>
        </div>

        {/* Edge pill */}
        <div className="shrink-0">
          <PredictionEdgePill
            stance={sym.stance}
            edge={sym.edge}
            swarmProb={sym.swarm_prob}
            marketProb={sym.market_prob}
            confidence={sym.confidence}
          />
        </div>

        {/* Agents */}
        <div className="flex items-center gap-1 text-xs text-slate-500 shrink-0 w-20">
          <Users className="w-3 h-3" />
          <span className="text-emerald-400">{sym.supporting_agents}</span>
          <span>/</span>
          <span className="text-red-400">{sym.opposing_agents}</span>
        </div>

        {/* Plans */}
        <div className="flex items-center gap-1 text-xs text-slate-500 shrink-0 w-14">
          <Activity className="w-3 h-3" />
          <span>{totalPlans}</span>
        </div>

        {/* Expiry */}
        <div className="flex items-center gap-1 text-[11px] text-slate-500 shrink-0 w-28">
          <Clock className="w-3 h-3" />
          {expiryStr}
        </div>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-4 border-t border-slate-700/40">
          <div className="grid grid-cols-3 gap-4 mt-3">
            {/* Probability comparison bar */}
            <div>
              <div className="text-[10px] text-slate-500 mb-1.5 uppercase tracking-wide">
                Probability Comparison
              </div>
              <PredictionEdgePill
                stance={sym.stance}
                edge={sym.edge}
                swarmProb={sym.swarm_prob}
                marketProb={sym.market_prob}
                confidence={sym.confidence}
                showBar
              />
              <div className="mt-2 text-xs text-slate-400">
                Edge: <span className={sym.edge >= 0 ? "text-emerald-400" : "text-red-400"}>
                  {(sym.edge * 100).toFixed(2)}%
                </span>
                {" · "}
                Confidence: {(sym.confidence * 100).toFixed(0)}%
              </div>
            </div>

            {/* Agent breakdown */}
            <div>
              <div className="text-[10px] text-slate-500 mb-1.5 uppercase tracking-wide">
                Agent Breakdown
              </div>
              <div className="flex items-center gap-3">
                <div className="flex-1">
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-emerald-400">YES ({sym.supporting_agents})</span>
                    <span className="text-red-400">NO ({sym.opposing_agents})</span>
                  </div>
                  <div className="w-full h-2 bg-slate-700 rounded-full overflow-hidden flex">
                    <div
                      className="bg-emerald-500/70 h-full"
                      style={{
                        width: `${
                          sym.supporting_agents + sym.opposing_agents > 0
                            ? (sym.supporting_agents /
                                (sym.supporting_agents + sym.opposing_agents)) *
                              100
                            : 50
                        }%`,
                      }}
                    />
                    <div className="bg-red-500/70 h-full flex-1" />
                  </div>
                </div>
              </div>
              <div className="text-[11px] text-slate-500 mt-1">
                {sym.opinion_count} total opinions
              </div>
            </div>

            {/* Plan status */}
            <div>
              <div className="text-[10px] text-slate-500 mb-1.5 uppercase tracking-wide">
                Active Plans
              </div>
              <div className="flex gap-3 text-xs">
                <div>
                  <span className="text-slate-500">Proposed:</span>{" "}
                  <span className="text-white">{sym.active_plans.proposed}</span>
                </div>
                <div>
                  <span className="text-slate-500">Approved:</span>{" "}
                  <span className="text-blue-400">{sym.active_plans.approved}</span>
                </div>
                <div>
                  <span className="text-slate-500">Executing:</span>{" "}
                  <span className="text-emerald-400">{sym.active_plans.executing}</span>
                </div>
              </div>
              <div className="text-[11px] text-slate-500 mt-1">
                Volume: ${sym.volume.toLocaleString()}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Brier Sidebar ──────────────────────────────────────────────── */

function BrierSidebar({
  metrics,
  stubbed,
}: {
  metrics: ReturnType<typeof usePredictionMetrics>["metrics"];
  stubbed: boolean;
}) {
  if (stubbed || !metrics) {
    return (
      <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-4">
        <h3 className="text-sm font-semibold text-slate-400 flex items-center gap-2">
          <BarChart3 className="w-4 h-4" /> Brier Scores
        </h3>
        <p className="text-xs text-slate-500 mt-2">
          No resolved markets yet — Brier scores will appear after markets settle.
        </p>
      </div>
    );
  }

  const brier = {
    swarm_brier: metrics.brier?.swarm_brier ?? null,
    market_brier: metrics.brier?.market_brier ?? null,
    swarm_vs_market: metrics.brier?.swarm_vs_market ?? null,
    agent_ranking: metrics.brier?.agent_ranking ?? [],
    resolved_count: metrics.brier?.resolved_count ?? 0,
    total_pnl_usd: metrics.brier?.total_pnl_usd ?? 0,
    calibration: metrics.brier?.calibration ?? [],
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Score cards */}
      <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-4">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-3">
          <BarChart3 className="w-4 h-4 text-blue-400" /> Brier Scores
        </h3>
        <div className="grid grid-cols-2 gap-3 text-center">
          <div>
            <div className="text-[10px] text-slate-500">Swarm</div>
            <div
              className={`text-xl font-bold ${
                brier.swarm_brier !== null && brier.swarm_brier < 0.25
                  ? "text-emerald-400"
                  : "text-amber-400"
              }`}
            >
              {brier.swarm_brier?.toFixed(3) ?? "—"}
            </div>
          </div>
          <div>
            <div className="text-[10px] text-slate-500">Market</div>
            <div className="text-xl font-bold text-slate-300">
              {brier.market_brier?.toFixed(3) ?? "—"}
            </div>
          </div>
        </div>
        {brier.swarm_vs_market && (
          <div
            className={`text-center text-xs mt-2 ${
              brier.swarm_vs_market === "better"
                ? "text-emerald-400"
                : brier.swarm_vs_market === "worse"
                ? "text-red-400"
                : "text-slate-400"
            }`}
          >
            Swarm is{" "}
            {brier.swarm_vs_market === "better"
              ? "outperforming"
              : brier.swarm_vs_market === "worse"
              ? "underperforming"
              : "matching"}{" "}
            the market
          </div>
        )}
        <div className="text-center text-[11px] text-slate-500 mt-1">
          {brier.resolved_count} resolved · PnL: ${brier.total_pnl_usd.toFixed(2)}
        </div>
      </div>

      {/* Agent leaderboard */}
      {brier.agent_ranking.length > 0 && (
        <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-4">
          <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-3">
            <Trophy className="w-4 h-4 text-amber-400" /> Agent Leaderboard
          </h3>
          <div className="flex flex-col gap-1.5">
            {brier.agent_ranking.slice(0, 10).map((a, i) => (
              <div
                key={a.agent_id}
                className="flex items-center justify-between text-xs px-2 py-1 rounded bg-slate-700/30"
              >
                <span className="text-slate-400">
                  <span className="text-slate-500 mr-1.5">#{i + 1}</span>
                  {a.agent_id}
                </span>
                <span
                  className={`font-mono ${
                    a.brier < 0.2 ? "text-emerald-400" : a.brier < 0.3 ? "text-amber-400" : "text-red-400"
                  }`}
                >
                  {a.brier.toFixed(3)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Universe stats */}
      <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-4">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-3">
          <Target className="w-4 h-4 text-blue-400" /> Universe
        </h3>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="text-slate-500">Active</div>
          <div className="text-right text-white">{metrics.universe?.active_instruments ?? 0}</div>
          <div className="text-slate-500">Total</div>
          <div className="text-right text-white">{metrics.universe?.total_instruments ?? 0}</div>
          <div className="text-slate-500">Plans (exec)</div>
          <div className="text-right text-emerald-400">{metrics.plans?.executing ?? 0}</div>
          <div className="text-slate-500">Plans (approved)</div>
          <div className="text-right text-blue-400">{metrics.plans?.approved ?? 0}</div>
        </div>
      </div>
    </div>
  );
}
