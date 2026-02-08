// Centralized API service for all backend calls
// Use relative path to leverage Vite proxy
const API_BASE = '/api';

export interface SystemHealth {
  status: 'healthy' | 'degraded' | 'unhealthy';
  timestamp: number;
  environment: string;
  incident_flag: boolean;
  services: Record<string, { status: string; last_check: number }>;
}

export interface PnLSummary {
  today_pnl: number;
  today_pnl_pct: number;
  mtm_pnl: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  limit_daily_loss: number;
  limit_utilization_pct: number;
}

export interface TradingSummary {
  active_strategies: number;
  paused_strategies: number;
  venues_connected: number;
  venues: string[];
  notional_deployed: number;
  notional_capacity: number;
  utilization_pct: number;
}

export interface AgentSummary {
  total_agents: number;
  active_agents: number;
  idle_agents: number;
  tasks_completed: number;
  tasks_pending: number;
  average_response_time: number;
  success_rate: number;
  agents: Array<{
    id: string;
    name: string;
    status: string;
    heartbeat_age_ms: number;
    strategy: string;
    state: string;
    positions_count: number;
    today_pnl: number;
    tasks_completed: number;
    uptime: number;
  }>;
  summary: {
    total: number;
    healthy: number;
    paused: number;
    unhealthy: number;
  };
}

export interface RiskProtections {
  timestamp: string;
  circuit_breaker: {
    state: 'CLOSED' | 'OPEN' | 'HALF_OPEN';
    state_color: string;
    error_count: number;
    window_seconds: number;
    threshold: number;
    last_error_at: string | null;
    opened_at: string | null;
    cooldown_seconds: number;
    half_open_successes: number;
  };
  lockdown: {
    trading_suite_enabled: boolean;
    global_mode: string;
    spectator_mode: boolean;
    lockdown_reason: string | null;
  };
  risk_limits: {
    max_daily_loss_usd: number;
    current_daily_pnl: number;
    daily_loss_utilization_pct: number;
    max_per_symbol_exposure_usd: number;
    max_open_orders: number;
    current_open_orders: number;
  };
  recent_events: Array<{ timestamp: string; type: string; details: any }>;
}

export interface PrimeStatus {
  status: string;
  mode: string;
  market_data_connected: boolean;
  narrative_available: boolean;
  last_narrative_timestamp: number;
  data_feeds: Record<string, { connected: boolean; latency_ms: number }>;
}

export interface PredictionMarket {
  market_id: string;
  question: string;
  category: string;
  yes_price: number;
  no_price: number;
  volume_24h: number;
  platform: string;
  close_date?: string;
}

class APIService {
  private async fetchJSON<T>(endpoint: string): Promise<T> {
    const response = await fetch(`${API_BASE}${endpoint}`);
    if (!response.ok) {
      throw new Error(`API Error: ${response.status} ${response.statusText}`);
    }
    return response.json();
  }

  // System Health
  async getSystemHealth(): Promise<SystemHealth> {
    return this.fetchJSON<SystemHealth>('/system/health');
  }

  // PnL & Portfolio
  async getPnLSummary(): Promise<PnLSummary> {
    return this.fetchJSON<PnLSummary>('/risk/pnl-summary');
  }

  async getPortfolioSummary() {
    return this.fetchJSON('/portfolio/summary');
  }

  // Trading Operations
  async getTradingSummary(): Promise<TradingSummary> {
    return this.fetchJSON<TradingSummary>('/trading/summary');
  }

  // Agents
  async getAgentSummary(): Promise<AgentSummary> {
    return this.fetchJSON<AgentSummary>('/agents/summary');
  }

  async getAgentActivity() {
    return this.fetchJSON('/agents/activity');
  }

  // Risk & Protections
  async getRiskProtections(): Promise<RiskProtections> {
    return this.fetchJSON<RiskProtections>('/risk/protections');
  }

  async getRiskExposure() {
    return this.fetchJSON('/risk/exposure');
  }

  // Prime Status
  async getPrimeStatus(): Promise<PrimeStatus> {
    return this.fetchJSON<PrimeStatus>('/prime/status');
  }

  // Prediction Markets
  async getPredictionMarkets(): Promise<{ markets: PredictionMarket[] }> {
    return this.fetchJSON<{ markets: PredictionMarket[] }>('/v1/us-compliant/prediction-markets');
  }

  // Live Prices
  async getLivePrices(symbols: string[]) {
    const symbolsParam = symbols.join(',');
    return this.fetchJSON(`/prices/live?symbols=${symbolsParam}`);
  }

  // Recent Orders
  async getRecentOrders() {
    return this.fetchJSON('/orders/recent');
  }
}

export const api = new APIService();
