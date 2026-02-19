/**
 * Resilient WebSocket Client with Auto-Resubscription
 * 
 * Features:
 * - Exponential backoff reconnection
 * - Automatic re-subscription on reconnect
 * - Message handler registration
 * - Graceful shutdown
 * 
 * Use this for TS agents connecting to Python bridge (internal WS)
 * Python bridge handles Kalshi auth; this handles bridge reconnection
 */

import WebSocket from "ws";

type Handler = (msg: any) => void;

export interface ResilientWsConfig {
  url: string;
  baseBackoffMs?: number;
  maxBackoffMs?: number;
  heartbeatIntervalMs?: number;
}

export class ResilientWsClient {
  private ws?: WebSocket;
  private handlers: Handler[] = [];
  private subscriptions: any[] = [];
  private reconnectAttempts = 0;
  private closedByClient = false;
  private heartbeatInterval?: NodeJS.Timeout;
  private config: Required<ResilientWsConfig>;

  constructor(config: ResilientWsConfig) {
    this.config = {
      url: config.url,
      baseBackoffMs: config.baseBackoffMs ?? 1000,
      maxBackoffMs: config.maxBackoffMs ?? 30000,
      heartbeatIntervalMs: config.heartbeatIntervalMs ?? 15000,
    };
  }

  /**
   * Start connection
   */
  connect(): void {
    this.closedByClient = false;
    this.open();
  }

  /**
   * Register message handler
   */
  onMessage(handler: Handler): void {
    this.handlers.push(handler);
  }

  /**
   * Add subscription that will be automatically re-sent on reconnect
   */
  addSubscription(msg: any): void {
    this.subscriptions.push(msg);
    this.send(msg);
  }

  /**
   * Remove subscription
   */
  removeSubscription(msg: any): void {
    const index = this.subscriptions.indexOf(msg);
    if (index > -1) {
      this.subscriptions.splice(index, 1);
    }
  }

  /**
   * Send message (only if connected)
   */
  send(msg: any): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    } else {
      console.warn("[ResilientWS] Cannot send - not connected");
    }
  }

  /**
   * Close connection gracefully
   */
  close(): void {
    this.closedByClient = true;
    this.stopHeartbeat();
    this.ws?.close();
  }

  /**
   * Check if currently connected
   */
  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  private open(): void {
    console.log(`[ResilientWS] Connecting to ${this.config.url}`);
    this.ws = new WebSocket(this.config.url);

    this.ws.on("open", () => {
      console.log("[ResilientWS] Connected");
      this.reconnectAttempts = 0;
      this.startHeartbeat();
      this.resubscribeAll();
    });

    this.ws.on("message", (raw) => {
      try {
        const msg = JSON.parse(raw.toString());
        this.handlers.forEach((h) => h(msg));
      } catch (e) {
        console.error("[ResilientWS] Parse error:", e);
      }
    });

    this.ws.on("pong", () => {
      // Connection alive
    });

    this.ws.on("close", (code, reason) => {
      console.warn(`[ResilientWS] Closed: code=${code} reason=${reason.toString()}`);
      this.stopHeartbeat();
      
      if (!this.closedByClient) {
        this.scheduleReconnect();
      }
    });

    this.ws.on("error", (err) => {
      console.error("[ResilientWS] Error:", err);
    });
  }

  private resubscribeAll(): void {
    if (this.subscriptions.length === 0) {
      return;
    }

    console.log(`[ResilientWS] Re-subscribing to ${this.subscriptions.length} channels`);
    
    for (const sub of this.subscriptions) {
      this.send(sub);
    }
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    
    this.heartbeatInterval = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.ping("heartbeat");
      }
    }, this.config.heartbeatIntervalMs);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = undefined;
    }
  }

  private scheduleReconnect(): void {
    this.reconnectAttempts++;
    
    // Exponential backoff: 1s, 2s, 4s, 8s, 16s, 30s (capped)
    const delay = Math.min(
      this.config.maxBackoffMs,
      this.config.baseBackoffMs * Math.pow(2, Math.min(this.reconnectAttempts - 1, 5))
    );

    console.log(
      `[ResilientWS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`
    );

    setTimeout(() => {
      this.open();
    }, delay);
  }

  // Monitoring
  getStats() {
    return {
      connected: this.isConnected(),
      reconnectAttempts: this.reconnectAttempts,
      subscriptionCount: this.subscriptions.length,
      handlerCount: this.handlers.length,
    };
  }
}
