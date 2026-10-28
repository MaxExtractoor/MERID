/**
 * useAgentWall — composes every data source behind the agent-monitoring
 * surface into one fault-isolated, freshness-tracked state object.
 *
 * Sources (each independently fault-isolated via Promise.allSettled — a
 * failing endpoint must never zero out the wall):
 *   fetchAgentsWall        -> AssetAgent[]   (rich grid endpoint w/ fallback)
 *   fetchGridSummary       -> GridSummary
 *   fetchDecisionFeed      -> DecisionEvent[]
 *   fetchMarketStates      -> MarketState[]
 *   fetchBalance           -> BalanceInfo (incl. shards)
 *   fetchLiveRuntimeState  -> LiveRuntimeState
 *   fetchSpotPrices        -> spot map
 *
 * After each poll, market-state rows and spot prices are merged into each
 * agent's market/heartbeat blocks — but ONLY where the server left gaps.
 * Missing data stays missing; the UI renders 'n/a' rather than a fake zero.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  fetchAgentsWall, fetchGridSummary, fetchDecisionFeed, fetchMarketStates,
  fetchBalance, fetchLiveRuntimeState, fetchSpotPrices, toMarketStateList,
} from './api';
import type {
  AssetAgent, BalanceInfo, DecisionEvent, GridSummary,
  LiveRuntimeState, MarketState,
} from './types';
import { agentAttentionRank } from './types';
import { matchMarketState, numOr, parseTsMs, toSpotMap } from './format';
import type { SpotInfo } from './format';

export type WallSourceId =
  | 'agents' | 'grid' | 'feed' | 'markets' | 'balance' | 'runtime' | 'spot';

export interface SourceStatus {
  /** Endpoint currently reachable — last fetch succeeded. */
  ok: boolean;
  /** At least one fetch has completed (success or failure). */
  attempted: boolean;
  /** Last error message, cleared on next success. */
  error?: string;
  /** Epoch ms of last *successful* fetch — drives freshness chips. */
  lastOkMs?: number;
}

export type WallSources = Record<WallSourceId, SourceStatus>;

export interface AgentWallRibbon {
  runtime?: LiveRuntimeState;
  balance?: BalanceInfo;
  grid?: GridSummary;
}

export interface AgentWallResult {
  /** AssetAgent[] sorted by operator-attention order (stable per asset). */
  agents: AssetAgent[];
  ribbon: AgentWallRibbon;
  feed: DecisionEvent[];
  marketStates: MarketState[];
  spotPrices: Partial<Record<string, SpotInfo>>;
  sources: WallSources;
  /** Epoch ms of the last completed poll cycle (any source). */
  lastUpdate?: number;
  /** True until the very first poll completes. */
  loading: boolean;
  /** Force an immediate poll. */
  refresh: () => void;
}

export interface UseAgentWallOptions {
  /** Poll interval in ms. Default 5000. `0` disables polling. */
  pollMs?: number;
  /** Decision-feed row limit. Default 60. */
  feedLimit?: number;
}

const INITIAL_SOURCES: WallSources = {
  agents: { ok: false, attempted: false },
  grid: { ok: false, attempted: false },
  feed: { ok: false, attempted: false },
  markets: { ok: false, attempted: false },
  balance: { ok: false, attempted: false },
  runtime: { ok: false, attempted: false },
  spot: { ok: false, attempted: false },
};

interface WallData {
  agents: AssetAgent[];
  grid?: GridSummary;
  feed: DecisionEvent[];
  marketStates: MarketState[];
  balance?: BalanceInfo;
  runtime?: LiveRuntimeState;
  spotPrices: Partial<Record<string, SpotInfo>>;
}

const INITIAL_DATA: WallData = {
  agents: [],
  feed: [],
  marketStates: [],
  spotPrices: {},
};

function errMsg(e: unknown): string {
  if (e instanceof Error) return e.message;
  return String(e);
}

/**
 * Merge market-state + spot gaps into agents. Only fills fields the server
 * left undefined — never overwrites authoritative agent fields, never
 * invents values.
 */
export function mergeWallAgents(
  agents: AssetAgent[],
  states: MarketState[],
  spot: Partial<Record<string, SpotInfo>>,
): AssetAgent[] {
  return agents.map((agent) => {
    const ms = matchMarketState(agent.asset, agent.market?.ticker, states);
    const sp = spot[agent.asset];
    if (!ms && !sp) return agent;

    const market = { ...(agent.market ?? {}) };
    if (!market.ticker && ms?.ticker) market.ticker = ms.ticker;
    if (market.yes_bid_c == null && ms?.yes_bid_c != null) market.yes_bid_c = ms.yes_bid_c;
    if (market.yes_ask_c == null && ms?.yes_ask_c != null) market.yes_ask_c = ms.yes_ask_c;
    if (market.mid_c == null && ms?.mid_c != null) market.mid_c = ms.mid_c;
    if (market.spread_c == null && ms?.spread_c != null) market.spread_c = ms.spread_c;
    if (market.secs_to_close == null && ms?.secs_to_expiry != null) {
      market.secs_to_close = ms.secs_to_expiry;
    }
    if (market.book_fresh == null && ms?.book_age_ms != null) {
      market.book_fresh = ms.book_age_ms < 10_000;
    }

    const heartbeat = { ...agent.heartbeat };
    if (heartbeat.book_age_ms == null && ms?.book_age_ms != null) {
      heartbeat.book_age_ms = ms.book_age_ms;
    }
    if (heartbeat.spot_age_ms == null && sp?.ageS != null) {
      heartbeat.spot_age_ms = sp.ageS * 1000;
    }

    return { ...agent, market, heartbeat };
  });
}

/** Attention-order sort, stable within a state by configured asset order. */
export function sortAgentsByAttention(agents: AssetAgent[]): AssetAgent[] {
  const assetOrder = new Map(agents.map((a, i) => [a.asset, i]));
  return [...agents].sort((a, b) => {
    const d = agentAttentionRank(a) - agentAttentionRank(b);
    if (d !== 0) return d;
    return (assetOrder.get(a.asset) ?? 0) - (assetOrder.get(b.asset) ?? 0);
  });
}

/** Sort the decision tape newest-first by timestamp (stable for ties). */
export function sortFeed(feed: DecisionEvent[]): DecisionEvent[] {
  return [...feed].sort((a, b) => (parseTsMs(b.ts) ?? 0) - (parseTsMs(a.ts) ?? 0));
}

export function useAgentWall(options?: UseAgentWallOptions): AgentWallResult {
  const pollMs = options?.pollMs ?? 5000;
  const feedLimit = options?.feedLimit ?? 60;

  const [data, setData] = useState<WallData>(INITIAL_DATA);
  const [sources, setSources] = useState<WallSources>(INITIAL_SOURCES);
  const [lastUpdate, setLastUpdate] = useState<number | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const inFlightRef = useRef(false);
  const mountedRef = useRef(true);

  const poll = useCallback(async () => {
    if (inFlightRef.current) return; // never overlap polls
    inFlightRef.current = true;
    try {
      const [rAgents, rGrid, rFeed, rMarkets, rBalance, rRuntime, rSpot] =
        await Promise.allSettled([
          fetchAgentsWall(),
          fetchGridSummary(),
          fetchDecisionFeed(feedLimit),
          fetchMarketStates(),
          fetchBalance(),
          fetchLiveRuntimeState(),
          fetchSpotPrices(),
        ]);
      if (!mountedRef.current) return;
      const now = Date.now();

      setSources((prev) => {
        const next = { ...prev };
        const mark = (id: WallSourceId, res: PromiseSettledResult<unknown>) => {
          if (res.status === 'fulfilled') {
            next[id] = { ok: true, attempted: true, lastOkMs: now };
          } else {
            next[id] = { ...prev[id], ok: false, attempted: true, error: errMsg(res.reason) };
          }
        };
        mark('agents', rAgents);
        mark('grid', rGrid);
        mark('feed', rFeed);
        mark('markets', rMarkets);
        mark('balance', rBalance);
        mark('runtime', rRuntime);
        mark('spot', rSpot);
        return next;
      });

      setData((prev) => ({
        agents: rAgents.status === 'fulfilled' ? rAgents.value : prev.agents,
        grid: rGrid.status === 'fulfilled' ? rGrid.value : prev.grid,
        feed:
          rFeed.status === 'fulfilled' ? rFeed.value.events ?? [] : prev.feed,
        marketStates:
          rMarkets.status === 'fulfilled'
            ? toMarketStateList(rMarkets.value)
            : prev.marketStates,
        balance: rBalance.status === 'fulfilled' ? rBalance.value : prev.balance,
        runtime: rRuntime.status === 'fulfilled' ? rRuntime.value : prev.runtime,
        spotPrices:
          rSpot.status === 'fulfilled' ? toSpotMap(rSpot.value) : prev.spotPrices,
      }));
      setLastUpdate(now);
      setLoading(false);
    } finally {
      inFlightRef.current = false;
    }
  }, [feedLimit]);

  useEffect(() => {
    mountedRef.current = true;
    void poll();
    if (pollMs > 0) {
      const id = window.setInterval(() => void poll(), pollMs);
      return () => {
        mountedRef.current = false;
        window.clearInterval(id);
      };
    }
    return () => {
      mountedRef.current = false;
    };
  }, [poll, pollMs]);

  const refresh = useCallback(() => {
    void poll();
  }, [poll]);

  const agents = useMemo(
    () => sortAgentsByAttention(mergeWallAgents(data.agents, data.marketStates, data.spotPrices)),
    [data.agents, data.marketStates, data.spotPrices],
  );
  const feed = useMemo(() => sortFeed(data.feed), [data.feed]);

  const ribbon = useMemo<AgentWallRibbon>(
    () => ({ runtime: data.runtime, balance: data.balance, grid: data.grid }),
    [data.runtime, data.balance, data.grid],
  );

  return { agents, ribbon, feed, marketStates: data.marketStates, spotPrices: data.spotPrices, sources, lastUpdate, loading, refresh };
}

/**
 * Trading-shard cash in cents from BalanceInfo.shards.
 * Only returns a shard balance when we know it IS the trading shard
 * (explicit match, or a single-shard account). Multi-shard accounts with no
 * declared trading shard return undefined -> UI shows 'n/a', not a guess.
 */
export function tradingShardCents(balance: BalanceInfo | undefined): number | undefined {
  const shards = balance?.shards;
  if (!shards?.length) return undefined;
  const shardNum = numOr(balance?.trading_shard);
  if (shardNum != null) {
    const s = shards.find((x) => x.shard === shardNum);
    return numOr(s?.available_cents ?? s?.balance_cents);
  }
  if (shards.length === 1) {
    const s = shards[0];
    return numOr(s.available_cents ?? s.balance_cents);
  }
  return undefined;
}
