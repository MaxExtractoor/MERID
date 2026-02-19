/**
 * Orderbook Delta Agent
 * Processes Kalshi orderbook snapshots and deltas, publishes features
 * 
 * Consumes:
 * - kalshi.orderbook_snapshot
 * - kalshi.orderbook_delta
 * 
 * Publishes:
 * - signals.orderbook_features
 */

import { LocalOrderbook } from "./orderbookState";
import { EventBus, EventEnvelope, OrderbookSnapshotMsg, OrderbookDeltaMsg, OrderbookFeatures } from "@merid/swarm-kernel";

export class OrderbookDeltaAgent {
  private book = new LocalOrderbook();
  private bus: EventBus;
  private agentId: string;

  constructor(bus: EventBus, agentId: string = "orderbook-delta-1") {
    this.bus = bus;
    this.agentId = agentId;
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

    console.log(`[${this.agentId}] Started, subscribed to orderbook events`);
  }

  private async onSnapshot(evt: EventEnvelope<OrderbookSnapshotMsg>): Promise<void> {
    const msg = evt.data;
    const { market_ticker, yes, no, seq } = msg.msg;

    this.book.applySnapshot(market_ticker, yes, no, seq);

    // Publish features after snapshot
    await this.publishFeatures(market_ticker, evt.ts);
  }

  private async onDelta(evt: EventEnvelope<OrderbookDeltaMsg>): Promise<void> {
    const msg = evt.data;
    const { market_ticker, price, delta, side, seq } = msg.msg;

    const applied = this.book.applyDelta(market_ticker, side, price, delta, seq);

    if (!applied) {
      // Out-of-order or invalid delta
      return;
    }

    // Publish features after each delta
    await this.publishFeatures(market_ticker, evt.ts);
  }

  private async publishFeatures(ticker: string, ts: number): Promise<void> {
    const quote = this.book.toBestBidAsk(ticker);

    // Only publish if we have valid quotes
    if (quote.bestBid === null || quote.bestAsk === null) {
      console.warn(`[${this.agentId}] No valid quotes for ${ticker}`);
      return;
    }

    const features: OrderbookFeatures = {
      market_ticker: ticker,
      bestBid: quote.bestBid,
      bestAsk: quote.bestAsk,
      mid: quote.mid!,
      spread: quote.spread!,
      bidDepth: quote.bidDepth,
      askDepth: quote.askDepth,
      imbalance: quote.imbalance,
      ts,
    };

    await this.bus.publish("signals.orderbook_features", features);

    console.log(
      `[${this.agentId}] ${ticker}: mid=${features.mid.toFixed(3)}, ` +
      `spread=${features.spread.toFixed(3)}, imb=${features.imbalance.toFixed(2)}`
    );
  }

  async stop(): Promise<void> {
    console.log(`[${this.agentId}] Stopping`);
  }

  // Expose for monitoring
  getTrackedMarkets(): string[] {
    return this.book.getTickers();
  }

  isMarketStale(ticker: string, thresholdMs: number = 30000): boolean {
    return this.book.isStale(ticker, thresholdMs);
  }
}
