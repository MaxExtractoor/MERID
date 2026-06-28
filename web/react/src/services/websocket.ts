/**
 * Kalshi WebSocket Client — Single Connection for Real-Time Updates
 * 
 * Architecture:
 * - Single WebSocket connection for all real-time data
 * - Integrates with Zustand store for state updates
 * - Handles portfolio_update, risk_update, kill_switch events
 * - Automatic reconnection with exponential backoff
 * - No component-local WebSocket hacks
 */

import { useKalshiStore } from '../store';

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8011/ws';

class KalshiWebSocket {
  private ws: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private maxBackoffMs = 30000; // 30 seconds
  private mounted = true;

  constructor() {
    // Don't auto-connect - use polling via refreshAll() instead
    // WebSocket requires auth which isn't implemented yet
    console.log('[KalshiWebSocket] WebSocket disabled - using API polling');
  }

  private connect() {
    if (!this.mounted) return;

    try {
      this.ws = new WebSocket(WS_URL);
      this.setupEventHandlers();
    } catch (error) {
      console.error('[KalshiWebSocket] Connection failed:', error);
      this.scheduleReconnect();
    }
  }

  private setupEventHandlers() {
    if (!this.ws) return;

    this.ws.onopen = () => {
      console.log('[KalshiWebSocket] Connected');
      this.reconnectAttempts = 0;
      useKalshiStore.getState().setConnected(true);
    };

    this.ws.onclose = (event) => {
      console.log('[KalshiWebSocket] Disconnected:', event.code, event.reason);
      useKalshiStore.getState().setConnected(false);
      this.scheduleReconnect();
    };

    this.ws.onerror = (error) => {
      console.error('[KalshiWebSocket] Error:', error);
    };

    this.ws.onmessage = (event) => {
      this.handleMessage(event.data);
    };
  }

  private handleMessage(data: string) {
    try {
      const message = JSON.parse(data);
      const eventType = message.type || message.event || message.event_type;

      if (!eventType) {
        console.warn('[KalshiWebSocket] Unknown message format:', message);
        return;
      }

      // Route to appropriate store slice based on event type
      switch (eventType) {
        case 'portfolio_update':
          this.handlePortfolioUpdate(message.data);
          break;
        case 'risk_update':
        case 'risk_summary':
        case 'risk_alert':
          this.handleRiskUpdate(message.data);
          break;
        case 'kill_switch':
          this.handleKillSwitch(message.data);
          break;
        case 'agent_updated':
        case 'agent_update':
          this.handleAgentUpdate(message.data);
          break;
        default:
          console.debug('[KalshiWebSocket] Unhandled event type:', eventType);
      }
    } catch (error) {
      console.error('[KalshiWebSocket] Failed to parse message:', error);
    }
  }

  private handlePortfolioUpdate(data: any) {
    // Backend payload structure from portfolio_publisher.py:
    // {
    //   total_value: number,
    //   change_24h: number,
    //   change_24h_percent: number,
    //   pnl_today: number,
    //   positions_count: number,
    //   total_trades: number,
    //   winning_trades: number,
    //   losing_trades: number,
    //   timestamp: number,
    //   source: string
    // }
    
    useKalshiStore.getState().updatePortfolio({
      balance: data.total_value || 0,
      cash: data.total_value || 0, // TODO: Separate cash from total when available
      portfolio_value: data.total_value || 0,
      daily_pnl: data.pnl_today || 0,
      timestamp: new Date(data.timestamp || Date.now()).toISOString(),
    });
  }

  private handleRiskUpdate(data: any) {
    // Backend payload structure for risk_update:
    // {
    //   daily_pnl: number,
    //   drawdown_pct: number,
    //   total_notional: number,
    //   kill_switch_active: boolean,
    //   kill_switch_reason: string,
    //   sizing_metrics: { kelly_fraction, vol_scale, effective_fraction, edge_pct },
    //   alerts: array,
    //   timestamp: string
    // }
    
    useKalshiStore.getState().updateRisk({
      daily_pnl: data.daily_pnl || 0,
      drawdown_pct: data.drawdown_pct || 0,
      total_notional: data.total_notional || 0,
      kill_switch_active: data.kill_switch_active || false,
      kill_switch_reason: data.kill_switch_reason || '',
      sizing_metrics: data.sizing_metrics || {
        kelly_fraction: 0,
        vol_scale: 0,
        effective_fraction: 0,
        edge_pct: 0,
      },
      alerts: data.alerts || [],
      timestamp: data.timestamp || new Date().toISOString(),
    });
  }

  private handleKillSwitch(data: any) {
    // Backend payload for kill_switch:
    // {
    //   active: boolean,
    //   reason: string,
    //   timestamp: string
    // }
    
    useKalshiStore.getState().updateRisk({
      kill_switch_active: data.active || false,
      kill_switch_reason: data.reason || '',
      timestamp: data.timestamp || new Date().toISOString(),
    });
  }

  private handleAgentUpdate(data: any) {
    // Backend payload for agent_updated:
    // {
    //   agents: array,
    //   running: boolean,
    //   timestamp: string
    // }
    
    useKalshiStore.getState().updateGrid({
      running: data.running || false,
      agents: data.agents || [],
      timestamp: data.timestamp || new Date().toISOString(),
    });
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }

    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('[KalshiWebSocket] Max reconnection attempts reached');
      return;
    }

    const backoffMs = Math.min(
      1000 * Math.pow(2, this.reconnectAttempts),
      this.maxBackoffMs
    );

    const jitter = Math.random() * 1000;
    const delay = backoffMs + jitter;

    console.log(`[KalshiWebSocket] Reconnecting in ${Math.round(delay)}ms (attempt ${this.reconnectAttempts + 1})`);

    this.reconnectTimer = setTimeout(() => {
      this.reconnectAttempts++;
      this.connect();
    }, delay);
  }

  disconnect() {
    this.mounted = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    if (this.ws) {
      this.ws.close();
    }
  }
}

// Singleton instance
let wsInstance: KalshiWebSocket | null = null;

export function getWebSocketClient(): KalshiWebSocket {
  if (!wsInstance) {
    wsInstance = new KalshiWebSocket();
  }
  return wsInstance;
}

export function disconnectWebSocket() {
  if (wsInstance) {
    wsInstance.disconnect();
    wsInstance = null;
  }
}
