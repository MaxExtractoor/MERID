/**
 * WebSocket Message Dispatcher
 * Routes raw Kalshi WS messages to appropriate event bus topics
 * 
 * Cleanly separates WS transport from swarm logic
 */

import { EventBus } from "./types";

export class WsDispatcher {
  private messageCount = 0;
  private errorCount = 0;

  constructor(private bus: EventBus) {}

  /**
   * Handle raw WebSocket message and route to appropriate topic
   */
  async handle(raw: any): Promise<void> {
    this.messageCount++;

    try {
      // Route by message type
      switch (raw.type) {
        case "orderbook_snapshot":
          await this.bus.publish("kalshi.orderbook_snapshot", raw);
          break;

        case "orderbook_delta":
          await this.bus.publish("kalshi.orderbook_delta", raw);
          break;

        case "trade":
          await this.bus.publish("kalshi.trade", raw);
          break;

        case "ticker":
          await this.bus.publish("kalshi.ticker", raw);
          break;

        case "fill":
          await this.bus.publish("kalshi.fill", raw);
          break;

        case "error":
          await this.bus.publish("kalshi.error", raw);
          this.errorCount++;
          console.error("[WsDispatcher] Server error:", raw.msg);
          break;

        default:
          console.warn(`[WsDispatcher] Unknown message type: ${raw.type}`);
      }
    } catch (e) {
      this.errorCount++;
      console.error("[WsDispatcher] Failed to dispatch message:", e);
    }
  }

  getStats() {
    return {
      messagesProcessed: this.messageCount,
      errors: this.errorCount,
    };
  }
}
