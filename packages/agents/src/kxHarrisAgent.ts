/**
 * KX Harris Orderbook Agent
 * Monitors KXHARRIS24-LSV market (example from Kalshi docs)
 * Consumes orderbook deltas from Python bridge, publishes signals
 */

import { EventBus, EventEnvelope } from "@merid/swarm-kernel";

interface OrderbookMsg {
  type: "orderbook_snapshot" | "orderbook_delta";
  msg: {
    market_ticker: string;
    bids: [number, number][];
    asks: [number, number][];
    seq?: number;
    timestamp?: number;
  };
}

interface KXHarrisSignal {
  market_ticker: string;
  mid: number;
  spread: number;
  impliedProbYes: number;
  topDepthBid: number;
  topDepthAsk: number;
  imbalance: number;
  ts: number;
}

export class KXHarrisOrderbookAgent {
  private lastSeq: number = 0;
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number = 10;

  constructor(private bus: EventBus) {}

  async start(): Promise<void> {
    // Subscribe to Kalshi orderbook events from Python bridge
    await this.bus.subscribe<OrderbookMsg>(
      "kalshi.orderbook",
      (evt) => this.handleOrderbook(evt)
    );

    // Subscribe to WS status events
    await this.bus.subscribe(
      "kalshi.ws.status",
      (evt) => this.handleWSStatus(evt)
    );

    console.log("[KXHarris] Agent started, subscribed to kalshi.orderbook");
  }

  private async handleOrderbook(evt: EventEnvelope<OrderbookMsg>): Promise<void> {
    const msg = evt.data;

    // Filter for KXHARRIS24-LSV market only
    if (!msg.msg || msg.msg.market_ticker !== "KXHARRIS24-LSV") {
      return;
    }

    // Sequence number validation (prevent out-of-order processing)
    if (msg.msg.seq && msg.msg.seq <= this.lastSeq) {
      console.warn(
        `[KXHarris] Out-of-order message: seq=${msg.msg.seq}, lastSeq=${this.lastSeq}`
      );
      return;
    }

    if (msg.msg.seq) {
      this.lastSeq = msg.msg.seq;
    }

    const { bids, asks } = msg.msg;

    if (!bids.length || !asks.length) {
      console.warn("[KXHarris] Empty orderbook, skipping");
      return;
    }

    // Compute signal
    const signal = this.computeSignal(bids, asks, evt.ts);
    
    // Publish to swarm
    await this.bus.publish("signals.kx_harris.orderbook", signal);

    console.log(
      `[KXHarris] Signal: mid=${signal.mid.toFixed(2)}, spread=${signal.spread.toFixed(2)}, ` +
      `imbalance=${signal.imbalance.toFixed(2)}`
    );
  }

  private computeSignal(
    bids: [number, number][],
    asks: [number, number][],
    ts: number
  ): KXHarrisSignal {
    const [bestBidPrice, bestBidSize] = bids[0];
    const [bestAskPrice, bestAskSize] = asks[0];

    const mid = (bestBidPrice + bestAskPrice) / 2;
    const spread = bestAskPrice - bestBidPrice;

    // Kalshi contracts trade in cents (1-99), where price = implied probability * 100
    const impliedProbYes = mid / 100;

    // Top-of-book depth
    const topDepthBid = bestBidSize;
    const topDepthAsk = bestAskSize;

    // Orderbook imbalance: positive = more bid depth, negative = more ask depth
    const totalDepth = topDepthBid + topDepthAsk;
    const imbalance = totalDepth > 0 ? (topDepthBid - topDepthAsk) / totalDepth : 0;

    return {
      market_ticker: "KXHARRIS24-LSV",
      mid,
      spread,
      impliedProbYes,
      topDepthBid,
      topDepthAsk,
      imbalance,
      ts,
    };
  }

  private async handleWSStatus(evt: EventEnvelope<any>): Promise<void> {
    const { connected, error } = evt.data;

    if (!connected) {
      console.warn(`[KXHarris] WS disconnected: ${error || "unknown reason"}`);
      this.reconnectAttempts++;

      if (this.reconnectAttempts > this.maxReconnectAttempts) {
        console.error("[KXHarris] Max reconnect attempts reached, alerting...");
        await this.bus.publish("alerts.critical", {
          agent: "KXHarris",
          message: "WS connection failed after max retries",
          timestamp: Date.now(),
        });
      }
    } else {
      console.log("[KXHarris] WS reconnected");
      this.reconnectAttempts = 0;
      this.lastSeq = 0; // Reset sequence on reconnect
    }
  }

  async stop(): Promise<void> {
    console.log("[KXHarris] Agent stopping");
  }
}
