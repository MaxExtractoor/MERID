/**
 * Trade Subscriber Agent
 * Subscribes to Kalshi trade channel and publishes trade ticks
 * 
 * Consumes:
 * - kalshi.trade (from bridge)
 * 
 * Publishes:
 * - kalshi.trades (normalized)
 */

import { EventBus, EventEnvelope, TradeMsg, TradeTick } from "@merid/swarm-kernel";

export class TradeSubscriberAgent {
  private agentId: string;
  private tradeCount: Map<string, number> = new Map();
  private lastTradeTime: Map<string, number> = new Map();

  constructor(private bus: EventBus, agentId: string = "trade-subscriber-1") {
    this.agentId = agentId;
  }

  async start(): Promise<void> {
    await this.bus.subscribe<TradeMsg>(
      "kalshi.trade",
      (evt) => this.handleTrade(evt)
    );

    console.log(`[${this.agentId}] Started, subscribed to kalshi.trade`);
  }

  private async handleTrade(evt: EventEnvelope<TradeMsg>): Promise<void> {
    const msg = evt.data;
    
    if (msg.type !== "trade") {
      return;
    }

    const { market_ticker, price, size, ts } = msg.msg;

    // Convert Kalshi integer price (0-100) to decimal probability (0-1)
    const normalizedPrice = price / 100;

    // Parse ISO timestamp to milliseconds
    const timestampMs = new Date(ts).getTime();

    const tick: TradeTick = {
      market_ticker,
      price: normalizedPrice,
      size,
      ts: timestampMs,
    };

    // Update stats
    const count = (this.tradeCount.get(market_ticker) ?? 0) + 1;
    this.tradeCount.set(market_ticker, count);
    this.lastTradeTime.set(market_ticker, timestampMs);

    // Publish normalized trade
    await this.bus.publish("kalshi.trades", tick);

    console.log(
      `[${this.agentId}] Trade: ${market_ticker} @ ${normalizedPrice.toFixed(3)} ` +
      `size=${size} (total_trades=${count})`
    );
  }

  async stop(): Promise<void> {
    console.log(`[${this.agentId}] Stopping`);
  }

  // Monitoring methods
  getTradeCount(ticker: string): number {
    return this.tradeCount.get(ticker) ?? 0;
  }

  getLastTradeTime(ticker: string): number | null {
    return this.lastTradeTime.get(ticker) ?? null;
  }

  getTrackedMarkets(): string[] {
    return Array.from(this.tradeCount.keys());
  }

  getTotalTrades(): number {
    return Array.from(this.tradeCount.values()).reduce((sum, count) => sum + count, 0);
  }
}
