/**
 * FlowRadarView — Meme/whale/KOL radar + sniper/MEV status + domain metrics.
 *
 * Sections:
 *   1. Header with live counts + chain filter
 *   2. Token radar cards (flow score, stance, events, plans)
 *   3. Entity sidebar (whales, KOLs)
 *   4. Recent flow events feed
 *   5. Sniper/MEV status panel
 *   6. Domain metrics sidebar
 */

import { useState, useMemo } from "react";
import {
  useFlowRadar,
  useFlowMetrics,
  useFlowSniper,
  useFlowRisk,
  FlowTokenConsensus,
  FlowEntity,
  FlowEvent,
} from "../hooks/useFlowRadar";

// ── Helpers ──────────────────────────────────────────────────────────

const CHAINS = ["All", "solana", "ethereum", "base", "arbitrum"];
const ENTITY_FILTERS = ["All", "whale", "smart_wallet", "kol", "deployer", "cex"];

const STANCE_COLORS: Record<string, string> = {
  spec_long: "text-green-400 bg-green-900/30 border-green-700",
  watch: "text-yellow-400 bg-yellow-900/30 border-yellow-700",
  avoid: "text-red-400 bg-red-900/30 border-red-700",
  spec_short: "text-orange-400 bg-orange-900/30 border-orange-700",
};

const QUALITY_COLORS: Record<string, string> = {
  elite: "text-purple-400",
  good: "text-green-400",
  average: "text-yellow-400",
  poor: "text-red-400",
  unknown: "text-slate-500",
};

const CHAIN_ICONS: Record<string, string> = {
  solana: "◎",
  ethereum: "⟠",
  base: "🔵",
  arbitrum: "🔷",
};

function formatUsd(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`;
  return `$${v.toFixed(2)}`;
}

function formatAge(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  if (hours < 24) return `${hours.toFixed(1)}h`;
  return `${(hours / 24).toFixed(1)}d`;
}

function timeAgo(ts: number): string {
  const s = Math.floor(Date.now() / 1000 - ts);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function eventTypeLabel(t: string): string {
  return t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ── Flow Score Bar ───────────────────────────────────────────────────

function FlowScoreBar({ score }: { score: number }) {
  const color =
    score >= 70 ? "bg-green-500" : score >= 50 ? "bg-yellow-500" : score >= 30 ? "bg-orange-500" : "bg-red-500";
  return (
    <div className="w-full h-2 bg-slate-700 rounded-full overflow-hidden">
      <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${score}%` }} />
    </div>
  );
}

// ── Token Card ───────────────────────────────────────────────────────

function TokenCard({
  token,
  expanded,
  onToggle,
}: {
  token: FlowTokenConsensus;
  expanded: boolean;
  onToggle: () => void;
}) {
  const stance = token.opinion_summary.dominant_stance;
  const stanceClass = STANCE_COLORS[stance] || STANCE_COLORS.watch;

  return (
    <div
      data-testid="flow-token-card"
      className="bg-slate-800 border border-slate-700 rounded-lg p-4 hover:border-slate-500 transition-colors cursor-pointer"
      onClick={onToggle}
     role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); (onToggle)(); } }}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-lg">{CHAIN_ICONS[token.chain] || "🔗"}</span>
          <span className="font-bold text-white text-lg">{token.symbol}</span>
          <span className="text-slate-500 text-sm">{token.name}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`px-2 py-0.5 rounded text-xs font-semibold border ${stanceClass}`}>
            {stance.replace("_", " ").toUpperCase()}
          </span>
          <span className="text-slate-500 text-xs">{formatAge(token.age_hours)}</span>
        </div>
      </div>

      {/* Flow score */}
      <div className="mb-3">
        <div className="flex justify-between text-xs text-slate-400 mb-1">
          <span>Flow Score</span>
          <span className="font-mono">{token.flow_score}</span>
        </div>
        <FlowScoreBar score={token.flow_score} />
      </div>

      {/* Quick stats row */}
      <div className="grid grid-cols-4 gap-2 text-center text-xs">
        <div>
          <div className="text-slate-500">Liquidity</div>
          <div className="text-white font-mono">{formatUsd(token.liquidity_usd)}</div>
        </div>
        <div>
          <div className="text-slate-500">🐋 Whale</div>
          <div className="text-white font-mono">
            <span className="text-green-400">+{token.event_summary.whale_buys}</span>
            {" / "}
            <span className="text-red-400">-{token.event_summary.whale_sells}</span>
          </div>
        </div>
        <div>
          <div className="text-slate-500">👤 KOL</div>
          <div className="text-white font-mono">
            {token.event_summary.kol_buys}B / {token.event_summary.kol_mentions}M
          </div>
        </div>
        <div>
          <div className="text-slate-500">Plans</div>
          <div className="text-white font-mono">{token.plan_summary.active_plans}</div>
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="mt-4 pt-4 border-t border-slate-700 space-y-3">
          {/* Price */}
          {token.price_usd > 0 && (
            <div className="flex justify-between text-sm">
              <span className="text-slate-400">Price</span>
              <span className="text-white font-mono">
                ${token.price_usd < 0.01 ? token.price_usd.toExponential(2) : token.price_usd.toFixed(4)}
              </span>
            </div>
          )}

          {/* Opinion distribution */}
          {token.opinion_summary.total > 0 && (
            <div>
              <div className="text-xs text-slate-400 mb-1">Swarm Opinions ({token.opinion_summary.total})</div>
              <div className="flex gap-1">
                {Object.entries(token.opinion_summary.stance_distribution).map(([s, count]) => (
                  count > 0 && (
                    <span key={s} className={`px-2 py-0.5 rounded text-xs border ${STANCE_COLORS[s] || ""}`}>
                      {s}: {count}
                    </span>
                  )
                ))}
              </div>
            </div>
          )}

          {/* Plan breakdown */}
          <div className="grid grid-cols-3 gap-2 text-xs text-center">
            <div className="bg-slate-900 rounded p-2">
              <div className="text-slate-500">Meme</div>
              <div className="text-white">{token.plan_summary.meme_plans}</div>
            </div>
            <div className="bg-slate-900 rounded p-2">
              <div className="text-slate-500">Whale</div>
              <div className="text-white">{token.plan_summary.whale_plans}</div>
            </div>
            <div className="bg-slate-900 rounded p-2">
              <div className="text-slate-500">KOL</div>
              <div className="text-white">{token.plan_summary.kol_plans}</div>
            </div>
          </div>

          {/* LP events */}
          <div className="flex justify-between text-xs">
            <span className="text-slate-400">LP Activity</span>
            <span>
              <span className="text-green-400">+{token.event_summary.lp_adds}</span>
              {" / "}
              <span className="text-red-400">-{token.event_summary.lp_removes}</span>
            </span>
          </div>

          {/* Contract */}
          <div className="text-xs text-slate-500 font-mono truncate">
            {token.contract_address}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Entity Row ───────────────────────────────────────────────────────

function EntityRow({ entity }: { entity: FlowEntity }) {
  const qColor = QUALITY_COLORS[entity.quality] || QUALITY_COLORS.unknown;
  return (
    <div data-testid="flow-entity-row" className="flex items-center justify-between py-2 border-b border-slate-800 text-sm">
      <div className="flex items-center gap-2">
        <span className="text-xs px-1.5 py-0.5 bg-slate-700 rounded text-slate-300">
          {entity.entity_type === "smart_wallet" ? "🧠" : entity.entity_type === "whale" ? "🐋" : entity.entity_type === "kol" ? "👤" : entity.entity_type === "deployer" ? "🏗️" : "🏦"}
        </span>
        <span className="text-white font-medium">{entity.label || entity.address.slice(0, 12)}</span>
        {entity.social_handle && (
          <span className="text-blue-400 text-xs">{entity.social_handle}</span>
        )}
      </div>
      <div className="flex items-center gap-3 text-xs">
        <span className={qColor}>{entity.quality}</span>
        <span className="text-slate-400">{entity.trade_count} trades</span>
        <span className={entity.historical_pnl_usd >= 0 ? "text-green-400" : "text-red-400"}>
          {formatUsd(entity.historical_pnl_usd)}
        </span>
        <span className="text-slate-400">{(entity.hit_rate * 100).toFixed(0)}%</span>
      </div>
    </div>
  );
}

// ── Event Feed Row ───────────────────────────────────────────────────

function EventFeedRow({ event }: { event: FlowEvent }) {
  const isBullish = ["large_buy", "kol_buy", "lp_added", "cex_withdrawal", "bridge_in", "new_cex_listing"].includes(event.event_type);
  const color = isBullish ? "text-green-400" : event.event_type.includes("sell") || event.event_type === "lp_removed" ? "text-red-400" : "text-slate-400";

  return (
    <div data-testid="flow-event-row" className="flex items-center justify-between py-1.5 text-xs border-b border-slate-800/50">
      <div className="flex items-center gap-2">
        <span className={`${color} font-medium`}>{eventTypeLabel(event.event_type)}</span>
        <span className="text-white font-mono">{event.token_symbol}</span>
        {event.entity_type && (
          <span className="text-slate-500">{event.entity_type}</span>
        )}
      </div>
      <div className="flex items-center gap-2">
        {event.size_usd > 0 && <span className="text-slate-300 font-mono">{formatUsd(event.size_usd)}</span>}
        {event.mention_text && <span className="text-blue-400 truncate max-w-[150px]">{event.mention_text}</span>}
        <span className="text-slate-600">{timeAgo(event.timestamp)}</span>
      </div>
    </div>
  );
}

// ── Sniper Panel ─────────────────────────────────────────────────────

function SniperPanel() {
  const { status, fills, loading } = useFlowSniper();

  if (loading) return <div className="text-slate-500 text-sm p-4">Loading sniper status...</div>;

  return (
    <div data-testid="sniper-panel" className="space-y-4">
      {/* Route health */}
      <div>
        <h4 className="text-xs text-slate-400 uppercase tracking-wider mb-2">Route Health</h4>
        <div className="space-y-2">
          {Object.entries(status.route_health).map(([chain, health]) => (
            <div key={chain} className="bg-slate-800 rounded p-2">
              <div className="flex justify-between items-center mb-1">
                <span className="text-white text-sm font-medium">
                  {CHAIN_ICONS[chain] || ""} {chain}
                </span>
                <span className={health.healthy_count === health.total_count ? "text-green-400" : "text-yellow-400"}>
                  {health.healthy_count}/{health.total_count} healthy
                </span>
              </div>
              <div className="flex gap-1 flex-wrap">
                {health.routes.map((r, i) => (
                  <span
                    key={i}
                    className={`text-xs px-1.5 py-0.5 rounded ${r.is_healthy ? "bg-green-900/30 text-green-400" : "bg-red-900/30 text-red-400"}`}
                  >
                    {r.dex_router}{r.mev_relay ? `+${r.mev_relay}` : ""}
                  </span>
                ))}
              </div>
              {health.has_mev_protection && (
                <div className="text-xs text-purple-400 mt-1">🛡️ MEV protection available</div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Recent fills */}
      {fills.length > 0 && (
        <div>
          <h4 className="text-xs text-slate-400 uppercase tracking-wider mb-2">Recent Fills</h4>
          <div className="space-y-1">
            {fills.slice(0, 10).map((fill) => (
              <div key={fill.id} className="flex items-center justify-between text-xs py-1 border-b border-slate-800/50">
                <div className="flex items-center gap-2">
                  <span className={fill.success ? "text-green-400" : "text-red-400"}>
                    {fill.success ? "✓" : "✗"}
                  </span>
                  <span className="text-white font-mono">{fill.token_symbol}</span>
                  <span className="text-slate-500">{fill.direction}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-slate-300">{formatUsd(fill.filled_size_usd)}</span>
                  <span className="text-slate-500">{fill.actual_slippage_bps}bps</span>
                  {fill.mev_detected && (
                    <span className="text-red-400">⚠️ MEV</span>
                  )}
                  <span className="text-slate-600">{fill.latency_ms.toFixed(0)}ms</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Live mode indicator */}
      <div className="text-xs text-center">
        <span className={`px-2 py-1 rounded ${status.is_live ? "bg-green-900/30 text-green-400" : "bg-slate-700 text-slate-400"}`}>
          {status.is_live ? "🟢 LIVE" : "📋 PAPER"}
        </span>
      </div>
    </div>
  );
}

// ── Metrics Sidebar ──────────────────────────────────────────────────

function MetricsSidebar() {
  const { metrics, loading } = useFlowMetrics();
  const { risk } = useFlowRisk();

  if (loading) return <div className="text-slate-500 text-sm p-4">Loading metrics...</div>;

  return (
    <div data-testid="flow-metrics" className="space-y-4">
      {/* Domain stats */}
      <div>
        <h4 className="text-xs text-slate-400 uppercase tracking-wider mb-2">Domain</h4>
        <div className="grid grid-cols-2 gap-2 text-center text-xs">
          <div className="bg-slate-800 rounded p-2">
            <div className="text-slate-500">Tokens</div>
            <div className="text-white font-mono text-lg">{metrics.tokens_tracked}</div>
          </div>
          <div className="bg-slate-800 rounded p-2">
            <div className="text-slate-500">Events 24h</div>
            <div className="text-white font-mono text-lg">{metrics.events_24h}</div>
          </div>
          <div className="bg-slate-800 rounded p-2">
            <div className="text-slate-500">🐋 Whales</div>
            <div className="text-white font-mono text-lg">{metrics.whale_count}</div>
          </div>
          <div className="bg-slate-800 rounded p-2">
            <div className="text-slate-500">👤 KOLs</div>
            <div className="text-white font-mono text-lg">{metrics.kol_count}</div>
          </div>
        </div>
      </div>

      {/* Sniper stats */}
      <div>
        <h4 className="text-xs text-slate-400 uppercase tracking-wider mb-2">Sniper</h4>
        <div className="space-y-1 text-xs">
          <div className="flex justify-between">
            <span className="text-slate-400">Fills</span>
            <span className="text-white">{metrics.sniper.total_fills}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Success Rate</span>
            <span className="text-white">{(metrics.sniper.success_rate * 100).toFixed(0)}%</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Avg Slippage</span>
            <span className="text-white">{metrics.sniper.avg_slippage_bps.toFixed(0)} bps</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Avg Latency</span>
            <span className="text-white">{metrics.sniper.avg_latency_ms.toFixed(0)}ms</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Volume</span>
            <span className="text-white">{formatUsd(metrics.sniper.total_volume_usd)}</span>
          </div>
          {metrics.sniper.mev_incidents > 0 && (
            <div className="flex justify-between text-red-400">
              <span>MEV Incidents</span>
              <span>{metrics.sniper.mev_incidents} ({formatUsd(metrics.sniper.mev_loss_usd)})</span>
            </div>
          )}
        </div>
      </div>

      {/* Risk */}
      <div>
        <h4 className="text-xs text-slate-400 uppercase tracking-wider mb-2">Risk</h4>
        <div className="space-y-1 text-xs">
          <div className="flex justify-between">
            <span className="text-slate-400">Exposure</span>
            <span className="text-white">{formatUsd(risk.state.domain_exposure_usd)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Utilization</span>
            <span className="text-white">{risk.utilization_pct}%</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Daily PnL</span>
            <span className={risk.state.daily_pnl_usd >= 0 ? "text-green-400" : "text-red-400"}>
              {formatUsd(risk.state.daily_pnl_usd)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Active Plans</span>
            <span className="text-white">{risk.state.active_plan_count}</span>
          </div>
          {risk.state.is_throttled && (
            <div className="text-yellow-400 text-center mt-1 bg-yellow-900/20 rounded p-1">
              ⚡ THROTTLED
            </div>
          )}
          {risk.state.is_halted && (
            <div className="text-red-400 text-center mt-1 bg-red-900/20 rounded p-1">
              🛑 HALTED: {risk.state.halt_reason}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Main View ────────────────────────────────────────────────────────

export default function FlowRadarView() {
  const [chainFilter, setChainFilter] = useState("All");
  const [entityFilter, setEntityFilter] = useState("All");
  const [expandedToken, setExpandedToken] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"radar" | "entities" | "events" | "sniper">("radar");
  const [sortBy, setSortBy] = useState<"flow_score" | "liquidity" | "age" | "events">("flow_score");

  const { tokens, entities, recentEvents, source, loading } = useFlowRadar(
    chainFilter === "All" ? undefined : chainFilter,
  );

  // Sort tokens
  const sortedTokens = useMemo(() => {
    const arr = [...tokens];
    switch (sortBy) {
      case "flow_score":
        return arr.sort((a, b) => b.flow_score - a.flow_score);
      case "liquidity":
        return arr.sort((a, b) => b.liquidity_usd - a.liquidity_usd);
      case "age":
        return arr.sort((a, b) => a.age_hours - b.age_hours);
      case "events":
        return arr.sort((a, b) => b.event_summary.total - a.event_summary.total);
      default:
        return arr;
    }
  }, [tokens, sortBy]);

  // Filter entities
  const filteredEntities = useMemo(() => {
    if (entityFilter === "All") return entities;
    return entities.filter((e) => e.entity_type === entityFilter);
  }, [entities, entityFilter]);

  return (
    <div className="h-full flex flex-col bg-slate-900 text-white">
      {/* Header */}
      <div className="border-b border-slate-700 px-6 py-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold">Flow Radar</h1>
            <span className="text-xs text-slate-500">Memecoins · Whales · KOLs · Snipers</span>
            {source === "stub" && (
              <span data-testid="flow-stub-banner" className="text-xs px-2 py-0.5 bg-amber-900/30 text-amber-400 border border-amber-700 rounded">
                STUB DATA
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <span>{tokens.length} tokens</span>
            <span>·</span>
            <span>{entities.length} entities</span>
            <span>·</span>
            <span>{recentEvents.length} events</span>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-4 mb-3">
          {(["radar", "entities", "events", "sniper"] as const).map((tab) => (
            <button type="button"
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                activeTab === tab
                  ? "bg-blue-600 text-white"
                  : "bg-slate-800 text-slate-400 hover:text-white"
              }`}
            >
              {tab === "radar" ? "🎯 Radar" : tab === "entities" ? "🐋 Entities" : tab === "events" ? "📊 Events" : "⚡ Sniper/MEV"}
            </button>
          ))}
        </div>

        {/* Chain filter */}
        <div className="flex items-center gap-2">
          {CHAINS.map((c) => (
            <button type="button"
              key={c}
              onClick={() => setChainFilter(c)}
              className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                chainFilter === c
                  ? "bg-blue-600 text-white border-blue-500"
                  : "bg-slate-800 text-slate-400 border-slate-700 hover:border-slate-500"
              }`}
            >
              {c === "All" ? "All Chains" : `${CHAIN_ICONS[c] || ""} ${c}`}
            </button>
          ))}
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-auto flex">
        {/* Main content */}
        <div className="flex-1 p-4 overflow-auto">
          {loading ? (
            <div className="flex items-center justify-center h-64 text-slate-500">Loading flow data...</div>
          ) : activeTab === "radar" ? (
            <div>
              {/* Sort controls */}
              <div className="flex items-center gap-2 mb-4 text-xs">
                <span className="text-slate-500">Sort:</span>
                {(["flow_score", "liquidity", "age", "events"] as const).map((s) => (
                  <button type="button"
                    key={s}
                    onClick={() => setSortBy(s)}
                    className={`px-2 py-1 rounded ${sortBy === s ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white"}`}
                  >
                    {s === "flow_score" ? "Score" : s.charAt(0).toUpperCase() + s.slice(1)}
                  </button>
                ))}
              </div>

              {sortedTokens.length === 0 ? (
                <div data-testid="flow-empty" className="text-center text-slate-500 py-16">
                  No tokens detected yet. Trigger an ingestion cycle.
                </div>
              ) : (
                <div className="grid gap-3">
                  {sortedTokens.map((tok) => (
                    <TokenCard
                      key={tok.token_id}
                      token={tok}
                      expanded={expandedToken === tok.token_id}
                      onToggle={() => setExpandedToken(expandedToken === tok.token_id ? null : tok.token_id)}
                    />
                  ))}
                </div>
              )}
            </div>
          ) : activeTab === "entities" ? (
            <div>
              {/* Entity type filter */}
              <div className="flex items-center gap-2 mb-4">
                {ENTITY_FILTERS.map((ef) => (
                  <button type="button"
                    key={ef}
                    onClick={() => setEntityFilter(ef)}
                    className={`px-2 py-1 rounded text-xs ${
                      entityFilter === ef ? "bg-slate-700 text-white" : "text-slate-400 hover:text-white"
                    }`}
                  >
                    {ef === "All" ? "All" : ef.replace("_", " ")}
                  </button>
                ))}
              </div>
              <div className="space-y-0">
                {filteredEntities.map((ent) => (
                  <EntityRow key={ent.id} entity={ent} />
                ))}
                {filteredEntities.length === 0 && (
                  <div className="text-center text-slate-500 py-16">No entities found.</div>
                )}
              </div>
            </div>
          ) : activeTab === "events" ? (
            <div>
              <div className="space-y-0">
                {recentEvents.map((ev) => (
                  <EventFeedRow key={ev.id} event={ev} />
                ))}
                {recentEvents.length === 0 && (
                  <div className="text-center text-slate-500 py-16">No recent events.</div>
                )}
              </div>
            </div>
          ) : (
            <SniperPanel />
          )}
        </div>

        {/* Metrics sidebar */}
        <div className="w-72 border-l border-slate-700 p-4 overflow-auto">
          <MetricsSidebar />
        </div>
      </div>
    </div>
  );
}
