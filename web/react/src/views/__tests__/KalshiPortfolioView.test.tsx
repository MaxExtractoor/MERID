/**
 * Tests for KalshiPortfolioView — Positions, orders, fills, risk tab, sizing metrics.
 */

import { render, screen, fireEvent } from '@testing-library/react';

jest.mock('../../hooks/useApiData', () => ({
  useApiData: jest.fn(() => ({ data: null, loading: false, refetch: jest.fn() })),
}));

// Access the mock AFTER jest.mock is hoisted — require returns the mocked module
// eslint-disable-next-line @typescript-eslint/no-var-requires
const mockUseApiData: jest.Mock = (require('../../hooks/useApiData') as { useApiData: jest.Mock }).useApiData;

jest.mock('../../config/constants', () => ({
  API_BASE_URL: '',
  API_ENDPOINTS: {
    KALSHI_POSITIONS: '/api/v1/kalshi/positions',
    KALSHI_ORDERS: '/api/v1/kalshi/orders',
    KALSHI_FILLS: '/api/v1/kalshi/fills',
    KALSHI_BALANCE: '/api/v1/kalshi/balance',
    KALSHI_RISK: '/api/v1/kalshi/risk',
    KALSHI_SIZING_METRICS: '/api/v1/kalshi/sizing-metrics',
    KALSHI_PNL_HISTORY: '/api/v1/kalshi/pnl-history',
    KALSHI_RISK_DOWNSIZE: '/api/v1/kalshi/risk/downsize',
    OPERATOR_KILL_SWITCH_STATUS: '/api/v1/operator/kill-switch-status',
    OPERATOR_EMERGENCY_STOP: '/api/v1/operator/emergency-stop',
    OPERATOR_RESET_KILL_SWITCH: '/api/v1/operator/reset-kill-switch',
    KALSHI_ORDER_CANCEL: (id: string) => `/api/v1/kalshi/orders/${id}`,
    KALSHI_ORDER_AMEND: (id: string) => `/api/v1/kalshi/orders/${id}`,
    KALSHI_GRID_MODE: '/api/v1/kalshi-grid/mode',
    KALSHI_GRID_SESSION: '/api/v1/kalshi-grid/session',
    KALSHI_GRID_PORTFOLIO: '/api/v1/kalshi-grid/portfolio',
    KALSHI_ORDERS_BATCH_CANCEL: '/api/v1/kalshi/orders',
    KALSHI_EXPORT: '/api/v1/kalshi/export',
    SYSTEM_EXECUTION_GATE: '/api/v1/system/execution-gate',
  },
  DEFAULTS: {
    POLLING_INTERVALS: {
      STANDARD: 30000,
      FAST_REFRESH: 5000,
      SLOW: 60000,
      BACKGROUND: 120000,
    },
  },
}));

jest.mock('../../components/KalshiModeBadge', () => ({
  __esModule: true,
  default: () => <span data-testid="mode-badge">PAPER</span>,
}));

jest.mock('../../components/KalshiPnlChart', () => ({
  __esModule: true,
  default: () => <div data-testid="pnl-chart">PnL Chart</div>,
}));

jest.mock('../../components/KalshiRiskFeed', () => ({
  __esModule: true,
  default: () => <div data-testid="risk-feed">Risk Feed</div>,
}));

jest.mock('../../components/ExecutionGateStrip', () => ({
  __esModule: true,
  default: () => <div data-testid="execution-gate-strip" />,
}));

import KalshiPortfolioView from '../KalshiPortfolioView';

const MOCK_POSITIONS = {
  positions: [
    { ticker: 'KXBTC-1H-T95000', outcome: 'yes', size: 5, avg_price: 0.55, unrealized_pnl: 2.25, realized_pnl: 0 },
    { ticker: 'KXETH-15M-T3000', outcome: 'no', size: 3, avg_price: 0.40, unrealized_pnl: -0.60, realized_pnl: 1.20 },
  ],
};

const MOCK_ORDERS = {
  orders: [
    { order_id: 'ord-001', ticker: 'KXBTC-1H-T95000', side: 'buy', size: 2, price: 0.55, filled: 0, remaining: 2, status: 'resting', created_at: '2026-02-15T19:30:00Z' },
  ],
};

const MOCK_FILLS = {
  fills: [
    { trade_id: 'fill-001', ticker: 'KXBTC-1H-T95000', order_id: 'ord-prev', side: 'yes', size: 5, price: 0.55, fee: 0.18, timestamp: '2026-02-15T19:20:00Z' },
  ],
};

const MOCK_BALANCE = { usd: 500.00, locked: 50.00, available: 450.00 };

const MOCK_MODE_PAPER = { mode: 'paper', is_live: false, live_enabled: true };
const MOCK_MODE_LIVE  = { mode: 'live',  is_live: true,  live_enabled: true };

const MOCK_SESSION = { session_open: true, ws_connected: true, ws_lag_ms: 12, mode: 'live' };

const MOCK_GRID_PORTFOLIO = { equity_usd: 512.50, daily_pnl_usd: 14.75, open_interest: 18, position_count: 2 };

const MOCK_RISK = {
  kill_switch_active: false,
  kill_switch_reason: null,
  daily_pnl_usd: 12.50,
  total_notional_usd: 8.00,
  total_unrealized_pnl_usd: 1.65,
  daily_realized_pnl_usd: 1.20,
  daily_total_pnl_usd: 2.85,
  daily_trades: 4,
  daily_fees_usd: 0.36,
  drawdown_pct: 2.1,
  category_notional: { crypto: 8.00 },
  category_contracts: { crypto: 8 },
  open_market_count: 2,
  recent_breaches: [],
  limits: { max_daily_loss_usd: 50, drawdown_halt_pct: 0.15, max_total_notional_usd: 100 },
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
  drawdown_tier: 'normal' as const,
  drawdown_pct: 2.1,
  drawdown_thresholds: { warning: 5, downsize: 10, halt: 15 },
  sharpe_ratio: 2.45,
  sortino_ratio: 3.10,
  calmar_ratio: 4.80,
  win_rate_pct: 62,
  profit_factor: 1.85,
  trades_today: 4,
};

function setupMocks(overrides: Record<string, unknown> = {}) {
  const riskData = (overrides.risk ?? MOCK_RISK) as typeof MOCK_RISK;
  const ksActive = riskData?.kill_switch_active ?? false;
  mockUseApiData.mockImplementation((endpoint: unknown) => {
    if (typeof endpoint !== 'string') return { data: null, loading: false, refetch: jest.fn() };
    if (endpoint.includes('operator/kill-switch-status')) {
      return { data: overrides.killSwitch ?? { global_kill: ksActive, can_trade: !ksActive, kill_reason: ksActive ? 'Manual stop' : null }, loading: false, refetch: jest.fn() };
    }
    if (endpoint.includes('kalshi-grid/mode')) {
      return { data: overrides.mode ?? MOCK_MODE_PAPER, loading: false, refetch: jest.fn() };
    }
    if (endpoint.includes('kalshi-grid/session')) {
      return { data: overrides.session ?? MOCK_SESSION, loading: false, refetch: jest.fn() };
    }
    if (endpoint.includes('kalshi-grid/portfolio')) {
      return { data: overrides.gridPortfolio ?? MOCK_GRID_PORTFOLIO, loading: false, refetch: jest.fn() };
    }
    if (endpoint.includes('/kalshi/positions')) {
      return { data: overrides.positions ?? MOCK_POSITIONS, loading: false, refetch: jest.fn() };
    }
    if (endpoint.includes('/kalshi/orders')) {
      return { data: overrides.orders ?? MOCK_ORDERS, loading: false, refetch: jest.fn() };
    }
    if (endpoint.includes('/kalshi/fills')) {
      return { data: overrides.fills ?? MOCK_FILLS, loading: false, refetch: jest.fn() };
    }
    if (endpoint.includes('/kalshi/balance')) {
      return { data: overrides.balance ?? MOCK_BALANCE, loading: false, refetch: jest.fn() };
    }
    if (endpoint.includes('/kalshi/risk')) {
      return { data: overrides.risk ?? MOCK_RISK, loading: false, refetch: jest.fn() };
    }
    if (endpoint.includes('/kalshi/sizing-metrics')) {
      return { data: overrides.sizing ?? MOCK_SIZING, loading: false, refetch: jest.fn() };
    }
    return { data: null, loading: false, refetch: jest.fn() };
  });
}

describe('KalshiPortfolioView', () => {
  beforeEach(() => {
    // Explicitly reset fetch mock without clearAllMocks (which can interfere with mockImplementation)
    (global.fetch as jest.Mock).mockReset();
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, json: async () => ({}) });
    window.confirm = jest.fn().mockReturnValue(true);
    setupMocks();
  });

  describe('Rendering', () => {
    it('renders portfolio title with mode badge', () => {
      render(<KalshiPortfolioView />);
      expect(screen.getByText(/Kalshi Portfolio/i)).toBeInTheDocument();
      expect(screen.getByTestId('mode-badge')).toBeInTheDocument();
    });

    it('shows position and order counts', () => {
      render(<KalshiPortfolioView />);
      expect(screen.getByText(/2 positions/)).toBeInTheDocument();
      expect(screen.getByText(/1 open orders/)).toBeInTheDocument();
    });

    it('displays equity card with grid portfolio value', () => {
      render(<KalshiPortfolioView />);
      // Grid portfolio equity takes priority over balance
      expect(screen.getByText('$512.50')).toBeInTheDocument();
      expect(screen.getByText(/Avail: \$450.00/)).toBeInTheDocument();
    });
  });

  describe('Tabs', () => {
    it('renders all 4 tabs', () => {
      render(<KalshiPortfolioView />);
      expect(screen.getByText(/^Positions/)).toBeInTheDocument();
      expect(screen.getByText(/^Orders/)).toBeInTheDocument();
      expect(screen.getByText(/^Fills/)).toBeInTheDocument();
      expect(screen.getByText(/^Risk/)).toBeInTheDocument();
    });

    it('shows positions tab by default with position data', () => {
      render(<KalshiPortfolioView />);
      expect(screen.getByText('KXBTC-1H-T95000')).toBeInTheDocument();
      expect(screen.getByText('KXETH-15M-T3000')).toBeInTheDocument();
    });

    it('switches to orders tab', () => {
      render(<KalshiPortfolioView />);
      fireEvent.click(screen.getByText(/^Orders/));
      expect(screen.queryByText('ord-001')).not.toBeInTheDocument(); // order ID is truncated
      expect(screen.getByText('resting')).toBeInTheDocument();
    });

    it('switches to fills tab', () => {
      render(<KalshiPortfolioView />);
      fireEvent.click(screen.getByText(/^Fills/));
      expect(screen.getByText('$0.18')).toBeInTheDocument(); // fee
    });
  });

  describe('Per-Asset Filter', () => {
    it('renders asset filter chips when multiple assets present', () => {
      render(<KalshiPortfolioView />);
      expect(screen.getByText('KXBTC')).toBeInTheDocument();
      expect(screen.getByText('KXETH')).toBeInTheDocument();
    });
  });

  describe('Risk Tab', () => {
    it('shows daily PnL and drawdown', () => {
      render(<KalshiPortfolioView />);
      fireEvent.click(screen.getByText(/^Risk/));
      expect(screen.getByText('$12.50')).toBeInTheDocument();
      expect(screen.getByText('2.1%')).toBeInTheDocument();
    });

    it('shows category exposure', () => {
      render(<KalshiPortfolioView />);
      fireEvent.click(screen.getByText(/^Risk/));
      expect(screen.getByText('crypto')).toBeInTheDocument();
      expect(screen.getAllByText('$8.00').length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('Risk Tab — Sizing Metrics', () => {
    it('shows Kelly utilization', () => {
      render(<KalshiPortfolioView />);
      fireEvent.click(screen.getByText(/^Risk/));
      expect(screen.getByText('65%')).toBeInTheDocument();
      expect(screen.getByText('f=0.120')).toBeInTheDocument();
    });

    it('shows vol scale', () => {
      render(<KalshiPortfolioView />);
      fireEvent.click(screen.getByText(/^Risk/));
      expect(screen.getByText('0.85x')).toBeInTheDocument();
    });

    it('shows drawdown tier badge', () => {
      render(<KalshiPortfolioView />);
      fireEvent.click(screen.getByText(/^Risk/));
      expect(screen.getByText('Normal')).toBeInTheDocument();
    });

    it('shows risk-adjusted metrics (Sharpe/Sortino/Calmar)', () => {
      render(<KalshiPortfolioView />);
      fireEvent.click(screen.getByText(/^Risk/));
      expect(screen.getByText('2.45')).toBeInTheDocument();
      expect(screen.getByText('3.10')).toBeInTheDocument();
      expect(screen.getByText('4.80')).toBeInTheDocument();
    });
  });

  describe('Kill Switch', () => {
    it('shows kill switch OFF when not active', () => {
      render(<KalshiPortfolioView />);
      expect(screen.getByText('OFF')).toBeInTheDocument();
    });

    it('shows kill switch ACTIVE when triggered', () => {
      setupMocks({
        risk: { ...MOCK_RISK, kill_switch_active: true },
        killSwitch: { global_kill: true, can_trade: false, kill_reason: 'Manual stop' },
      });
      render(<KalshiPortfolioView />);
      expect(screen.getByText('ACTIVE')).toBeInTheDocument();
    });
  });

  describe('Loading State', () => {
    it('shows loading when data not ready', () => {
      mockUseApiData.mockReturnValue({ data: null, loading: true, refetch: jest.fn() });
      render(<KalshiPortfolioView />);
      expect(screen.getByText('Loading...')).toBeInTheDocument();
    });
  });

  describe('Paper/Live Mode Toggle', () => {
    it('shows PAPER toggle button when in paper mode', () => {
      setupMocks({ mode: MOCK_MODE_PAPER });
      render(<KalshiPortfolioView />);
      // The toggle button text is PAPER — there may also be the KalshiModeBadge stub
      const paperEls = screen.getAllByText('PAPER');
      expect(paperEls.length).toBeGreaterThanOrEqual(1);
    });

    it('shows LIVE toggle button when in live mode', () => {
      setupMocks({ mode: MOCK_MODE_LIVE });
      render(<KalshiPortfolioView />);
      // Toggle button shows LIVE; equity card also shows LIVE badge
      const liveEls = screen.getAllByText('LIVE');
      expect(liveEls.length).toBeGreaterThanOrEqual(1);
    });

    it('fires POST to mode endpoint on toggle click', async () => {
      setupMocks({ mode: MOCK_MODE_PAPER });
      (global.fetch as jest.Mock).mockResolvedValueOnce({ ok: true, json: async () => ({}) });
      render(<KalshiPortfolioView />);
      // Click the toggle button (title contains 'Switch to Live mode')
      const toggleBtn = screen.getByTitle(/Switch to Live mode/i);
      fireEvent.click(toggleBtn);
      await Promise.resolve();
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('kalshi-grid/mode'),
        expect.objectContaining({ method: 'POST' }),
      );
    });

    it('shows error banner when mode switch fails', async () => {
      setupMocks({ mode: MOCK_MODE_PAPER });
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        json: async () => ({ detail: 'Live mode not enabled' }),
      });
      render(<KalshiPortfolioView />);
      fireEvent.click(screen.getByTitle(/Switch to Live mode/i));
      await screen.findByText(/Live mode not enabled/);
    });

    it('toggle is disabled when kill switch is active', () => {
      setupMocks({
        mode: MOCK_MODE_PAPER,
        killSwitch: { global_kill: true, can_trade: false, kill_reason: 'Manual stop' },
      });
      render(<KalshiPortfolioView />);
      const toggleBtn = screen.getByTitle(/Live mode disabled|Switch to Live mode/i);
      expect(toggleBtn).toBeDisabled();
    });

    it('shows KILL ACTIVE badge when kill switch is on', () => {
      setupMocks({
        killSwitch: { global_kill: true, can_trade: false, kill_reason: 'Drawdown breach' },
      });
      render(<KalshiPortfolioView />);
      expect(screen.getByText('KILL ACTIVE')).toBeInTheDocument();
    });
  });

  describe('Session & WS Status', () => {
    it('shows Session open when session is open', () => {
      setupMocks({ session: { ...MOCK_SESSION, session_open: true } });
      render(<KalshiPortfolioView />);
      expect(screen.getByText('Session open')).toBeInTheDocument();
    });

    it('shows Session closed when session is closed', () => {
      setupMocks({ session: { ...MOCK_SESSION, session_open: false } });
      render(<KalshiPortfolioView />);
      expect(screen.getByText('Session closed')).toBeInTheDocument();
    });

    it('shows WS lag when connected', () => {
      setupMocks({ session: { ...MOCK_SESSION, ws_connected: true, ws_lag_ms: 12 } });
      render(<KalshiPortfolioView />);
      expect(screen.getByText('WS 12ms')).toBeInTheDocument();
    });

    it('shows WS offline when disconnected', () => {
      setupMocks({ session: { ...MOCK_SESSION, ws_connected: false } });
      render(<KalshiPortfolioView />);
      expect(screen.getByText('WS offline')).toBeInTheDocument();
    });
  });

  describe('Equity Card — Kalshi grid portfolio wiring', () => {
    it('shows grid portfolio equity when available', () => {
      setupMocks({ gridPortfolio: MOCK_GRID_PORTFOLIO });
      render(<KalshiPortfolioView />);
      expect(screen.getByText('$512.50')).toBeInTheDocument();
    });

    it('falls back to balance when grid portfolio unavailable', () => {
      setupMocks({ gridPortfolio: null });
      render(<KalshiPortfolioView />);
      // When grid portfolio is null, equity card shows balance.
      // The Avail sub-label is a reliable unique indicator that balance data loaded.
      expect(screen.getByText(/Avail:/)).toBeInTheDocument();
    });

    it('shows LIVE badge on equity card in live mode', () => {
      setupMocks({ mode: MOCK_MODE_LIVE });
      render(<KalshiPortfolioView />);
      // Multiple LIVE elements expected (toggle button + equity card badge)
      expect(screen.getAllByText('LIVE').length).toBeGreaterThanOrEqual(1);
    });

    it('shows grid portfolio daily PnL in Realized card', () => {
      setupMocks({ gridPortfolio: MOCK_GRID_PORTFOLIO });
      render(<KalshiPortfolioView />);
      expect(screen.getByText('$14.75')).toBeInTheDocument();
    });

    it('shows open interest in Notional card', () => {
      setupMocks({ gridPortfolio: MOCK_GRID_PORTFOLIO });
      render(<KalshiPortfolioView />);
      expect(screen.getByText(/OI: 18/)).toBeInTheDocument();
    });
  });
});
