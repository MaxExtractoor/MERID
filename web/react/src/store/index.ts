/**
 * Kalshi Store — Single Source of Truth for 15m Stack
 * 
 * Architecture:
 * - Single Zustand store with 4 slices: portfolio, risk, grid, system
 * - WebSocket for real-time updates (portfolio, risk, kill switch)
 * - Selective polling for slow-moving data (grid status, calibration, logs)
 * - All UI state derived from store, no local state duplication
 * 
 * Guardrails:
 * - UI never recomputes PnL, risk, or balances — only renders what backend provides
 * - Interface freeze: PortfolioData, RiskData, GridData, SystemData are contracts
 * - One connection per domain: Single WebSocket client, single polling layer
 */

import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';

// ── Types (contracts with backend) ─────────────────────────────────────────────

export interface Position {
  ticker: string;
  side: 'yes' | 'no';
  quantity: number;
  avg_entry_price_cents: number;
  unrealized_pnl_cents: number;
  outcome: string;
}

export interface Fill {
  fill_id: string;
  ticker: string;
  side: 'yes' | 'no';
  contracts: number;
  price_cents: number;
  fee_cents: number;
  pnl_cents: number;
  filled_at: string;
  market_question?: string;
}

export interface PortfolioData {
  balance: number;
  cash: number;
  portfolio_value: number;
  daily_pnl: number;
  positions: Position[];
  fills: Fill[];
  timestamp: string;
}

export interface SizingMetrics {
  kelly_fraction: number;
  vol_scale: number;
  effective_fraction: number;
  edge_pct: number;
}

export interface RiskAlert {
  id: string;
  type: 'drawdown' | 'notional' | 'daily_loss' | 'position';
  severity: 'warning' | 'critical';
  message: string;
  timestamp: string;
}

export interface RiskData {
  daily_pnl: number;
  drawdown_pct: number;
  total_notional: number;
  kill_switch_active: boolean;
  kill_switch_reason: string;
  sizing_metrics: SizingMetrics;
  alerts: RiskAlert[];
  timestamp: string;
}

export interface AgentSummary {
  name: string;
  asset: string;
  timeframe: string;
  running: boolean;
  cycles: number;
  orders: number;
  fills: number;
  series_tickers: string[];
}

export interface DeploymentStatus {
  mode: 'paper' | 'shadow' | 'live';
  auto_promoter_enabled: boolean;
  last_transition: string;
}

export interface PerformanceMetrics {
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  win_rate: number;
  profit_factor: number;
}

export interface GridData {
  running: boolean;
  agents: AgentSummary[];
  deployment: DeploymentStatus;
  performance: PerformanceMetrics;
  timestamp: string;
}

export interface ServiceHealth {
  name: string;
  ok: boolean;
  latency_ms: number;
  error?: string;
}

export interface SystemData {
  health: {
    ok: boolean;
    services: Record<string, ServiceHealth>;
    overall_latency_ms: number;
  };
  logs: LogEntry[];
  timestamp: string;
}

export interface LogEntry {
  id: string;
  level: 'info' | 'warning' | 'error';
  component: string;
  message: string;
  timestamp: string;
}

// ── Store Interface ───────────────────────────────────────────────────────────

interface KalshiStore {
  // Slices
  portfolio: PortfolioData;
  risk: RiskData;
  grid: GridData;
  system: SystemData;
  
  // Connection state
  connected: boolean;
  lastUpdate: number;
  
  // Actions
  updatePortfolio: (data: Partial<PortfolioData>) => void;
  updateRisk: (data: Partial<RiskData>) => void;
  updateGrid: (data: Partial<GridData>) => void;
  updateSystem: (data: Partial<SystemData>) => void;
  setConnected: (connected: boolean) => void;
  refreshAll: () => Promise<void>;
}

// ── Initial State ─────────────────────────────────────────────────────────────

const initialPortfolio: PortfolioData = {
  balance: 0,
  cash: 0,
  portfolio_value: 0,
  daily_pnl: 0,
  positions: [],
  fills: [],
  timestamp: new Date().toISOString(),
};

const initialRisk: RiskData = {
  daily_pnl: 0,
  drawdown_pct: 0,
  total_notional: 0,
  kill_switch_active: false,
  kill_switch_reason: '',
  sizing_metrics: {
    kelly_fraction: 0,
    vol_scale: 0,
    effective_fraction: 0,
    edge_pct: 0,
  },
  alerts: [],
  timestamp: new Date().toISOString(),
};

const initialGrid: GridData = {
  running: false,
  agents: [],
  deployment: {
    mode: 'paper',
    auto_promoter_enabled: false,
    last_transition: '',
  },
  performance: {
    sharpe_ratio: 0,
    sortino_ratio: 0,
    calmar_ratio: 0,
    win_rate: 0,
    profit_factor: 0,
  },
  timestamp: new Date().toISOString(),
};

const initialSystem: SystemData = {
  health: {
    ok: false,
    services: {},
    overall_latency_ms: 0,
  },
  logs: [],
  timestamp: new Date().toISOString(),
};

// ── Store Creation ───────────────────────────────────────────────────────────

export const useKalshiStore = create<KalshiStore>()(
  subscribeWithSelector((set, get) => ({
    // Initial state
    portfolio: initialPortfolio,
    risk: initialRisk,
    grid: initialGrid,
    system: initialSystem,
    connected: false,
    lastUpdate: 0,
    
    // Actions
    updatePortfolio: (data) => set((state) => ({
      portfolio: { ...state.portfolio, ...data },
      lastUpdate: Date.now(),
    })),
    
    updateRisk: (data) => set((state) => ({
      risk: { ...state.risk, ...data },
      lastUpdate: Date.now(),
    })),
    
    updateGrid: (data) => set((state) => ({
      grid: { ...state.grid, ...data },
      lastUpdate: Date.now(),
    })),
    
    updateSystem: (data) => set((state) => ({
      system: { ...state.system, ...data },
      lastUpdate: Date.now(),
    })),
    
    setConnected: (connected) => set({ connected }),
    
    refreshAll: async () => {
      // Fetch all data from API (initial load or manual refresh)
      try {
        const API_BASE = 'http://localhost:8011/api/v1';
        
        // Fetch portfolio data
        const balanceRes = await fetch(`${API_BASE}/kalshi/balance`);
        const balanceData = await balanceRes.json();
        
        const pnlRes = await fetch(`${API_BASE}/kalshi/pnl`);
        const pnlData = await pnlRes.json();
        
        const fillsRes = await fetch(`${API_BASE}/kalshi/fills?since_hours=24&limit=100`);
        const fillsData = await fillsRes.json();
        
        // Update portfolio slice with actual API field names
        get().updatePortfolio({
          balance: balanceData.balance_cents / 100 || 0,
          cash: balanceData.balance_cents / 100 || 0,
          portfolio_value: balanceData.balance_cents / 100 || 0,
          daily_pnl: pnlData.total_pnl || 0,
          positions: [], // Balance endpoint doesn't return positions
          fills: fillsData.fills || [],
          timestamp: new Date().toISOString(),
        });
        
        // Fetch risk data
        const riskRes = await fetch(`${API_BASE}/kalshi/risk`);
        const riskData = await riskRes.json();
        
        get().updateRisk({
          daily_pnl: riskData.daily_pnl_usd || 0,
          drawdown_pct: riskData.drawdown_pct || 0,
          total_notional: riskData.total_notional_usd || 0,
          kill_switch_active: riskData.kill_switch_active || false,
          kill_switch_reason: riskData.kill_switch_reason || '',
          sizing_metrics: {
            kelly_fraction: riskData.limits?.kelly_fraction || 0,
            vol_scale: riskData.limits?.vol_scale || 0,
            effective_fraction: riskData.limits?.effective_fraction || 0,
            edge_pct: riskData.limits?.edge_pct || 0,
          },
          alerts: riskData.recent_breaches || [],
          timestamp: riskData.timestamp || new Date().toISOString(),
        });
        
        // Fetch system health
        const healthRes = await fetch(`${API_BASE}/system/health`);
        const healthData = await healthRes.json();
        
        // Convert health data to store format
        const services: Record<string, any> = {};
        if (healthData.components) {
          Object.entries(healthData.components).forEach(([name, comp]: [string, any]) => {
            services[name] = {
              name,
              ok: comp.healthy,
              latency_ms: 0,
              error: comp.healthy ? undefined : comp.message,
            };
          });
        }
        
        get().updateSystem({
          health: {
            ok: healthData.overall_health || false,
            services,
            overall_latency_ms: 0,
          },
          logs: [],
          timestamp: new Date().toISOString(),
        });
        
        get().setConnected(true);
        console.log('[KalshiStore] All data refreshed successfully');
      } catch (error) {
        console.error('[KalshiStore] Failed to refresh data:', error);
        get().setConnected(false);
      }
    },
  }))
);

// ── Selectors (for optimized subscriptions) ───────────────────────────────────

export const selectPortfolio = (state: KalshiStore) => state.portfolio;
export const selectRisk = (state: KalshiStore) => state.risk;
export const selectGrid = (state: KalshiStore) => state.grid;
export const selectSystem = (state: KalshiStore) => state.system;
export const selectConnected = (state: KalshiStore) => state.connected;
