/**
 * Kalshi Arbitrage Detection Agent
 * Detects arbitrage opportunities from orderbook updates
 * 
 * Checks for:
 * - YES bid + NO bid > 1 (internal arbitrage)
 * - Cross-market inconsistencies (future extension)
 * 
 * Consumes:
 * - kalshi.orderbook_snapshot
 * - kalshi.orderbook_delta
 * 
 * Publishes:
 * - signals.arbitrage
 */

import { EventBus, EventEnvelope, OrderbookSnapshotMsg, OrderbookDeltaMsg } from "@merid/swarm-kernel";
import { LocalOrderbook } from "./orderbookState";
import { detectArbitrageEdge } from "@merid/swarm-kernel/orderbookMath";

export interface ArbSignal {
  market_ticker: string;
  bestBid: number;
  bestAsk: number;
  yesPlusNo: number;
  edge: number;
  ts: number;
  severity: "low" | "medium" | "high";
}

export class KalshiArbitrageAgent {
  private book = new LocalOrderbook();
  private agentId: string;
  private minEdgeThreshold: number;

  constructor(
    private bus: EventBus,
    agentId: string = "arbitrage-detector-1",
    minEdgeThreshold: number = 0.01 // 1% minimum edge
  ) {
    this.agentId = agentId;
    this.minEdgeThreshold = minEdgeThreshold;
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

    console.log(`[${this.agentId}] Started, min edge threshold=${this.minEdgeThreshold}`);
  }

  private async onSnapshot(evt: EventEnvelope<OrderbookSnapshotMsg>): Promise<void> {
    const { market_ticker, yes, no } = evt.data.msg;
    this.book.applySnapshot(market_ticker, yes, no, evt.data.seq);
    await this.checkArbitrage(market_ticker, evt.ts);
  }

  private async onDelta(evt: EventEnvelope<OrderbookDeltaMsg>): Promise<void> {
    const { market_ticker, price, delta, side } = evt.data.msg;
    this.book.applyDelta(market_ticker, side, price, delta, evt.data.seq);
    await this.checkArbitrage(market_ticker, evt.ts);
  }

  private async checkArbitrage(ticker: string, ts: number): Promise<void> {
    const quote = this.book.toBestBidAsk(ticker);

    if (quote.bestBid === null || quote.bestAsk === null) {
      return;
    }

    // Get raw integer prices for edge calculation
    const bestYesBid = this.book.getBestYesBid(ticker);
    const bestNoBid = this.book.getBestNoBid(ticker);

    if (bestYesBid === null || bestNoBid === null) {
      return;
    }

    // Convert to decimal probabilities
    const yesBid = bestYesBid / 100;
    const noBid = bestNoBid / 100;
    const yesPlusNo = yesBid + noBid;

    // Edge = amount by which YES bid + NO bid exceeds 1.0
    // Positive edge means you can buy both YES and NO for less than 1 cent
    const edge = yesPlusNo - 1;

    if (edge > this.minEdgeThreshold) {
      const severity = this.classifySeverity(edge);

      const signal: ArbSignal = {
        market_ticker: ticker,
        bestBid: quote.bestBid,
        bestAsk: quote.bestAsk,
        yesPlusNo,
        edge,
        ts,
        severity,
      };

      await this.bus.publish("signals.arbitrage", signal);

      console.log(
        `[${this.agentId}] 🔥 Arbitrage detected: ${ticker} ` +
        `edge=${(edge * 100).toFixed(2)}% severity=${severity} ` +
        `(YES_bid=${yesBid.toFixed(3)} + NO_bid=${noBid.toFixed(3)} = ${yesPlusNo.toFixed(3)})`
      );
    }
  }

  private classifySeverity(edge: number): "low" | "medium" | "high" {
    if (edge > 0.05) return "high";    // >5% edge
    if (edge > 0.02) return "medium";  // 2-5% edge
    return "low";                      // 1-2% edge
  }

  async stop(): Promise<void> {
    console.log(`[${this.agentId}] Stopping`);
  }

  // Monitoring
  getTrackedMarkets(): string[] {
    return this.book.getTickers();
  }
}
