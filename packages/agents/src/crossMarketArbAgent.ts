/**
 * Cross-Market Arbitrage Agent
 * Detects arbitrage opportunities across related markets
 * 
 * Example: Sum of probabilities for mutually exclusive events > 1
 * If Market A (YES) = 0.6 and Market B (YES) = 0.5, but A and B are mutually exclusive,
 * then sum = 1.1 > 1.0, creating arbitrage opportunity
 * 
 * Consumes:
 * - kalshi.orderbook_snapshot
 * - kalshi.orderbook_delta
 * 
 * Publishes:
 * - signals.cross_market_arb
 */

import { EventBus, EventEnvelope, OrderbookSnapshotMsg, OrderbookDeltaMsg } from "@merid/swarm-kernel";
import { LocalOrderbook } from "./orderbookState";

export interface CrossArbSignal {
  group_id: string;
  markets: { ticker: string; mid: number }[];
  sumProb: number;
  edge: number;
  violationType: "sum_exceeds_one" | "negative_prob" | "other";
  ts: number;
}

export interface MarketGroup {
  id: string;
  name: string;
  markets: string[]; // Tickers of mutually exclusive markets
  type: "mutually_exclusive" | "complementary";
}

/**
 * Cross-Market Arbitrage Agent
 * 
 * Monitors groups of related markets (e.g., election outcomes, bracket results)
 * and detects when implied probabilities violate basic consistency rules.
 * 
 * Configuration:
 * - groups: Market groups to monitor (mutually exclusive or complementary)
 * - minEdge: Minimum edge threshold (default: 0.05 = 5%)
 */
export class CrossMarketArbAgent {
  private book = new LocalOrderbook();
  private agentId: string;
  private minEdge: number;

  constructor(
    private bus: EventBus,
    private groups: MarketGroup[],
    agentId: string = "cross-market-arb-1",
    minEdge: number = 0.05
  ) {
    this.agentId = agentId;
    this.minEdge = minEdge;
  }

  async start(): Promise<void> {
    await this.bus.subscribe<OrderbookSnapshotMsg>(
      "kalshi.orderbook_snapshot",
      (evt) => this.onSnapshot(evt)
    );

    await this.bus.subscribe<OrderbookDeltaMsg>(
      "kalshi.orderbook_delta",
      (evt) => this.onDelta(evt)
    );

    console.log(`[${this.agentId}] Started, monitoring ${this.groups.length} market groups`);
    for (const group of this.groups) {
      console.log(`  Group: ${group.name} (${group.type})`);
      console.log(`    Markets: ${group.markets.join(", ")}`);
    }
  }

  private async onSnapshot(evt: EventEnvelope<OrderbookSnapshotMsg>): Promise<void> {
    const { market_ticker, yes, no } = evt.data.msg;
    this.book.applySnapshot(market_ticker, yes, no, evt.data.seq);
    await this.checkAllGroups(evt.ts);
  }

  private async onDelta(evt: EventEnvelope<OrderbookDeltaMsg>): Promise<void> {
    const { market_ticker, price, delta, side } = evt.data.msg;
    const applied = this.book.applyDelta(market_ticker, side, price, delta, evt.data.seq);
    
    if (applied) {
      await this.checkAllGroups(evt.ts);
    }
  }

  private async checkAllGroups(ts: number): Promise<void> {
    for (const group of this.groups) {
      await this.checkGroup(group, ts);
    }
  }

  private async checkGroup(group: MarketGroup, ts: number): Promise<void> {
    // Collect mid prices for all markets in group
    const mids: { ticker: string; mid: number }[] = [];

    for (const ticker of group.markets) {
      const quote = this.book.toBestBidAsk(ticker);
      
      if (quote.mid !== null) {
        mids.push({ ticker, mid: quote.mid });
      }
    }

    // Need at least 2 markets to check consistency
    if (mids.length < 2) {
      return;
    }

    // Check for violations based on group type
    if (group.type === "mutually_exclusive") {
      await this.checkMutuallyExclusive(group, mids, ts);
    } else if (group.type === "complementary") {
      await this.checkComplementary(group, mids, ts);
    }
  }

  private async checkMutuallyExclusive(
    group: MarketGroup,
    mids: { ticker: string; mid: number }[],
    ts: number
  ): Promise<void> {
    // For mutually exclusive events, sum of probabilities should equal 1
    // If sum > 1, arbitrage opportunity exists
    const sumProb = mids.reduce((sum, m) => sum + m.mid, 0);
    const edge = sumProb - 1.0;

    if (edge > this.minEdge) {
      const signal: CrossArbSignal = {
        group_id: group.id,
        markets: mids,
        sumProb,
        edge,
        violationType: "sum_exceeds_one",
        ts,
      };

      await this.bus.publish("signals.cross_market_arb", signal);

      console.log(
        `[${this.agentId}] 🔥 Cross-market arbitrage: ${group.name} ` +
        `sum=${sumProb.toFixed(3)} (should be 1.0), edge=${(edge * 100).toFixed(2)}%`
      );

      for (const m of mids) {
        console.log(`  ${m.ticker}: ${m.mid.toFixed(3)}`);
      }
    }
  }

  private async checkComplementary(
    group: MarketGroup,
    mids: { ticker: string; mid: number }[],
    ts: number
  ): Promise<void> {
    // For complementary events (e.g., YES and NO on same outcome),
    // sum should equal 1.0 exactly
    // Any deviation creates arbitrage
    if (mids.length !== 2) {
      console.warn(`[${this.agentId}] Complementary group ${group.id} should have exactly 2 markets`);
      return;
    }

    const sumProb = mids.reduce((sum, m) => sum + m.mid, 0);
    const edge = Math.abs(sumProb - 1.0);

    if (edge > this.minEdge) {
      const signal: CrossArbSignal = {
        group_id: group.id,
        markets: mids,
        sumProb,
        edge,
        violationType: sumProb > 1 ? "sum_exceeds_one" : "negative_prob",
        ts,
      };

      await this.bus.publish("signals.cross_market_arb", signal);

      console.log(
        `[${this.agentId}] 🔥 Complementary arbitrage: ${group.name} ` +
        `sum=${sumProb.toFixed(3)} (should be 1.0), edge=${(edge * 100).toFixed(2)}%`
      );
    }
  }

  async stop(): Promise<void> {
    console.log(`[${this.agentId}] Stopping`);
  }

  // Monitoring
  getGroups(): MarketGroup[] {
    return this.groups;
  }

  getTrackedMarkets(): string[] {
    return this.book.getTickers();
  }
}
