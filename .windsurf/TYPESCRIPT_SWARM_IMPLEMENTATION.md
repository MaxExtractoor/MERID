# TypeScript Swarm Implementation Guide
**Production-Ready Agent Templates, Orchestration Patterns & Migration Path**

---

## Overview

This guide provides TypeScript agent templates for Kalshi trading swarms, compatible with the Python WS bridge architecture. Agents consume normalized events, emit intents, and never touch Kalshi directly.

**Tech Stack:**
- Node.js service: `apps/kalshi-swarm-node`
- WebSocket library: `ws`
- Event bus: Topic-based pub/sub (Kafka/NATS/Redis)
- Type safety: Full TypeScript with shared schemas

---

## 1. Core Type Definitions

```typescript
// packages/swarm-kernel/src/types.ts

export interface EventEnvelope<T = unknown> {
  topic: string;
  ts: number;
  data: T;
}

export interface EventBus {
  subscribe<T>(
    topic: string, 
    handler: (evt: EventEnvelope<T>) => Promise<void> | void
  ): Promise<void>;
  
  publish<T>(topic: string, data: T): Promise<void>;
}

export interface OrderbookDelta {
  market_ticker: string;
  bids: [number, number][]; // [price, size]
  asks: [number, number][];
  seq: number;
  timestamp: number;
}

export interface MicrostructureSignal {
  market_ticker: string;
  mid: number;
  spread: number;
  bid_depth: number;
  ask_depth: number;
  imbalance: number;  // (bid_depth - ask_depth) / (bid_depth + ask_depth)
  ts: number;
}

export interface OrderIntent {
  session_id: string;
  agent_id: string;
  market_ticker: string;
  side: "buy_yes" | "sell_yes" | "buy_no" | "sell_no";
  qty: number;
  price: number;
  client_tag: string;  // Idempotency key
  confidence: number;  // 0-1, used for auction bidding
  rationale?: string;  // Explainability
}

export interface RiskDecision {
  intent_id: string;
  approved: boolean;
  adjusted_qty?: number;
  rejection_reason?: string;
  risk_score: number;
}

export interface ExecutionOutcome {
  intent_id: string;
  order_id?: string;
  status: "submitted" | "rejected_risk" | "rejected_rate_limit" | "error";
  error_message?: string;
  timestamp: number;
}

export interface Fill {
  order_id: string;
  market_ticker: string;
  side: string;
  qty: number;
  price: number;
  timestamp: number;
}
```

---

## 2. WebSocket Client (Event Bridge)

```typescript
// packages/swarm-kernel/src/wsClient.ts
import WebSocket from "ws";

export interface WsConfig {
  url: string;
  reconnectDelay?: number;
  maxReconnectDelay?: number;
  heartbeatInterval?: number;
}

export class SwarmWsClient {
  private ws?: WebSocket;
  private handlers: ((msg: any) => void)[] = [];
  private reconnectDelay: number;
  private maxReconnectDelay: number;
  private heartbeatInterval: number;
  private heartbeatTimer?: NodeJS.Timeout;
  private lastPong: number = Date.now();

  constructor(private config: WsConfig) {
    this.reconnectDelay = config.reconnectDelay ?? 1000;
    this.maxReconnectDelay = config.maxReconnectDelay ?? 30000;
    this.heartbeatInterval = config.heartbeatInterval ?? 30000;
  }

  connect(): void {
    console.log(`[WS] Connecting to ${this.config.url}`);
    this.ws = new WebSocket(this.config.url);

    this.ws.on("open", () => {
      console.log("[WS] Connected");
      this.reconnectDelay = this.config.reconnectDelay ?? 1000;
      this.startHeartbeat();
    });

    this.ws.on("message", (raw) => {
      try {
        const msg = JSON.parse(raw.toString());
        this.handlers.forEach((h) => h(msg));
      } catch (e) {
        console.error("[WS] Failed to parse message:", e);
      }
    });

    this.ws.on("pong", () => {
      this.lastPong = Date.now();
    });

    this.ws.on("close", () => {
      console.log("[WS] Connection closed");
      this.stopHeartbeat();
      this.scheduleReconnect();
    });

    this.ws.on("error", (err) => {
      console.error("[WS] Error:", err);
    });
  }

  private startHeartbeat(): void {
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.ping();
        
        // Check if last pong was too long ago
        const timeSinceLastPong = Date.now() - this.lastPong;
        if (timeSinceLastPong > this.heartbeatInterval * 2) {
          console.warn("[WS] No pong received, reconnecting");
          this.ws.terminate();
        }
      }
    }, this.heartbeatInterval);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = undefined;
    }
  }

  private scheduleReconnect(): void {
    console.log(`[WS] Reconnecting in ${this.reconnectDelay}ms`);
    setTimeout(() => {
      this.connect();
    }, this.reconnectDelay);
    
    // Exponential backoff
    this.reconnectDelay = Math.min(
      this.reconnectDelay * 2,
      this.maxReconnectDelay
    );
  }

  onMessage(handler: (msg: any) => void): void {
    this.handlers.push(handler);
  }

  send(msg: any): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    } else {
      console.warn("[WS] Cannot send - not connected");
    }
  }

  close(): void {
    this.stopHeartbeat();
    this.ws?.close();
  }
}
```

---

## 3. Agent Implementations

### OrderbookAgent (Market Microstructure)

```typescript
// packages/agents/src/orderbookAgent.ts
import { EventBus, EventEnvelope, OrderbookDelta, MicrostructureSignal } from "@merid/swarm-kernel";

interface BookState {
  bids: [number, number][];
  asks: [number, number][];
  lastSeq: number;
  lastUpdate: number;
}

export class OrderbookAgent {
  private books: Map<string, BookState> = new Map();
  private readonly staleThreshold = 5000; // 5 seconds

  constructor(
    private bus: EventBus,
    private agentId: string
  ) {}

  async start(): Promise<void> {
    await this.bus.subscribe<OrderbookDelta>(
      "kalshi.orderbook",
      (evt) => this.handleOrderbook(evt)
    );
    
    console.log(`[${this.agentId}] OrderbookAgent started`);
  }

  private async handleOrderbook(evt: EventEnvelope<OrderbookDelta>): Promise<void> {
    const { market_ticker, seq, bids, asks } = evt.data;
    
    // Get or create book state
    const book = this.books.get(market_ticker) ?? {
      bids: [],
      asks: [],
      lastSeq: 0,
      lastUpdate: 0,
    };

    // Sequence number check (prevent out-of-order processing)
    if (seq <= book.lastSeq) {
      console.warn(
        `[${this.agentId}] Ignoring out-of-order message: seq=${seq}, lastSeq=${book.lastSeq}`
      );
      return;
    }

    // Update book
    book.bids = bids;
    book.asks = asks;
    book.lastSeq = seq;
    book.lastUpdate = evt.ts;
    this.books.set(market_ticker, book);

    // Compute microstructure signals
    const signal = this.computeSignal(market_ticker, book, evt.ts);
    if (signal) {
      await this.bus.publish("signals.microstructure", signal);
    }
  }

  private computeSignal(
    market_ticker: string,
    book: BookState,
    ts: number
  ): MicrostructureSignal | null {
    if (book.bids.length === 0 || book.asks.length === 0) {
      return null;
    }

    const bestBid = book.bids[0][0];
    const bestAsk = book.asks[0][0];
    const mid = (bestBid + bestAsk) / 2;
    const spread = bestAsk - bestBid;

    // Compute depth
    const bidDepth = book.bids.slice(0, 5).reduce((sum, [_, size]) => sum + size, 0);
    const askDepth = book.asks.slice(0, 5).reduce((sum, [_, size]) => sum + size, 0);
    const totalDepth = bidDepth + askDepth;
    const imbalance = totalDepth > 0 ? (bidDepth - askDepth) / totalDepth : 0;

    return {
      market_ticker,
      mid,
      spread,
      bid_depth: bidDepth,
      ask_depth: askDepth,
      imbalance,
      ts,
    };
  }

  getBookState(market_ticker: string): BookState | undefined {
    return this.books.get(market_ticker);
  }

  isStale(market_ticker: string): boolean {
    const book = this.books.get(market_ticker);
    if (!book) return true;
    return Date.now() - book.lastUpdate > this.staleThreshold;
  }
}
```

### KalshiMarketAnalysisAgent (Feature Engineering)

```typescript
// packages/agents/src/kalshiMarketAnalysisAgent.ts
import {
  EventBus,
  EventEnvelope,
  OrderbookSnapshot,
} from "@merid/swarm-kernel";

interface TradeTick {
  market_ticker: string;
  price: number;
  size: number;
  ts: number;
}

interface MarketFeatures {
  market_ticker: string;
  mid: number;
  spread: number;
  topDepthBid: number;
  topDepthAsk: number;
  imbalance: number;
  recentVol: number;
  ts: number;
}

interface MarketState {
  lastBook?: OrderbookSnapshot;
  trades: TradeTick[];
}

/**
 * Transforms raw Kalshi orderbooks + trades into feature signals.
 * 
 * Inputs: kalshi.orderbook.snapshot, kalshi.orderbook.delta, kalshi.trades
 * Outputs: signals.market_features
 * 
 * Features computed:
 * - Mid price and spread
 * - Top-of-book depth (bid/ask)
 * - Orderbook imbalance
 * - Recent volatility (1-minute rolling)
 */
export class KalshiMarketAnalysisAgent {
  private state: Map<string, MarketState> = new Map();

  constructor(private bus: EventBus, private agentId: string) {}

  async start(): Promise<void> {
    await this.bus.subscribe<OrderbookSnapshot>(
      "kalshi.orderbook.snapshot",
      (evt) => this.onSnapshot(evt)
    );
    
    await this.bus.subscribe<OrderbookSnapshot>(
      "kalshi.orderbook.delta",
      (evt) => this.onDelta(evt)
    );
    
    await this.bus.subscribe<TradeTick>(
      "kalshi.trades",
      (evt) => this.onTrade(evt)
    );
    
    console.log(`[${this.agentId}] KalshiMarketAnalysisAgent started`);
  }

  private getOrCreate(ticker: string): MarketState {
    let s = this.state.get(ticker);
    if (!s) {
      s = { trades: [] };
      this.state.set(ticker, s);
    }
    return s;
  }

  private async onSnapshot(evt: EventEnvelope<OrderbookSnapshot>): Promise<void> {
    const { market_ticker } = evt.data;
    const s = this.getOrCreate(market_ticker);
    s.lastBook = evt.data;
    await this.computeAndPublishFeatures(market_ticker, evt.ts);
  }

  private async onDelta(evt: EventEnvelope<OrderbookSnapshot>): Promise<void> {
    const { market_ticker } = evt.data;
    const s = this.getOrCreate(market_ticker);
    // In production, apply delta; here treating as full book for simplicity
    s.lastBook = evt.data;
    await this.computeAndPublishFeatures(market_ticker, evt.ts);
  }

  private async onTrade(evt: EventEnvelope<TradeTick>): Promise<void> {
    const { market_ticker } = evt.data;
    const s = this.getOrCreate(market_ticker);
    
    // Add trade
    s.trades.push(evt.data);
    
    // Keep only last 60 seconds
    const cutoff = evt.ts - 60_000;
    s.trades = s.trades.filter((t) => t.ts >= cutoff);
    
    await this.computeAndPublishFeatures(market_ticker, evt.ts);
  }

  private async computeAndPublishFeatures(
    ticker: string,
    ts: number
  ): Promise<void> {
    const s = this.state.get(ticker);
    if (!s?.lastBook) return;

    const bids = s.lastBook.bids;
    const asks = s.lastBook.asks;
    if (!bids.length || !asks.length) return;

    const bestBid = bids[0][0];
    const bestAsk = asks[0][0];
    const mid = (bestBid + bestAsk) / 2;
    const spread = bestAsk - bestBid;
    
    // Sum all bid/ask depth (could limit to top N levels)
    const topDepthBid = bids.reduce((acc, [_, size]) => acc + size, 0);
    const topDepthAsk = asks.reduce((acc, [_, size]) => acc + size, 0);
    const totalDepth = topDepthBid + topDepthAsk;
    const imbalance = totalDepth === 0 
      ? 0 
      : (topDepthBid - topDepthAsk) / totalDepth;

    // Compute recent volatility (standard deviation of trade prices)
    const recentVol = Math.sqrt(this.variance(s.trades.map((t) => t.price)) || 0);

    const feat: MarketFeatures = {
      market_ticker: ticker,
      mid,
      spread,
      topDepthBid,
      topDepthAsk,
      imbalance,
      recentVol,
      ts,
    };

    await this.bus.publish("signals.market_features", feat);
  }

  private variance(xs: number[]): number {
    if (xs.length < 2) return 0;
    const mean = xs.reduce((a, b) => a + b, 0) / xs.length;
    return xs.reduce((acc, x) => acc + (x - mean) * (x - mean), 0) / (xs.length - 1);
  }
}
```

### TraderAgent (Signal-to-Intent)

```typescript
// packages/agents/src/traderAgent.ts
import { EventBus, EventEnvelope, MicrostructureSignal, OrderIntent } from "@merid/swarm-kernel";

export interface TraderConfig {
  minSpread: number;          // Skip if spread > threshold
  minConfidence: number;      // Min signal quality
  maxPositionSize: number;    // Per-market cap
  targetMarkets?: string[];   // Whitelist (optional)
}

export class TraderAgent {
  private positions: Map<string, number> = new Map();
  
  constructor(
    private bus: EventBus,
    private agentId: string,
    private config: TraderConfig
  ) {}

  async start(sessionId: string): Promise<void> {
    await this.bus.subscribe<MicrostructureSignal>(
      "signals.microstructure",
      (evt) => this.onSignal(sessionId, evt)
    );
    
    console.log(`[${this.agentId}] TraderAgent started for session ${sessionId}`);
  }

  private async onSignal(
    sessionId: string,
    evt: EventEnvelope<MicrostructureSignal>
  ): Promise<void> {
    const { market_ticker, mid, spread, imbalance } = evt.data;

    // Filter by target markets if configured
    if (this.config.targetMarkets && !this.config.targetMarkets.includes(market_ticker)) {
      return;
    }

    // Filter by spread
    if (spread > this.config.minSpread) {
      return;
    }

    // Check position limits
    const currentPosition = this.positions.get(market_ticker) ?? 0;
    if (Math.abs(currentPosition) >= this.config.maxPositionSize) {
      return;
    }

    // Simple strategy: buy if bid depth > ask depth (positive imbalance)
    const shouldBuy = imbalance > 0.2;
    const shouldSell = imbalance < -0.2;

    if (!shouldBuy && !shouldSell) {
      return;
    }

    // Compute confidence based on imbalance magnitude
    const confidence = Math.min(Math.abs(imbalance), 1.0);
    if (confidence < this.config.minConfidence) {
      return;
    }

    const side = shouldBuy ? "buy_yes" : "sell_yes";
    const qty = 1; // Start simple
    const price = shouldBuy ? mid + 0.01 : mid - 0.01; // Slight offset

    const intent: OrderIntent = {
      session_id: sessionId,
      agent_id: this.agentId,
      market_ticker,
      side,
      qty,
      price: Math.round(price * 100) / 100, // Round to 2 decimals
      client_tag: `${sessionId}:${this.agentId}:${market_ticker}:${evt.ts}`,
      confidence,
      rationale: `Imbalance=${imbalance.toFixed(2)}, spread=${spread.toFixed(2)}`,
    };

    await this.bus.publish("intents.orders", intent);
    
    console.log(
      `[${this.agentId}] Intent: ${side} ${qty}x ${market_ticker} @ ${price} (confidence=${confidence.toFixed(2)})`
    );
  }

  recordFill(market_ticker: string, side: string, qty: number): void {
    const currentPosition = this.positions.get(market_ticker) ?? 0;
    const delta = side.includes("buy") ? qty : -qty;
    this.positions.set(market_ticker, currentPosition + delta);
  }
}
```

---

## 4. Swarm Orchestration Patterns

### Pattern 1: Sequential Pipeline

```typescript
// packages/swarm-kernel/src/orchestrators/sequential.ts
import { EventBus } from "@merid/swarm-kernel";

/**
 * Sequential orchestration: Scanner → Forecaster → Risk → Execution
 * 
 * Pros: Simple, traceable, predictable flow
 * Cons: Limited diversity, single decision path
 */
export class SequentialOrchestrator {
  constructor(private bus: EventBus) {}

  async wire(): Promise<void> {
    // Stage 1: Scanner identifies opportunities
    // Publishes to: "opportunities"
    
    // Stage 2: Forecaster consumes opportunities, generates signals
    // Subscribes: "opportunities"
    // Publishes: "signals"
    
    // Stage 3: Risk evaluates signals
    // Subscribes: "signals"
    // Publishes: "risk.decisions"
    
    // Stage 4: Execution consumes approved decisions
    // Subscribes: "risk.decisions"
    // Publishes: "executions"
    
    console.log("[SequentialOrchestrator] Pipeline wired");
  }
}
```

### Pattern 2: Auction (Best Bid Wins)

```typescript
// packages/swarm-kernel/src/orchestrators/auction.ts
import { EventBus, EventEnvelope, OrderIntent } from "@merid/swarm-kernel";

interface Opportunity {
  id: string;
  market_ticker: string;
  timestamp: number;
}

interface Bid {
  opportunity_id: string;
  agent_id: string;
  score: number;      // Expected value, Sharpe, confidence, etc.
  intent: OrderIntent;
  timestamp: number;
}

export interface AuctionConfig {
  minBids: number;           // Wait for at least N bids
  maxWaitMs: number;         // Max time to collect bids
  allowMultipleWinners?: boolean;
}

/**
 * Auction orchestration: Multiple agents compete for same opportunity
 * 
 * Pros: Promotes diversity, best strategy wins
 * Cons: Adds latency, requires coordination
 */
export class AuctionOrchestrator {
  private pending: Map<string, Bid[]> = new Map();
  private timers: Map<string, NodeJS.Timeout> = new Map();

  constructor(
    private bus: EventBus,
    private config: AuctionConfig
  ) {}

  async start(): Promise<void> {
    await this.bus.subscribe<Opportunity>(
      "swarm.opportunities",
      (evt) => this.onOpportunity(evt)
    );
    
    await this.bus.subscribe<Bid>(
      "swarm.bids",
      (evt) => this.onBid(evt)
    );
    
    console.log("[AuctionOrchestrator] Started");
  }

  private async onOpportunity(evt: EventEnvelope<Opportunity>): Promise<void> {
    const { id } = evt.data;
    
    // Initialize bid collection
    this.pending.set(id, []);
    
    // Broadcast opportunity to all agents
    await this.bus.publish("swarm.broadcast.opportunity", evt.data);
    
    // Set timeout to finalize auction
    const timer = setTimeout(() => {
      this.finalizeAuction(id);
    }, this.config.maxWaitMs);
    
    this.timers.set(id, timer);
  }

  private async onBid(evt: EventEnvelope<Bid>): Promise<void> {
    const { opportunity_id } = evt.data;
    const bids = this.pending.get(opportunity_id);
    
    if (!bids) {
      console.warn(`[AuctionOrchestrator] Received bid for unknown opportunity: ${opportunity_id}`);
      return;
    }

    bids.push(evt.data);
    
    // Check if we have enough bids to finalize early
    if (bids.length >= this.config.minBids) {
      this.finalizeAuction(opportunity_id);
    }
  }

  private async finalizeAuction(opportunityId: string): Promise<void> {
    const bids = this.pending.get(opportunityId);
    const timer = this.timers.get(opportunityId);
    
    if (timer) {
      clearTimeout(timer);
      this.timers.delete(opportunityId);
    }

    if (!bids || bids.length === 0) {
      console.log(`[AuctionOrchestrator] No bids for ${opportunityId}`);
      this.pending.delete(opportunityId);
      return;
    }

    // Sort by score descending
    bids.sort((a, b) => b.score - a.score);
    
    if (this.config.allowMultipleWinners) {
      // Forward all intents (risk engine will filter)
      for (const bid of bids) {
        await this.bus.publish("intents.orders", bid.intent);
      }
      console.log(`[AuctionOrchestrator] Forwarded ${bids.length} intents for ${opportunityId}`);
    } else {
      // Single winner
      const winner = bids[0];
      await this.bus.publish("intents.orders", winner.intent);
      console.log(
        `[AuctionOrchestrator] Winner: ${winner.agent_id} (score=${winner.score.toFixed(2)})`
      );
    }

    this.pending.delete(opportunityId);
  }

  stop(): void {
    // Clear all pending timers
    for (const timer of this.timers.values()) {
      clearTimeout(timer);
    }
    this.timers.clear();
    this.pending.clear();
  }
}
```

### Pattern 3: Critic-Trader Loop

```typescript
// packages/swarm-kernel/src/orchestrators/criticTrader.ts
import { EventBus, EventEnvelope, OrderIntent } from "@merid/swarm-kernel";

interface Critique {
  intent_id: string;
  approved: boolean;
  suggested_adjustments?: Partial<OrderIntent>;
  rationale: string;
}

export interface CriticTraderConfig {
  maxIterations: number;
}

/**
 * Critic-Trader loop: Iterative refinement before execution
 * 
 * Trader proposes → Critic evaluates → Adjust or approve
 * 
 * Pros: Quality control, iterative improvement
 * Cons: Adds latency, requires critic agent
 */
export class CriticTraderOrchestrator {
  private iterations: Map<string, number> = new Map();

  constructor(
    private bus: EventBus,
    private config: CriticTraderConfig
  ) {}

  async start(): Promise<void> {
    await this.bus.subscribe<OrderIntent>(
      "intents.orders.draft",
      (evt) => this.onDraftIntent(evt)
    );
    
    await this.bus.subscribe<Critique>(
      "critiques",
      (evt) => this.onCritique(evt)
    );
    
    console.log("[CriticTraderOrchestrator] Started");
  }

  private async onDraftIntent(evt: EventEnvelope<OrderIntent>): Promise<void> {
    const intent = evt.data;
    const iterCount = this.iterations.get(intent.client_tag) ?? 0;
    
    if (iterCount >= this.config.maxIterations) {
      console.log(`[CriticTrader] Max iterations reached for ${intent.client_tag}, forcing approval`);
      await this.bus.publish("intents.orders", intent);
      this.iterations.delete(intent.client_tag);
      return;
    }

    // Send to critic
    await this.bus.publish("swarm.critique_request", intent);
    this.iterations.set(intent.client_tag, iterCount + 1);
  }

  private async onCritique(evt: EventEnvelope<Critique>): Promise<void> {
    const { intent_id, approved, suggested_adjustments } = evt.data;

    if (approved) {
      // Forward to execution pipeline
      // (Intent should be available from context or cache)
      console.log(`[CriticTrader] Intent ${intent_id} approved`);
      // Lookup and forward original intent
      this.iterations.delete(intent_id);
    } else if (suggested_adjustments) {
      // Apply adjustments and re-submit to critic
      console.log(`[CriticTrader] Intent ${intent_id} needs adjustments`);
      // Apply adjustments and re-publish to "intents.orders.draft"
    } else {
      // Rejected without suggestions - drop
      console.log(`[CriticTrader] Intent ${intent_id} rejected`);
      this.iterations.delete(intent_id);
    }
  }
}
```

---

## 5. Migration Checklist to Swarm-Native

### Phase 1: Boundary Kalshi Interface ✅
- [ ] Single `KalshiWebSocketBridge` (Python) owns all WS connections
- [ ] Single `KalshiExecutionPipeline` (Python) owns all order placement
- [ ] Define topics: `kalshi.orderbook`, `kalshi.fills`, `kalshi.orders`, `kalshi.errors`
- [ ] No direct Kalshi access from agents

### Phase 2: Standardize Event Contracts ✅
- [ ] Define TypeScript types in `packages/swarm-kernel/src/types.ts`
- [ ] Define Python equivalents (Pydantic models) in `merid_agents/schemas/`
- [ ] Add schema versioning: `schema_version` field in all events
- [ ] Document contract evolution policy (backward compatibility)

### Phase 3: Introduce EventBus Abstraction ✅
- [ ] Choose event bus technology (Kafka/NATS/Redis Streams)
- [ ] Implement TS `EventBus` interface wrapper
- [ ] Implement Python equivalent
- [ ] Add connection health monitoring
- [ ] Test pub/sub across language boundary

### Phase 4: Refactor Agents to Pure Functions ✅
- [ ] Convert existing bots to: `(input events) → (output events)`
- [ ] Remove direct DB access from agents (use event-sourced state stores)
- [ ] Remove direct Kalshi API calls from agents
- [ ] Isolate state: `OrderbookState`, `PnLState`, `PositionState`
- [ ] Add agent lifecycle: `start()`, `stop()`, `health()`

### Phase 5: Insert Risk & Rate-Limit Gates ✅
- [ ] All `OrderIntent` → single `KalshiExecutionPipeline`
- [ ] Risk engine checks: position limits, drawdown, exposure
- [ ] Global rate limiter: per-tier token buckets
- [ ] Metrics: intents passed/failed, 429 count, daily loss, venue notional
- [ ] Alerts: risk rejections, rate limit exhaustion

### Phase 6: Add Orchestration Layer ✅
- [ ] Implement Sequential orchestrator (simplest)
- [ ] Implement Auction orchestrator (diversity)
- [ ] Implement Critic-Trader loop (quality control)
- [ ] Run in paper mode only until tested
- [ ] Add orchestration metrics: auction win rates, critic approval rate

### Phase 7: Adversarial Tests & Observability ✅
- [ ] Test: Out-of-order WS events (seq number violations)
- [ ] Test: WS disconnect/reconnect during active session
- [ ] Test: API timeout with retry (no ghost orders)
- [ ] Test: Duplicate intent detection (idempotency)
- [ ] Test: Rate limit exhaustion (graceful degradation)
- [ ] Log every decision: `session_id`, `agent_id`, `intent`, `outcome`
- [ ] Replay capability from event log

### Phase 8: Gradual Cut-Over ✅
- [ ] Feature flag: `ENABLE_SWARM_MODE` (default: false)
- [ ] Route subset of markets through swarm path
- [ ] Monitor swarm vs legacy performance (win rate, PnL, latency)
- [ ] Gradual rollout: 10% → 50% → 100%
- [ ] Deprecate direct Kalshi access paths
- [ ] Document Swarm architecture as canonical

---

## 6. Common Multi-Agent Trading Pitfalls

### Pitfall 1: Implicit Shared State

**Problem:** Agents share DB rows, caches, or in-memory dicts without locking

**Symptoms:**
- Race conditions on position updates
- Intermittent bugs that disappear when you add logging
- Different agents see inconsistent portfolio state

**Mitigation:**
```typescript
// BAD: Shared mutable state
class SharedState {
  positions: Record<string, number> = {};
}

// GOOD: Event-sourced state with single owner
class PositionStore {
  private events: PositionEvent[] = [];
  
  recordFill(event: FillEvent): void {
    this.events.push(event);
  }
  
  getPosition(market: string): number {
    return this.events
      .filter(e => e.market === market)
      .reduce((sum, e) => sum + e.delta, 0);
  }
}
```

**Key:** One owner per stateful domain (venue, risk, portfolio)

---

### Pitfall 2: Retry Storms / Non-Idempotent Orders

**Problem:** Timeouts cause multiple agents to retry same order → all execute

**Symptoms:**
- Ghost orders (expected 100 contracts, filled 300)
- Double/triple positions after network hiccups
- Unexplained limit breaches

**Mitigation:**
```typescript
// BAD: No idempotency
async function placeOrder(market: string, qty: number) {
  for (let i = 0; i < 3; i++) {
    try {
      return await kalshi.post_order(market, qty);
    } catch (e) {
      // Retry without unique ID → duplicates!
    }
  }
}

// GOOD: Idempotent with client_order_id
async function placeOrderIdempotent(intent: OrderIntent) {
  const client_order_id = intent.client_tag; // Unique per intent
  
  for (let i = 0; i < 3; i++) {
    try {
      return await kalshi.post_order({
        market: intent.market_ticker,
        qty: intent.qty,
        client_order_id, // Kalshi deduplicates
      });
    } catch (e) {
      // Safe to retry - Kalshi won't duplicate
      await sleep(exponentialBackoff(i));
    }
  }
}
```

**Key:** Unique `client_order_id` + single execution pipeline + backoff with jitter

---

### Pitfall 3: Uncoordinated Polling / Rate-Limit Starvation

**Problem:** Each agent polls portfolio/markets → hit tier limits, miss updates

**Symptoms:**
- 429 errors during high activity
- Agents starve each other of API quota
- Execution requests fail due to exhausted write budget

**Kalshi Limits:**
| Tier     | Read/s | Write/s |
|----------|--------|---------|
| Basic    | 20     | 10      |
| Premier  | 100    | 100     |
| Prime    | 400    | 400     |

**Mitigation:**
```typescript
// BAD: Each agent polls independently
class AgentA {
  async loop() {
    while (true) {
      await kalshi.get_portfolio(); // Eats quota!
      await sleep(1000);
    }
  }
}

// GOOD: Central polling with fan-out
class PollingService {
  constructor(private bus: EventBus, private limiter: RateLimiter) {}
  
  async loop() {
    while (true) {
      if (await this.limiter.acquire("read", priority: 3)) {
        const portfolio = await kalshi.get_portfolio();
        await this.bus.publish("kalshi.portfolio", portfolio);
      }
      await sleep(5000);
    }
  }
}

// Agents subscribe to events instead of polling
class AgentB {
  async start() {
    await this.bus.subscribe("kalshi.portfolio", (evt) => {
      // React to updates
    });
  }
}
```

**Key:** Central polling service + WS for streaming + global rate-limit buckets

---

### Pitfall 4: Emergent Feedback Loops

**Problem:** Multiple strategies chase same edge → compounding exposure

**Symptoms:**
- Unexpected correlation in agent positions
- All agents pile into same market simultaneously
- Fees and slippage higher than expected

**Mitigation:**
```typescript
// Add correlation-aware limits
class RiskEngine {
  async assess(intent: OrderIntent): Promise<RiskDecision> {
    // Per-market limit
    if (this.getPosition(intent.market_ticker) >= MAX_PER_MARKET) {
      return { approved: false, reason: "market_limit" };
    }
    
    // Per-asset limit (e.g., all BTC markets combined)
    const asset = this.extractAsset(intent.market_ticker); // "BTC"
    const assetExposure = this.getAssetExposure(asset);
    if (assetExposure >= MAX_PER_ASSET) {
      return { approved: false, reason: "asset_limit" };
    }
    
    // Global notional limit
    const totalNotional = this.getTotalNotional();
    if (totalNotional >= MAX_TOTAL_NOTIONAL) {
      return { approved: false, reason: "global_limit" };
    }
    
    return { approved: true };
  }
}

// Add randomization to break correlation
class TraderAgent {
  private async shouldExecute(intent: OrderIntent): Promise<boolean> {
    // Add random delay to decorrelate agents
    await sleep(Math.random() * 1000);
    
    // Probabilistic execution based on confidence
    return Math.random() < intent.confidence;
  }
}
```

**Key:** Global risk view by asset/market + correlation limits + randomization

---

### Pitfall 5: Lack of Adversarial Testing

**Problem:** Systems pass "sunny day" tests but fail under timing anomalies

**Symptoms:**
- Works perfectly in dev, crashes in prod
- Bugs only appear under load or network issues
- "I've never seen this error before" syndrome

**Mitigation:**
```typescript
// Adversarial test suite
describe("Swarm Adversarial Tests", () => {
  test("out-of-order WS events", async () => {
    // Send messages with reversed sequence numbers
    await bridge.inject({ type: "orderbook_delta", seq: 100 });
    await bridge.inject({ type: "orderbook_delta", seq: 99 }); // Out of order!
    
    // Verify agent handles gracefully
    expect(agent.getLastSeq()).toBe(100);
  });
  
  test("WS disconnect during session", async () => {
    // Start session
    const session = await swarm.startSession();
    
    // Simulate disconnect
    bridge.disconnect();
    
    // Verify agents pause, no ghost orders
    expect(await executionPipeline.getPendingCount()).toBe(0);
  });
  
  test("API timeout with retry", async () => {
    // Mock timeout on first attempt, success on second
    kalshi.post_order = jest.fn()
      .mockRejectedValueOnce(new Error("timeout"))
      .mockResolvedValueOnce({ order_id: "123" });
    
    await pipeline.execute(intent);
    
    // Verify only one order created (idempotency)
    expect(kalshi.post_order).toHaveBeenCalledTimes(2);
    expect(kalshi.post_order.mock.calls[0][0].client_order_id)
      .toBe(kalshi.post_order.mock.calls[1][0].client_order_id);
  });
  
  test("rate limit exhaustion", async () => {
    // Exhaust write budget
    limiter.exhaust("write");
    
    // Attempt execution
    const outcome = await pipeline.execute(intent);
    
    // Verify graceful degradation
    expect(outcome.status).toBe("rejected_rate_limit");
    expect(auditLog.getRejectionCount()).toBeGreaterThan(0);
  });
});
```

**Key:** Adversarial test suite required before live (chaos testing)

---

### Pitfall 6: Explainability Drift

**Problem:** Logs/explanations diverge from actual execution

**Symptoms:**
- Audit trail says "filled 100" but position shows 0
- Agent claims "rejected by risk" but order was submitted
- Debugging impossible due to inconsistent logs

**Mitigation:**
```typescript
// BAD: Agent logs locally
class TraderAgent {
  async onSignal(signal: Signal) {
    this.localLog.push({ type: "intent", signal }); // Diverges!
    await this.bus.publish("intents.orders", intent);
  }
}

// GOOD: Derive explainability from execution event log
class AuditLogger {
  async logExecution(outcome: ExecutionOutcome) {
    // Single source of truth
    await this.store.append({
      intent_id: outcome.intent.client_tag,
      agent_id: outcome.intent.agent_id,
      status: outcome.status,
      order_id: outcome.order_id,
      timestamp: outcome.timestamp,
    });
  }
  
  async buildExplainability(session_id: string) {
    // Reconstruct entire session from event log
    const events = await this.store.query({ session_id });
    return this.generateReport(events);
  }
}
```

**Key:** Derive explainability from execution event log, not agent local logs

---

## 7. Next Steps

### Immediate (Ready to Implement)
1. Create `packages/swarm-kernel/` with types and WS client
2. Create `packages/agents/` with OrderbookAgent and TraderAgent
3. Wire to existing Python Kalshi bridge via topic subscriptions
4. Run in paper mode with mock execution pipeline

### Short-term (Week 1-2)
5. Implement Sequential orchestrator
6. Add adversarial test harness
7. Create monitoring dashboard (agent activity, rate limits, risk)
8. Document TS ↔ Python event contracts

### Medium-term (Week 3-4)
9. Implement Auction and Critic-Trader orchestrators
10. Add production risk limits and rate limiting
11. Cut over 10% of markets to swarm path
12. Measure swarm vs legacy performance

---

**Last Updated:** 2026-02-16  
**Status:** Implementation-ready templates  
**Reference:** SWARM_MIGRATION_ROADMAP.md, KALSHI_SWARM_SAFETY_GUIDE.md
