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
  daily_pnl: number;
  daily_pnl_pct: number;
  total_equity: number;
  available_margin: number;
  positions_count: number;
}

export interface TradingSummary {
  active_orders: number;
  filled_today: number;
  cancelled_today: number;
  total_volume_24h: number;
  avg_fill_time_ms: number;
}

export interface AgentSummary {
  total_agents: number;
  active_agents: number;
  idle_agents: number;
  total_tasks_completed: number;
  agents: Array<{
    agent_id: string;
    name: string;
    status: 'active' | 'idle' | 'error';
    tasks_completed: number;
  }>;
}

export interface RiskProtections {
  circuit_breaker: {
    state: 'CLOSED' | 'OPEN' | 'HALF_OPEN';
    error_count: number;
    threshold: number;
    last_failure?: number;
  };
  lockdown: {
    trading_suite_enabled: boolean;
    reason?: string;
  };
  exposure: {
    total_exposure: number;
    max_exposure: number;
    utilization_pct: number;
  };
}

export interface PrimeStatus {
  connected: boolean;
  last_heartbeat?: number;
  active_connections: number;
  message_queue_size: number;
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
