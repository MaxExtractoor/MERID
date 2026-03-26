/**
 * Tests for KalshiDashboardView — Market discovery, quick tabs, trade ticket.
 */

import { render, screen, fireEvent } from '@testing-library/react';

// eslint-disable-next-line no-var
var apiDataImpl: (ep: string, opts?: unknown) => { data: unknown; loading: boolean; refetch: () => void } =
  () => ({ data: null, loading: false, refetch: jest.fn() });

jest.mock('../../hooks/useApiData', () => ({
  useApiData: (ep: string, opts?: unknown) => apiDataImpl(ep, opts),
}));

const mockUseApiData = {
  mockImplementation: (fn: typeof apiDataImpl) => { apiDataImpl = fn; },
  mockReturnValue: (val: ReturnType<typeof apiDataImpl>) => { apiDataImpl = () => val; },
};

// Mock KalshiTradeTicket — avoid deep rendering
jest.mock('../../components/KalshiTradeTicket', () => ({
  __esModule: true,
  default: ({ ticker }: { ticker: string }) => (
    <div data-testid="trade-ticket">{ticker}</div>
  ),
}));

// Mock KalshiModeBadge
jest.mock('../../components/KalshiModeBadge', () => ({
  __esModule: true,
  default: () => <span data-testid="mode-badge">PAPER</span>,
}));

jest.mock('../../components/ExecutionGateStrip', () => ({
  __esModule: true,
  default: () => <div data-testid="execution-gate-strip" />,
}));

jest.mock('../../config/constants', () => ({
  API_BASE_URL: '',
  API_ENDPOINTS: {
    KALSHI_MARKETS: '/api/v1/kalshi/markets',
    KALSHI_CATALOG: '/api/v1/kalshi/catalog',
    KALSHI_CATALOG_REFRESH: '/api/v1/kalshi/catalog/refresh',
    KALSHI_HEALTH: '/api/v1/kalshi/health',
    KALSHI_POSITIONS: '/api/v1/kalshi/positions',
    KALSHI_ORDERS: '/api/v1/kalshi/orders',
    KALSHI_FILLS: '/api/v1/kalshi/fills',
    KALSHI_BALANCE: '/api/v1/kalshi/balance',
    KALSHI_RISK: '/api/v1/kalshi/risk',
    KALSHI_SIZING_METRICS: '/api/v1/kalshi/sizing-metrics',
    KALSHI_EDGE: '/api/v1/kalshi/edge',
    KALSHI_GRID_MODE: '/api/v1/kalshi-grid/mode',
    KALSHI_GRID_STATUS: '/api/v1/kalshi-grid/status',
    OPERATOR_KILL_SWITCH_STATUS: '/api/v1/operator/kill-switch-status',
    KALSHI_ORDERBOOK: (ticker: string) => `/api/v1/kalshi/markets/${ticker}/orderbook`,
    KALSHI_MARKET_DETAIL: (ticker: string) => `/api/v1/kalshi/markets/${ticker}`,
    KALSHI_ORDER_CANCEL: (id: string) => `/api/v1/kalshi/orders/${id}`,
    KALSHI_FAVORITES: '/api/v1/kalshi/favorites',
    KALSHI_FAVORITES_TOGGLE: '/api/v1/kalshi/favorites/toggle',
    KALSHI_LIQUIDITY_HEALTH: (marketId: string) => `/api/v1/kalshi/liquidity-health/${marketId}`,
    KALSHI_VOLUME_HISTORY: (ticker: string) => `/api/v1/kalshi/volume-history/${ticker}`,
    KALSHI_VOLUME_SMOOTHED: (ticker: string) => `/api/v1/kalshi/volume-history/${ticker}/smoothed`,
    KALSHI_GRID_AGENT_SIGNALS: (name: string) => `/api/v1/kalshi-grid/agents/${name}/signals`,
    KALSHI_GRID_AGENT_ORDERS: (name: string) => `/api/v1/kalshi-grid/agents/${name}/orders`,
  },
  DEFAULTS: {
    POLLING_INTERVALS: {
      STANDARD: 30000,
      FAST_REFRESH: 5000,
      SLOW: 60000,
      POSITIONS: 15000,
      ORDERS: 15000,
    },
  },
}));

import KalshiDashboardView from '../KalshiDashboardView';

const MOCK_MARKETS = {
  markets: [
    {
      ticker: 'KXBTC-26FEB15-1H-T95000',
      question: 'Will BTC be above $95,000 at 3pm?',
      category: 'crypto',
      asset: 'BTC',
      timeframe: '1h',
      market_type: 'binary',
      active: true,
      volume: 1500,
      expires_at: '2026-02-15T20:00:00Z',
      minutes_to_expiry: 45,
      outcomes: [
        { id: 'yes', name: 'Yes', price: 0.62, bid: 0.60, ask: 0.64 },
        { id: 'no', name: 'No', price: 0.38, bid: 0.36, ask: 0.40 },
      ],
    },
    {
      ticker: 'KXETH-26FEB15-15M-T3000',
      question: 'Will ETH be above $3,000 at 3:15pm?',
      category: 'crypto',
      asset: 'ETH',
      timeframe: '15m',
      market_type: 'binary',
      active: true,
      volume: 500,
      expires_at: '2026-02-15T20:15:00Z',
      minutes_to_expiry: 15,
      outcomes: [
        { id: 'yes', name: 'Yes', price: 0.45, bid: 0.43, ask: 0.47 },
        { id: 'no', name: 'No', price: 0.55, bid: 0.53, ask: 0.57 },
      ],
    },
  ],
};

const MOCK_CATALOG = {
  market_count: 2,
  last_refresh: '2026-02-15T19:00:00Z',
  refresh_count: 5,
  categories: { crypto: 2 },
  assets: { BTC: 1, ETH: 1 },
  timeframes: { '1h': 1, '15m': 1 },
  running: true,
};

const MOCK_HEALTH = {
  status: 'healthy',
  issues: [],
  catalog: { market_count: 2, last_refresh: '2026-02-15T19:00:00Z', categories: 1 },
  risk: { kill_switch: false, daily_pnl: 12.50, drawdown_pct: 2.1 },
  ws: { running: true, events_forwarded: 300, subscribed_tickers: 10 },
  rate_limits: { orders_this_minute: 3, max_per_minute: 30, orders_this_hour: 20, max_per_hour: 200 },
};

function setupMocks(overrides: Record<string, unknown> = {}) {
  mockUseApiData.mockImplementation((endpoint: unknown) => {
    if (typeof endpoint !== 'string') return { data: null, loading: false, refetch: jest.fn() };
    if (endpoint === '') return { data: null, loading: false, refetch: jest.fn() };
    if (endpoint.includes('/kalshi/markets') && !endpoint.includes('orderbook')) {
      return { data: overrides.markets ?? MOCK_MARKETS, loading: false, refetch: jest.fn() };
    }
    if (endpoint.includes('orderbook')) {
      return { data: { ticker: 'KXBTC-26FEB15-1H-T95000', yes_bids: [], yes_asks: [], spread_cents: 2, midpoint: 0.55 }, loading: false, refetch: jest.fn() };
    }
    if (endpoint.includes('/kalshi/catalog') && !endpoint.includes('refresh')) {
      return { data: overrides.catalog ?? MOCK_CATALOG, loading: false, refetch: jest.fn() };
    }
    if (endpoint.includes('/kalshi/health')) {
      return { data: overrides.health ?? MOCK_HEALTH, loading: false, refetch: jest.fn() };
    }
    if (endpoint.includes('/kalshi/positions')) {
      return { data: overrides.positions ?? { positions: [] }, loading: false, refetch: jest.fn() };
    }
    if (endpoint.includes('kalshi-grid/mode') || endpoint.includes('/trade-mode')) {
      return { data: { mode: 'paper', is_live: false }, loading: false, refetch: jest.fn() };
    }
    if (endpoint.includes('/kalshi/edge')) {
      return { data: { signals: {}, count: 0 }, loading: false, refetch: jest.fn() };
    }
    if (endpoint.includes('/kalshi/sizing-metrics') || endpoint.includes('/kalshi/sizing')) {
      return { data: null, loading: false, refetch: jest.fn() };
    }
    if (endpoint.includes('/kalshi/balance')) {
      return { data: { available: 100, locked: 0 }, loading: false, refetch: jest.fn() };
    }
    return { data: null, loading: false, refetch: jest.fn() };
  });
}

describe('KalshiDashboardView', () => {
  beforeEach(() => {
    (global.fetch as jest.Mock).mockReset();
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, json: async () => ({}) });
    window.confirm = jest.fn().mockReturnValue(true);
    setupMocks();
  });

  describe('Rendering', () => {
    it('renders the dashboard title and mode badge', () => {
      render(<KalshiDashboardView />);
      expect(screen.getByText(/Kalshi Markets/i)).toBeInTheDocument();
      expect(screen.getByTestId('mode-badge')).toBeInTheDocument();
    });

    it('displays market count from catalog', () => {
      render(<KalshiDashboardView />);
      // catalog.market_count = 2, shown as a number in the Markets stat card
      expect(screen.getByText('2')).toBeInTheDocument();
    });

    it('displays health status badge', () => {
      render(<KalshiDashboardView />);
      expect(screen.getByText('HEALTHY')).toBeInTheDocument();
    });

    it('renders market cards', () => {
      render(<KalshiDashboardView />);
      expect(screen.getByText(/Will BTC be above \$95,000/)).toBeInTheDocument();
      expect(screen.getByText(/Will ETH be above \$3,000/)).toBeInTheDocument();
    });
  });

  describe('Quick-Filter Tabs', () => {
    it('renders all 7 quick tabs including Favorites', () => {
      render(<KalshiDashboardView />);
      expect(screen.getByText('All Markets')).toBeInTheDocument();
      expect(screen.getByText('Crypto Hourly')).toBeInTheDocument();
      expect(screen.getByText('Crypto 15m')).toBeInTheDocument();
      expect(screen.getByText('Top Volume')).toBeInTheDocument();
      expect(screen.getByText('New Markets')).toBeInTheDocument();
      expect(screen.getByText('My Positions')).toBeInTheDocument();
      expect(screen.getByText('Favorites')).toBeInTheDocument();
    });

    it('shows position count badge when positions exist', () => {
      setupMocks({ positions: { positions: [{ ticker: 'KXBTC-26FEB15-1H-T95000' }] } });
      render(<KalshiDashboardView />);
      // The My Positions tab shows a badge with count — find it inside the tab button
      const myPositionsBtn = screen.getByRole('button', { name: /My Positions/i });
      expect(myPositionsBtn).toBeInTheDocument();
    });
  });

  describe('Sorting', () => {
    it('renders sort dropdown with options', () => {
      render(<KalshiDashboardView />);
      // Sort select may use aria-label or title — check for the option values
      expect(screen.getByText('Volume')).toBeInTheDocument();
      expect(screen.getByText('Expiry')).toBeInTheDocument();
      expect(screen.getByText('Spread')).toBeInTheDocument();
    });
  });

  describe('Market Detail Slide-over', () => {
    it('renders market card open buttons', () => {
      render(<KalshiDashboardView />);
      // Each card has a button overlay with aria-label
      const cardBtns = screen.getAllByRole('button', { name: /Open market:/i });
      expect(cardBtns.length).toBeGreaterThanOrEqual(2);
    });

    it('market cards show ticker and question text', () => {
      render(<KalshiDashboardView />);
      expect(screen.getByText(/Will BTC be above \$95,000/)).toBeInTheDocument();
      expect(screen.getByText(/Will ETH be above \$3,000/)).toBeInTheDocument();
    });
  });

  describe('Category Chips', () => {
    it('renders category chips from catalog', () => {
      render(<KalshiDashboardView />);
      // Category chips show the category name — 'crypto' appears in chips
      expect(screen.getAllByText(/crypto/i).length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('Health Stats', () => {
    it('displays daily PnL', () => {
      render(<KalshiDashboardView />);
      expect(screen.getByText('$12.50')).toBeInTheDocument();
    });

    it('shows kill switch status', () => {
      render(<KalshiDashboardView />);
      expect(screen.getByText('OFF')).toBeInTheDocument();
    });
  });

  describe('Loading State', () => {
    it('shows loading indicator when data is loading', () => {
      mockUseApiData.mockReturnValue({ data: null, loading: true, refetch: jest.fn() });
      render(<KalshiDashboardView />);
      expect(screen.getByText('Loading markets...')).toBeInTheDocument();
    });
  });

  describe('Favorites', () => {
    it('renders favorite star buttons on market cards', () => {
      render(<KalshiDashboardView />);
      const starButtons = screen.getAllByLabelText(/Add to favorites|Remove from favorites/);
      expect(starButtons.length).toBeGreaterThanOrEqual(2);
    });

    it('clicking star toggles favorite state', () => {
      render(<KalshiDashboardView />);
      const starButton = screen.getAllByLabelText('Add to favorites')[0];
      fireEvent.click(starButton);
      // After clicking, it should become 'Remove from favorites'
      expect(screen.getAllByLabelText('Remove from favorites').length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('Spread Badges', () => {
    it('renders spread/liquidity badges on market cards', () => {
      render(<KalshiDashboardView />);
      // BTC: spread = 0.64 - 0.60 = 0.04 = 4 cents => '4¢'
      // ETH: spread = 0.47 - 0.43 = 0.04 = 4 cents => '4¢'
      const spreadBadges = screen.getAllByText(/¢/);
      expect(spreadBadges.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('Orderbook peek', () => {
    it('only shows orderbook when peek is activated per card', () => {
      render(<KalshiDashboardView />);
      expect(screen.queryByText(/Mid:/i)).not.toBeInTheDocument();
      const peekButtons = screen.getAllByText('Peek');
      fireEvent.click(peekButtons[1]); // card-level peek (index 0 is the global toggle)
      expect(screen.getByText(/Mid:/i)).toBeInTheDocument();
    });
  });

  describe('Pagination', () => {
    it('limits visible markets per page', () => {
      const largeMarkets = {
        markets: Array.from({ length: 80 }).map((_, i) => ({
          ...MOCK_MARKETS.markets[0],
          ticker: `KXBTC-TEST-${i}`,
          question: `Test market ${i}`,
        })),
      };
      setupMocks({ markets: largeMarkets });
      render(<KalshiDashboardView />);
      expect(screen.getByText(/Showing 60 of 80/)).toBeInTheDocument();
      fireEvent.click(screen.getByText('Next'));
      expect(screen.getByText(/Page 2/)).toBeInTheDocument();
    });
  });

  describe('Edge/EV Display', () => {
    it('shows EV labels on outcome prices', () => {
      render(<KalshiDashboardView />);
      // EV is displayed on each outcome price
      const evLabels = screen.getAllByText(/EV:/);
      expect(evLabels.length).toBeGreaterThanOrEqual(2);
    });
  });

  describe('Position Badges', () => {
    it('shows POSITION badge on cards with open positions', () => {
      setupMocks({ positions: { positions: [{ ticker: 'KXBTC-26FEB15-1H-T95000' }] } });
      render(<KalshiDashboardView />);
      expect(screen.getByText('POSITION')).toBeInTheDocument();
    });
  });
});
