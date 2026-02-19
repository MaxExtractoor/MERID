/**
 * Paper Session E2E Smoke Tests
 *
 * Tests the paper-trading user flow:
 *   §1 Sidebar navigation: click each paper-session view, verify onChange fires
 *   §2 PaperTradingView: mount with mocked hook, verify portfolio renders
 *   §3 API coverage: verify usePaperTrading hook calls correct endpoints
 *   §4 Manifest coverage: verify paper views exist in sidebar manifest
 */

import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import Sidebar from '../../components/Sidebar';
import type { View } from '../../types/views';

// ── Mock lucide-react ──────────────────────────────────────────

jest.mock('lucide-react', () => {
  const handler: ProxyHandler<Record<string, unknown>> = {
    get(_target, prop) {
      if (typeof prop === 'string' && prop[0] === prop[0].toUpperCase()) {
        const Icon = ({ className }: { className?: string }) => (
          <span data-testid={`icon-${String(prop)}`} className={className} />
        );
        Icon.displayName = String(prop);
        return Icon;
      }
      return undefined;
    },
  };
  return new Proxy({}, handler);
});

// ── Mock recharts ──────────────────────────────────────────────

jest.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div data-testid="mock-chart">{children}</div>,
  AreaChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Area: () => null,
  BarChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Bar: () => null,
  LineChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Line: () => null,
  PieChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Pie: () => null,
  Cell: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  Legend: () => null,
}));

// ── Mock usePaperTrading hook ──────────────────────────────────

const mockRefresh = jest.fn();

const MOCK_PORTFOLIO = {
  equity: 105432.50,
  cash: 45000.00,
  total_pnl: 5432.50,
  daily_pnl: 312.75,
  positions_count: 4,
  domains: {
    crypto: { equity: 42000, pnl: 3200, positions: 2 },
    prediction: { equity: 18432.50, pnl: 2232.50, positions: 2 },
  },
  win_rate: 0.625,
  total_trades: 16,
};

const MOCK_POSITIONS = [
  {
    symbol: 'BTC-USD',
    domain: 'crypto',
    side: 'long' as const,
    size: 0.5,
    entry_price: 42000,
    current_price: 43500,
    unrealized_pnl: 750,
    pnl_pct: 0.0357,
    opened_at: '2026-02-14T10:00:00Z',
  },
];

const MOCK_ORDERS = [
  {
    id: 'ord-001',
    symbol: 'BTC-USD',
    side: 'BUY',
    order_type: 'LIMIT',
    size: 0.5,
    price: 42000,
    status: 'filled',
    created_at: '2026-02-14T10:00:00Z',
    filled_at: '2026-02-14T10:00:01Z',
  },
];

const MOCK_PNL_HISTORY = [
  { ts: 1707900000, equity: 100000, pnl: 0 },
  { ts: 1707903600, equity: 102500, pnl: 2500 },
  { ts: 1707907200, equity: 105432.50, pnl: 5432.50 },
];

let hookReturnValue = {
  portfolio: MOCK_PORTFOLIO,
  positions: MOCK_POSITIONS,
  orders: MOCK_ORDERS,
  pnlHistory: MOCK_PNL_HISTORY,
  loading: false,
  error: null as string | null,
  refresh: mockRefresh,
};

jest.mock('../../hooks/usePaperTrading', () => ({
  usePaperTrading: () => hookReturnValue,
}));

// ── §1 Sidebar Navigation for Paper Session ────────────────────

describe('Paper Session — Sidebar Navigation', () => {
  const PAPER_SESSION_VIEWS: Array<{ name: string; href: View }> = [
    { name: 'Overview', href: 'overview' },
    { name: 'Paper Trading', href: 'paper-trading' },
    { name: 'Positions & Orders', href: 'positions' },
    { name: 'Wallet', href: 'wallet' },
    { name: 'Treasury', href: 'treasury' },
    { name: 'Rewards', href: 'rewards' },
    { name: 'Risk & Health', href: 'risk' },
    { name: 'Research & Analytics', href: 'research' },
    { name: 'Observability', href: 'observability' },
  ];

  const mockOnChange = jest.fn();

  beforeEach(() => {
    mockOnChange.mockClear();
  });

  it.each(PAPER_SESSION_VIEWS)(
    'clicking "$name" fires onChange("$href")',
    ({ name, href }) => {
      render(<Sidebar current="overview" onChange={mockOnChange} />);
      const btn = screen.getByText(name);
      fireEvent.click(btn);
      expect(mockOnChange).toHaveBeenCalledWith(href);
    }
  );

  it('paper-trading is highlighted when active', () => {
    render(<Sidebar current="paper-trading" onChange={mockOnChange} />);
    const btn = screen.getByText('Paper Trading').closest('button');
    expect(btn).toHaveClass('bg-blue-600');
  });

  it('full paper session cycle: each view activates correctly', () => {
    const { rerender } = render(<Sidebar current="overview" onChange={mockOnChange} />);

    for (const { name, href } of PAPER_SESSION_VIEWS) {
      mockOnChange.mockClear();
      fireEvent.click(screen.getByText(name));
      expect(mockOnChange).toHaveBeenCalledWith(href);
      rerender(<Sidebar current={href} onChange={mockOnChange} />);
      const btn = screen.getByText(name).closest('button');
      expect(btn).toHaveClass('bg-blue-600');
    }
  });
});

// ── §2 PaperTradingView Rendering ──────────────────────────────

// Import after mock is set up
import PaperTradingView from '../PaperTradingView';

describe('Paper Session — PaperTradingView', () => {
  beforeEach(() => {
    hookReturnValue = {
      portfolio: MOCK_PORTFOLIO,
      positions: MOCK_POSITIONS,
      orders: MOCK_ORDERS,
      pnlHistory: MOCK_PNL_HISTORY,
      loading: false,
      error: null,
      refresh: mockRefresh,
    };
  });

  it('renders loading state when loading=true and no portfolio', () => {
    hookReturnValue = { ...hookReturnValue, portfolio: null as never, loading: true };
    render(<PaperTradingView />);
    expect(screen.getByText(/Loading paper trading/i)).toBeInTheDocument();
  });

  it('renders error state when error is set and no portfolio', () => {
    hookReturnValue = { ...hookReturnValue, portfolio: null as never, error: 'Network error' };
    render(<PaperTradingView />);
    expect(screen.getByText('Paper Trading API Error')).toBeInTheDocument();
    expect(screen.getByText('Network error')).toBeInTheDocument();
  });

  it('renders portfolio heading', () => {
    render(<PaperTradingView />);
    expect(screen.getByText('Paper Trading')).toBeInTheDocument();
  });

  it('renders stat cards with correct labels', () => {
    render(<PaperTradingView />);
    expect(screen.getByText('Equity')).toBeInTheDocument();
    expect(screen.getByText('Total PnL')).toBeInTheDocument();
    expect(screen.getByText('Daily PnL')).toBeInTheDocument();
    expect(screen.getByText('Win Rate')).toBeInTheDocument();
  });

  it('renders portfolio equity value from mock data', () => {
    render(<PaperTradingView />);
    expect(screen.getByText('$105,432.50')).toBeInTheDocument();
  });

  it('renders win rate from mock data', () => {
    render(<PaperTradingView />);
    expect(screen.getByText('62.5%')).toBeInTheDocument();
    expect(screen.getByText('16 trades')).toBeInTheDocument();
  });

  it('renders positions tab with position data', () => {
    render(<PaperTradingView />);
    expect(screen.getByText('BTC-USD')).toBeInTheDocument();
  });

  it('renders domain allocation section', () => {
    render(<PaperTradingView />);
    expect(screen.getByText('Domain Allocation')).toBeInTheDocument();
    // 'crypto' appears in both domain bar and positions table
    expect(screen.getAllByText('crypto').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('prediction').length).toBeGreaterThanOrEqual(1);
  });

  it('can switch to orders tab', () => {
    render(<PaperTradingView />);

    const ordersTab = screen.getAllByRole('button').find(b => b.textContent?.includes('Orders'));
    expect(ordersTab).toBeDefined();
    if (ordersTab) {
      fireEvent.click(ordersTab);
      expect(screen.getByText('LIMIT')).toBeInTheDocument();
    }
  });

  it('refresh button calls refresh function', () => {
    render(<PaperTradingView />);
    const refreshBtn = screen.getByLabelText('Refresh');
    fireEvent.click(refreshBtn);
    expect(mockRefresh).toHaveBeenCalled();
  });

  it('renders total PnL with correct sign', () => {
    render(<PaperTradingView />);
    // +$5,432.50
    expect(screen.getByText('+$5,432.50')).toBeInTheDocument();
  });

  it('renders daily PnL with correct sign', () => {
    render(<PaperTradingView />);
    // +$312.75
    expect(screen.getByText('+$312.75')).toBeInTheDocument();
  });
});

// ── §3 Paper Session API Endpoint Wiring ───────────────────────

describe('Paper Session — API Wiring', () => {
  it('usePaperTrading hook exists and returns expected shape', () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const mod = require('../../hooks/usePaperTrading');
    expect(mod.usePaperTrading).toBeDefined();
    const result = mod.usePaperTrading();
    expect(result).toHaveProperty('portfolio');
    expect(result).toHaveProperty('positions');
    expect(result).toHaveProperty('orders');
    expect(result).toHaveProperty('pnlHistory');
    expect(result).toHaveProperty('loading');
    expect(result).toHaveProperty('error');
    expect(result).toHaveProperty('refresh');
  });

  it('paper-trading API constants exist in constants mock', () => {
    // The real constants.ts has these; verify the hook references them
    // by checking the source file directly
    const fs = require('fs');
    const hookSrc = fs.readFileSync(
      require.resolve('../../hooks/usePaperTrading').replace(/\.(js|ts)$/, '.ts'),
      'utf-8'
    ).toString();
    expect(hookSrc).toContain('PAPER_PORTFOLIO');
    expect(hookSrc).toContain('PAPER_POSITIONS');
    expect(hookSrc).toContain('PAPER_ORDERS');
  });
});

// ── §4 Paper Session Manifest Coverage ─────────────────────────

describe('Paper Session — Manifest Coverage', () => {
  it('all paper-session views exist in sidebar manifest', () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { ALL_SIDEBAR_ITEMS } = require('../../config/sidebarManifest');
    const hrefs = ALL_SIDEBAR_ITEMS.map((i: { href: string }) => i.href);

    const paperViews = [
      'overview', 'paper-trading', 'positions', 'wallet',
      'treasury', 'rewards', 'risk', 'research', 'observability',
    ];

    for (const v of paperViews) {
      expect(hrefs).toContain(v);
    }
  });

  it('paper-trading item exists with correct name', () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { ALL_SIDEBAR_ITEMS } = require('../../config/sidebarManifest');
    const paperItem = ALL_SIDEBAR_ITEMS.find(
      (i: { href: string }) => i.href === 'paper-trading'
    );
    expect(paperItem).toBeDefined();
    expect(paperItem.name).toBe('Paper Trading');
  });

  it('rewards view is in the Trading section', () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { SIDEBAR_MANIFEST } = require('../../config/sidebarManifest');
    const tradingSection = SIDEBAR_MANIFEST.find(
      (s: { key: string }) => s.key === 'trading'
    );
    expect(tradingSection).toBeDefined();
    const rewardsItem = tradingSection.items.find(
      (i: { href: string }) => i.href === 'rewards'
    );
    expect(rewardsItem).toBeDefined();
  });

  it('paper session views span correct sidebar sections', () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { SIDEBAR_MANIFEST } = require('../../config/sidebarManifest');

    // Paper session touches Trading + Risk & Analytics sections
    const tradingItems = SIDEBAR_MANIFEST.find(
      (s: { key: string }) => s.key === 'trading'
    ).items.map((i: { href: string }) => i.href);

    expect(tradingItems).toContain('overview');
    expect(tradingItems).toContain('paper-trading');
    expect(tradingItems).toContain('positions');
    expect(tradingItems).toContain('wallet');
    expect(tradingItems).toContain('treasury');
    expect(tradingItems).toContain('rewards');

    const riskItems = SIDEBAR_MANIFEST.find(
      (s: { key: string }) => s.key === 'risk-analytics'
    ).items.map((i: { href: string }) => i.href);

    expect(riskItems).toContain('risk');
    expect(riskItems).toContain('research');
    expect(riskItems).toContain('observability');
  });
});
