/**
 * Tests for KalshiVolDashboardView — Volatility targeting dashboard (3×2 grid).
 */

import { render, screen, fireEvent } from '@testing-library/react';

const mockUseApiData = jest.fn();
jest.mock('../../hooks/useApiData', () => ({
  useApiData: (...args: unknown[]) => mockUseApiData(...args),
}));

jest.mock('../../components/KalshiModeBadge', () => ({
  __esModule: true,
  default: () => <span data-testid="mode-badge">PAPER</span>,
}));

jest.mock('../../components/KalshiInsightsPanel', () => ({
  __esModule: true,
  default: () => <div data-testid="insights-panel">AI Insights</div>,
}));

import KalshiVolDashboardView from '../KalshiVolDashboardView';

// ── Mock data ──────────────────────────────────────────────────────────────

const MOCK_HEALTH = {
  status: 'healthy',
  issues: [],
  catalog: { market_count: 42 },
  risk: { kill_switch: false, daily_pnl: 15.50, drawdown_pct: 3.2 },
  ws: { running: true, events_forwarded: 1200, subscribed_tickers: 8 },
  rate_limits: { orders_this_minute: 5, max_per_minute: 30, orders_this_hour: 40, max_per_hour: 200 },
};

const MOCK_SIZING = {
  kelly_fraction: 0.12,
  kelly_utilization_pct: 65,
  vol_scale: 0.85,
  target_vol: 0.02,
  realized_vol: 0.0235,
  atr_fraction: 0.008,
  atr_value: 450,
  effective_fraction: 0.0102,
  drawdown_tier: 'normal',
  drawdown_pct: 3.2,
  drawdown_thresholds: { warning: 5, downsize: 10, halt: 15 },
  sharpe_ratio: 2.45,
  sortino_ratio: 3.10,
  calmar_ratio: 4.80,
  win_rate_pct: 62,
  profit_factor: 1.85,
  trades_today: 7,
};

const MOCK_RISK = {
  kill_switch_active: false,
  daily_pnl_usd: 15.50,
  total_notional_usd: 35.00,
  drawdown_pct: 3.2,
  daily_trades: 7,
  daily_fees_usd: 0.84,
  category_notional: { crypto: 30, politics: 5 },
  category_contracts: { crypto: 12, politics: 2 },
  open_market_count: 4,
  limits: { max_daily_loss_usd: 50, drawdown_halt_pct: 0.15, max_total_notional_usd: 200 },
};

const MOCK_GRID = {
  agent_count: 3,
  agents: [
    { name: 'btc-1h', asset: 'BTC', timeframe: '1h', status: 'running', cycles: 120, pf: 1.85, sharpe: 2.10, sortino: 2.80, calmar: 3.50, size_factor: 0.25 },
    { name: 'eth-15m', asset: 'ETH', timeframe: '15m', status: 'running', cycles: 80, pf: 1.42, sharpe: 1.60, sortino: 2.00, calmar: 2.20, size_factor: 0.15 },
    { name: 'btc-15m', asset: 'BTC', timeframe: '15m', status: 'paused', cycles: 50, pf: 0.95, sharpe: 0.80, sortino: 0.90, calmar: 1.10, size_factor: 0.05 },
  ],
};

const MOCK_ALERTS_EMPTY = { alerts: [] };

const MOCK_ALERTS_WITH_DATA = {
  alerts: [
    { market_id: 'KXBTC-1H', kind: 'wide_spread', severity: 'warning', msg: 'Spread 0.12 > 0.08', ts: 1708000000 },
    { market_id: 'KXETH-15M', kind: 'thin_book', severity: 'critical', msg: 'Depth 20 < 50', ts: 1708000010 },
  ],
};

const MOCK_PNL_EMPTY = { points: [] };

const MOCK_PNL_WITH_DATA = {
  points: [
    { ts: '2026-02-15T10:00:00Z', equity: 100, realized_vol: 0.018, target_vol: 0.02 },
    { ts: '2026-02-15T11:00:00Z', equity: 105, realized_vol: 0.021, target_vol: 0.02 },
    { ts: '2026-02-15T12:00:00Z', equity: 108.50, realized_vol: 0.023, target_vol: 0.02 },
  ],
};

// ── Helpers ─────────────────────────────────────────────────────────────────

function setupMocks(overrides: Record<string, unknown> = {}) {
  const refetch = jest.fn();
  // The component calls useApiData 6 times in order:
  //   0: health, 1: sizing, 2: risk, 3: grid, 4: alerts, 5: pnl
  const get = (key: string, fallback: unknown) =>
    key in overrides ? overrides[key] : fallback;
  const responses = [
    { data: get('health', MOCK_HEALTH), loading: false, refetch },
    { data: get('sizing', MOCK_SIZING), loading: false, refetch },
    { data: get('risk', MOCK_RISK), loading: false, refetch },
    { data: get('grid', MOCK_GRID), loading: false, refetch },
    { data: get('alerts', MOCK_ALERTS_EMPTY), loading: false, refetch },
    { data: get('pnl', MOCK_PNL_EMPTY), loading: false, refetch },
  ];
  let callIndex = 0;
  mockUseApiData.mockImplementation(() => {
    const idx = callIndex % responses.length;
    callIndex++;
    return responses[idx];
  });
  return refetch;
}

// ── Tests ───────────────────────────────────────────────────────────────────

describe('KalshiVolDashboardView', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  // ── Header ──────────────────────────────────────────────────────────────

  describe('Header', () => {
    it('renders title and mode badge', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText(/Kalshi Vol Dashboard/)).toBeInTheDocument();
      expect(screen.getByTestId('mode-badge')).toBeInTheDocument();
    });

    it('renders subtitle', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText(/Volatility targeting, risk limits/)).toBeInTheDocument();
    });

    it('renders refresh button that triggers refetch', () => {
      const refetch = setupMocks();
      render(<KalshiVolDashboardView />);
      const btn = screen.getByText('Refresh');
      fireEvent.click(btn);
      expect(refetch).toHaveBeenCalled();
    });
  });

  // ── Venue & Mode Card ───────────────────────────────────────────────────

  describe('Venue & Mode Card', () => {
    it('shows HEALTHY status', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('HEALTHY')).toBeInTheDocument();
    });

    it('shows DEGRADED status', () => {
      setupMocks({ health: { ...MOCK_HEALTH, status: 'degraded', issues: ['ws_disconnected'] } });
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('DEGRADED')).toBeInTheDocument();
    });

    it('shows WS events count', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('1,200')).toBeInTheDocument();
    });

    it('shows market count from catalog', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('42')).toBeInTheDocument();
    });

    it('shows agent count', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText(/3 active/)).toBeInTheDocument();
    });

    it('shows rate limit info', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('5/30/min')).toBeInTheDocument();
    });

    it('shows issue warnings when present', () => {
      setupMocks({ health: { ...MOCK_HEALTH, issues: ['rate_limit_warning'] } });
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('rate_limit_warning')).toBeInTheDocument();
    });
  });

  // ── Vol Targeting Card ──────────────────────────────────────────────────

  describe('Vol Targeting Card', () => {
    it('shows target vol and realized vol', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('2.0%')).toBeInTheDocument();
      expect(screen.getByText('2.4%')).toBeInTheDocument();
    });

    it('shows Kelly fraction', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('0.120')).toBeInTheDocument();
    });

    it('shows Kelly utilization', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('65%')).toBeInTheDocument();
    });

    it('shows vol scale', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('0.85×')).toBeInTheDocument();
    });

    it('shows drawdown tier badge', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('NORMAL')).toBeInTheDocument();
    });

    it('shows WARNING tier when drawdown elevated', () => {
      setupMocks({ sizing: { ...MOCK_SIZING, drawdown_tier: 'warning' } });
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('WARNING')).toBeInTheDocument();
    });

    it('shows effective fraction', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('1.02%')).toBeInTheDocument();
    });

    it('shows loading state when sizing is null', () => {
      setupMocks({ sizing: undefined });
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('Loading sizing data...')).toBeInTheDocument();
    });
  });

  // ── Risk Limits Card ────────────────────────────────────────────────────

  describe('Risk Limits Card', () => {
    it('shows daily PnL', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('$15.50')).toBeInTheDocument();
    });

    it('shows drawdown percentage', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('3.2%')).toBeInTheDocument();
    });

    it('shows total notional', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('$35')).toBeInTheDocument();
    });

    it('shows per-asset exposure bars', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('crypto')).toBeInTheDocument();
      expect(screen.getByText('politics')).toBeInTheDocument();
      expect(screen.getByText('$30')).toBeInTheDocument();
      expect(screen.getByText('$5')).toBeInTheDocument();
    });

    it('shows loading state when risk is null', () => {
      setupMocks({ risk: undefined });
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('Loading risk data...')).toBeInTheDocument();
    });
  });

  // ── Agent Performance Grid ──────────────────────────────────────────────

  describe('Agent Performance Grid', () => {
    it('renders agent table headers', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('Agent')).toBeInTheDocument();
      expect(screen.getByText('PF')).toBeInTheDocument();
      expect(screen.getByText('Sharpe')).toBeInTheDocument();
      expect(screen.getByText('Sortino')).toBeInTheDocument();
      expect(screen.getByText('Calmar')).toBeInTheDocument();
    });

    it('renders each agent row', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('BTC/1h')).toBeInTheDocument();
      expect(screen.getByText('ETH/15m')).toBeInTheDocument();
      expect(screen.getByText('BTC/15m')).toBeInTheDocument();
    });

    it('renders agent PF values', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('1.85')).toBeInTheDocument();
      expect(screen.getByText('1.42')).toBeInTheDocument();
      expect(screen.getByText('0.95')).toBeInTheDocument();
    });

    it('shows empty state when no agents', () => {
      setupMocks({ grid: { agent_count: 0, agents: [] } });
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('No agents running')).toBeInTheDocument();
    });

    it('shows agent count in header', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('3 agents')).toBeInTheDocument();
    });
  });

  // ── Equity & Vol ────────────────────────────────────────────────────────

  describe('Equity & Vol', () => {
    it('shows empty state when no PnL data', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('No PnL history yet')).toBeInTheDocument();
    });

    it('shows latest equity when PnL data present', () => {
      setupMocks({ pnl: MOCK_PNL_WITH_DATA });
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('$108.50')).toBeInTheDocument();
    });

    it('shows risk-adjusted metrics when sizing + PnL available', () => {
      setupMocks({ pnl: MOCK_PNL_WITH_DATA });
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('2.45')).toBeInTheDocument();
      expect(screen.getByText('3.10')).toBeInTheDocument();
      expect(screen.getByText('4.80')).toBeInTheDocument();
    });
  });

  // ── Live Alerts Feed ────────────────────────────────────────────────────

  describe('Live Alerts Feed', () => {
    it('shows empty state', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByText(/No liquidity alerts/)).toBeInTheDocument();
    });

    it('shows alert count', () => {
      setupMocks({ alerts: MOCK_ALERTS_WITH_DATA });
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('2 recent')).toBeInTheDocument();
    });

    it('renders alert messages', () => {
      setupMocks({ alerts: MOCK_ALERTS_WITH_DATA });
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('Spread 0.12 > 0.08')).toBeInTheDocument();
      expect(screen.getByText('Depth 20 < 50')).toBeInTheDocument();
    });

    it('renders alert kind badges', () => {
      setupMocks({ alerts: MOCK_ALERTS_WITH_DATA });
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('wide spread')).toBeInTheDocument();
      expect(screen.getByText('thin book')).toBeInTheDocument();
    });

    it('renders market IDs', () => {
      setupMocks({ alerts: MOCK_ALERTS_WITH_DATA });
      render(<KalshiVolDashboardView />);
      expect(screen.getByText('KXBTC-1H')).toBeInTheDocument();
      expect(screen.getByText('KXETH-15M')).toBeInTheDocument();
    });
  });

  // ── AI Insights Panel ──────────────────────────────────────────────────

  describe('AI Insights Panel', () => {
    it('renders insights panel component', () => {
      setupMocks();
      render(<KalshiVolDashboardView />);
      expect(screen.getByTestId('insights-panel')).toBeInTheDocument();
    });
  });
});
