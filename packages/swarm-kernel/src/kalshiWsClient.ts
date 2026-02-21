/**
 * Kalshi WebSocket Client with Auth Error Handling
 * 
 * Handles WS connection lifecycle and classifies close reasons
 * Should primarily be used by Python bridge; TS agents connect to internal bridge
 */

import WebSocket from "ws";

export type CloseKind = "auth" | "network" | "rate_limit" | "other";

export interface WSClientConfig {
  url: string;
  headers?: Record<string, string>;
  reconnectDelayMs?: number;
  maxReconnectAttempts?: number;
  onMessage?: (msg: any) => void;
  onAuthFailure?: () => void;
  onReconnect?: () => void;
}

export class KalshiWsClient {
  private ws?: WebSocket;
  private reconnectAttempts: number = 0;
  private shouldReconnect: boolean = true;
  private config: Required<WSClientConfig>;

  constructor(config: WSClientConfig) {
    this.config = {
      url: config.url,
      headers: config.headers ?? {},
      reconnectDelayMs: config.reconnectDelayMs ?? 1000,
      maxReconnectAttempts: config.maxReconnectAttempts ?? 10,
      onMessage: config.onMessage ?? (() => {}),
      onAuthFailure: config.onAuthFailure ?? (() => {}),
      onReconnect: config.onReconnect ?? (() => {}),
    };
  }

  connect(): void {
    console.log(`[KalshiWS] Connecting to ${this.config.url}`);

    this.ws = new WebSocket(this.config.url, {
      headers: this.config.headers,
    });

    this.ws.on("open", () => {
      console.log("[KalshiWS] Connected");
      this.reconnectAttempts = 0;
      if (this.reconnectAttempts > 0) {
        this.config.onReconnect();
      }
    });

    this.ws.on("message", (raw) => {
      try {
        const msg = JSON.parse(raw.toString());

        // Check for error messages from server
        if (msg.type === "error") {
          this.handleServerError(msg);
          return;
        }

        this.config.onMessage(msg);
      } catch (e) {
        console.error("[KalshiWS] Failed to parse message:", e);
      }
    });

    this.ws.on("close", (code, reason) => {
      const kind = this.classifyClose(code, reason);
      console.warn(`[KalshiWS] Closed: code=${code} kind=${kind} reason=${reason.toString()}`);

      this.handleClose(kind);
    });

    this.ws.on("error", (err) => {
      console.error("[KalshiWS] Error:", err);
    });

    this.ws.on("ping", () => {
      // ws library auto-responds with pong
    });
  }

  private handleServerError(msg: any): void {
    const { code, message } = msg.msg || msg;
    console.error(`[KalshiWS] Server error: code=${code} message=${message}`);

    // Check for auth-related errors
    if (this.isAuthError(code, message)) {
      console.error("[KalshiWS] Authentication error detected, disabling auto-reconnect");
      this.shouldReconnect = false;
      this.config.onAuthFailure();
      this.disconnect();
    }
  }

  private isAuthError(code: string, message: string): boolean {
    const authKeywords = [
      "unauthorized",
      "invalid signature",
      "invalid key",
      "authentication failed",
      "auth failed",
      "forbidden",
    ];

    const lowerMessage = (message || "").toLowerCase();
    const lowerCode = (code || "").toLowerCase();

    return authKeywords.some(keyword => 
      lowerMessage.includes(keyword) || lowerCode.includes(keyword)
    );
  }

  private classifyClose(code: number, reason: Buffer | string): CloseKind {
    const reasonStr = reason.toString().toLowerCase();

    // Auth failures
    if (code === 1008 || reasonStr.includes("unauthorized") || reasonStr.includes("auth")) {
      return "auth";
    }

    // Rate limiting
    if (code === 1013 || reasonStr.includes("rate limit") || reasonStr.includes("throttle")) {
      return "rate_limit";
    }

    // Network issues
    if (code === 1006 || code === 1001) {
      return "network";
    }

    return "other";
  }

  private handleClose(kind: CloseKind): void {
    if (kind === "auth") {
      console.error("[KalshiWS] Auth failure - NOT reconnecting");
      this.shouldReconnect = false;
      this.config.onAuthFailure();
      return;
    }

    if (kind === "rate_limit") {
      console.warn("[KalshiWS] Rate limited - backoff before reconnect");
      const backoffMs = this.config.reconnectDelayMs * Math.pow(2, this.reconnectAttempts);
      setTimeout(() => this.reconnect(), Math.min(backoffMs, 60000));
      return;
    }

    // Network or other issues - safe to retry
    this.reconnect();
  }

  private reconnect(): void {
    if (!this.shouldReconnect) {
      return;
    }

    this.reconnectAttempts++;

    if (this.reconnectAttempts > this.config.maxReconnectAttempts) {
      console.error(`[KalshiWS] Max reconnect attempts (${this.config.maxReconnectAttempts}) reached`);
      return;
    }

    const delayMs = this.config.reconnectDelayMs * this.reconnectAttempts;
    console.log(`[KalshiWS] Reconnecting in ${delayMs}ms (attempt ${this.reconnectAttempts})`);

    setTimeout(() => {
      this.connect();
    }, delayMs);
  }

  send(msg: any): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    } else {
      console.warn("[KalshiWS] Cannot send - not connected");
    }
  }

  disconnect(): void {
    this.shouldReconnect = false;
    if (this.ws) {
      this.ws.close();
      this.ws = undefined;
    }
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}
