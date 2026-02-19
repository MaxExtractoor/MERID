/**
 * Kalshi Microstructure Agent
 * Complete trading pipeline: Orderbook → Signals → OrderIntents
 * 
 * Flow:
 * 1. Consumes orderbook snapshots/deltas
 * 2. Maintains local book state
 * 3. Computes microstructure features (mid, spread, imbalance, volatility)
 * 4. Applies trading logic (edge detection, Kelly sizing)
 * 5. Emits OrderIntents to Python execution pipeline
 * 
 * Consumes:
 * - kalshi.orderbook_snapshot
 * - kalshi.orderbook_delta
 * - kalshi.trade
 * 
 * Publishes:
 * - signals.microstructure
 * - intents.orders
 */

import { 
  EventBus, 
  EventEnvelope, 
  OrderbookSnapshotMsg, 
  OrderbookDeltaMsg,
  TradeMsg,
  OrderIntent,
  TradeTick
} from "@merid/swarm-kernel";
import { LocalOrderbook } from "./orderbookState";

export interface MicrostructureFeatures {
  market_ticker: string;
  bestBid: number;
  bestAsk: number;
  mid: number;
  spread: number;
  bidDepth: number;
  askDepth: number;
  imbalance: number;
  recentVol: number;  // Recent price volatility
  tradeCount: number;
  ts: number;
}

export interface TradingConfig {
  agentId: string;
  sessionId: string;
  targetMarkets: string[];
  minEdge: number;           // Minimum edge required to trade (default: 0.02 = 2%)
  maxSpread: number;         // Skip if spread > threshold (default: 0.05 = 5%)
  maxPositionSize: number;   // Per-market position limit (default: 100)
  kellyFraction: number;     // Kelly fraction (default: 0.25 = quarter Kelly)
  minConfidence: number;     // Min confidence to trade (default: 0.5)
  enableLiveTrading: boolean; // Safety flag (default: false)
}

export class KalshiMicrostructureAgent {
  private book = new LocalOrderbook();
  private config: TradingConfig;
  private positions: Map<string, number> = new Map();
  private recentTrades: Map<string, TradeTick[]> = new Map();
  private tradeWindowMs = 60000; // 1 minute rolling window

  constructor(private bus: EventBus, config: Partial<TradingConfig>) {
    this.config = {
      agentId: config.agentId ?? "kalshi-microstructure-1",
      sessionId: config.sessionId ?? `session-${Date.now()}`,
      targetMarkets: config.targetMarkets ?? [],
      minEdge: config.minEdge ?? 0.02,
      maxSpread: config.maxSpread ?? 0.05,
      maxPositionSize: config.maxPositionSize ?? 100,
      kellyFraction: config.kellyFraction ?? 0.25,
      minConfidence: config.minConfidence ?? 0.5,
      enableLiveTrading: config.enableLiveTrading ?? false,
    };
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

    await this.bus.subscribe<TradeMsg>(
      "kalshi.trade",
      (evt) => this.onTrade(evt)
    );

    console.log(`[${this.config.agentId}] Started`);
    console.log(`  Session: ${this.config.sessionId}`);
    console.log(`  Markets: ${this.config.targetMarkets.join(", ")}`);
    console.log(`  Min Edge: ${(this.config.minEdge * 100).toFixed(1)}%`);
    console.log(`  Live Trading: ${this.config.enableLiveTrading}`);
  }

  private async onSnapshot(evt: EventEnvelope<OrderbookSnapshotMsg>): Promise<void> {
    const { market_ticker, yes, no } = evt.data.msg;

    // Filter by target markets if configured
    if (this.config.targetMarkets.length > 0 && !this.config.targetMarkets.includes(market_ticker)) {
      return;
    }

    this.book.applySnapshot(market_ticker, yes, no, evt.data.seq);
    await this.processMarket(market_ticker, evt.ts);
  }

  private async onDelta(evt: EventEnvelope<OrderbookDeltaMsg>): Promise<void> {
    const { market_ticker, price, delta, side } = evt.data.msg;

    // Filter by target markets
    if (this.config.targetMarkets.length > 0 && !this.config.targetMarkets.includes(market_ticker)) {
      return;
    }

    const applied = this.book.applyDelta(market_ticker, side, price, delta, evt.data.seq);
    if (applied) {
      await this.processMarket(market_ticker, evt.ts);
    }
  }

  private async onTrade(evt: EventEnvelope<TradeMsg>): Promise<void> {
    const { market_ticker, price, size, ts } = evt.data.msg;

    // Filter by target markets
    if (this.config.targetMarkets.length > 0 && !this.config.targetMarkets.includes(market_ticker)) {
      return;
    }

    // Store trade for volatility calculation
    const tick: TradeTick = {
      market_ticker,
      price: price / 100, // Normalize to 0-1
      size,
      ts: new Date(ts).getTime(),
    };

    const trades = this.recentTrades.get(market_ticker) ?? [];
    trades.push(tick);

    // Keep only recent trades (rolling window)
    const cutoff = Date.now() - this.tradeWindowMs;
    this.recentTrades.set(
      market_ticker,
      trades.filter(t => t.ts >= cutoff)
    );
  }

  private async processMarket(ticker: string, ts: number): Promise<void> {
    // Compute features
    const features = this.computeFeatures(ticker, ts);
    if (!features) return;

    // Publish microstructure signal
    await this.bus.publish("signals.microstructure", features);

    // Generate trading intent if appropriate
    await this.generateIntent(features);
  }

  private computeFeatures(ticker: string, ts: number): MicrostructureFeatures | null {
    const quote = this.book.toBestBidAsk(ticker);

    if (quote.bestBid === null || quote.bestAsk === null) {
      return null;
    }

    // Compute volatility from recent trades
    const trades = this.recentTrades.get(ticker) ?? [];
    const recentVol = this.computeVolatility(trades);

    return {
      market_ticker: ticker,
      bestBid: quote.bestBid,
      bestAsk: quote.bestAsk,
      mid: quote.mid!,
      spread: quote.spread!,
      bidDepth: quote.bidDepth,
      askDepth: quote.askDepth,
      imbalance: quote.imbalance,
      recentVol,
      tradeCount: trades.length,
      ts,
    };
  }

  private computeVolatility(trades: TradeTick[]): number {
    if (trades.length < 2) return 0;

    const prices = trades.map(t => t.price);
    const mean = prices.reduce((sum, p) => sum + p, 0) / prices.length;
    const variance = prices.reduce((sum, p) => sum + Math.pow(p - mean, 2), 0) / (prices.length - 1);

    return Math.sqrt(variance);
  }

  private async generateIntent(features: MicrostructureFeatures): Promise<void> {
    const { market_ticker, bestBid, bestAsk, mid, spread, imbalance } = features;

    // Filter 1: Skip wide markets
    if (spread > this.config.maxSpread) {
      return;
    }

    // Filter 2: Check position limits
    const currentPosition = this.positions.get(market_ticker) ?? 0;
    if (Math.abs(currentPosition) >= this.config.maxPositionSize) {
      return;
    }

    // Simple strategy: Buy if positive imbalance, sell if negative
    // In production, this would use model predictions for edge detection
    const shouldBuy = imbalance > 0.3;  // More bid depth than ask
    const shouldSell = imbalance < -0.3; // More ask depth than bid

    if (!shouldBuy && !shouldSell) {
      return;
    }

    // Compute edge (in production, this would come from model predictions)
    // Here we use imbalance as a proxy for edge
    const rawEdge = Math.abs(imbalance) * 0.05; // Scale to reasonable edge estimate

    // Filter 3: Minimum edge requirement
    if (rawEdge < this.config.minEdge) {
      return;
    }

    // Compute confidence based on signal strength
    const confidence = Math.min(Math.abs(imbalance), 1.0);

    if (confidence < this.config.minConfidence) {
      return;
    }

    // Kelly sizing: f = edge / odds
    // For binary market: f = (p - q) / (1 - q) where p = true prob, q = market prob
    const kellyFraction = rawEdge / spread;
    const baseSize = Math.floor(kellyFraction * this.config.maxPositionSize * this.config.kellyFraction);
    const qty = Math.max(1, Math.min(baseSize, 10)); // Cap at 10 for safety

    // Determine side and price
    const side = shouldBuy ? "buy_yes" : "sell_yes";
    const price = shouldBuy ? bestBid + 0.01 : bestAsk - 0.01; // Slight improvement over best

    // Create intent
    const intent: OrderIntent = {
      session_id: this.config.sessionId,
      agent_id: this.config.agentId,
      market_ticker,
      side,
      qty,
      price: Math.max(0.01, Math.min(0.99, price)), // Bound to valid range
      client_tag: `${this.config.sessionId}:${this.config.agentId}:${market_ticker}:${Date.now()}`,
      confidence,
      rationale: `Imbalance=${imbalance.toFixed(2)}, edge=${(rawEdge * 100).toFixed(1)}%, Kelly=${kellyFraction.toFixed(2)}`,
      timestamp: Date.now(),
    };

    // Publish intent (if live trading enabled)
    if (this.config.enableLiveTrading) {
      await this.bus.publish("intents.orders", intent);

      console.log(
        `[${this.config.agentId}] Intent: ${side} ${qty}x ${market_ticker} @ ${price.toFixed(3)} ` +
        `(conf=${confidence.toFixed(2)}, edge=${(rawEdge * 100).toFixed(1)}%)`
      );
    } else {
      console.log(
        `[${this.config.agentId}] [PAPER] Intent: ${side} ${qty}x ${market_ticker} @ ${price.toFixed(3)} ` +
        `(conf=${confidence.toFixed(2)}, edge=${(rawEdge * 100).toFixed(1)}%)`
      );
    }
  }

  async stop(): Promise<void> {
    console.log(`[${this.config.agentId}] Stopping`);
  }

  // Monitoring methods
  getTrackedMarkets(): string[] {
    return this.book.getTickers();
  }

  getPosition(ticker: string): number {
    return this.positions.get(ticker) ?? 0;
  }

  getTotalPositions(): number {
    return Array.from(this.positions.values()).reduce((sum, pos) => sum + Math.abs(pos), 0);
  }

  recordFill(ticker: string, side: string, qty: number): void {
    const current = this.positions.get(ticker) ?? 0;
    const delta = side.includes("buy") ? qty : -qty;
    this.positions.set(ticker, current + delta);
  }
}
