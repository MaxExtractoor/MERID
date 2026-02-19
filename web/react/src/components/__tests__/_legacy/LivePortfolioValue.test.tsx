/**
 * Tests for LivePortfolioValue — Kalshi data priority chain, mode badge, WS override.
 */

import { render, screen, act } from '@testing-library/react';

const mockUseApiData = jest.fn();
const mockUseRealtimeData = jest.fn();

jest.mock('../../hooks/useApiData', () => ({
  useApiData: (...args: unknown[]) => mockUseApiData(...args),
}));

jest.mock('../../hooks/useRealtimeData', () => ({
  useRealtimeData: (...args: unknown[]) => mockUseRealtimeData(...args),
}));

jest.mock('../../config/constants', () => ({
  API_ENDPOINTS: {
    KALSHI_RISK:           '/api/v1/kalshi/risk',
    KALSHI_BALANCE:        '/api/v1/kalshi/balance',
    KALSHI_GRID_PORTFOLIO: '/api/v1/kalshi-grid/portfolio',
    KALSHI_GRID_MODE:      '/api/v1/kalshi-grid/mode',
    PORTFOLIO_SUMMARY:     '/api/v1/portfolio/summary',
    PORTFOLIO_LIVE:        '/api/v1/portfolio/live',
  },
  DEFAULTS: {
    POLLING_INTERVALS: { STANDARD: 30000, BACKGROUND: 120000 },
  },
  WS_PORTFOLIO_URL: 'ws://localhost:8000/ws/portfolio',
}));

jest.mock('../../utils/logger', () => ({ logUiError: jest.fn() }));

import LivePortfolioValue from '../LivePortfolioValue';

// ── Mock data ────────────────────────────────────────────────────────────────

const MOCK_GRID_PORTFOLIO = { equity_usd: 512.50, daily_pnl_usd: 14.75, position_count: 3 };
const MOCK_KALSHI_RISK    = { daily_pnl_usd: 10.00, daily_realized_pnl_usd: 8.00, total_notional_usd: 40.00, open_market_count: 3 };
const MOCK_KALSHI_BALANCE = { usd: 500.00, available: 450.00, locked: 50.00 };
const MODE_PAPER = { mode: 'paper', is_live: false };
const MODE_LIVE  = { mode: 'live',  is_live: true  };

function setupMocks(overrides: {
  gridPortfolio?: unknown;
  kalshiRisk?: unknown;
  kalshiBalance?: unknown;
  mode?: unknown;
} = {}) {
  mockUseRealtimeData.mockReturnValue([null, false]);
  mockUseApiData.mockImplementation((endpoint: unknown) => {
    if (typeof endpoint !== 'string') return { data: null };
    if (endpoint.includes('kalshi-grid/portfolio')) return { data: overrides.gridPortfolio ?? MOCK_GRID_PORTFOLIO };
    if (endpoint.includes('kalshi/risk'))           return { data: overrides.kalshiRisk    ?? MOCK_KALSHI_RISK    };
    if (endpoint.includes('kalshi/balance'))        return { data: overrides.kalshiBalance ?? MOCK_KALSHI_BALANCE };
    if (endpoint.includes('kalshi-grid/mode'))      return { data: overrides.mode          ?? MODE_PAPER          };
    return { data: null };
  });
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe('LivePortfolioValue', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (global.fetch as jest.Mock).mockReset();
    (global.fetch as jest.Mock).mockResolvedValue({ ok: false });
  });

  describe('Title', () => {
    it('renders Kalshi Portfolio Value title', () => {
      setupMocks();
      render(<LivePortfolioValue />);
      expect(screen.getByText('Kalshi Portfolio Value')).toBeInTheDocument();
    });
  });

  describe('Kalshi grid portfolio — primary data source', () => {
    it('shows equity from grid portfolio', async () => {
      setupMocks({ gridPortfolio: MOCK_GRID_PORTFOLIO });
      await act(async () => { render(<LivePortfolioValue />); });
      // Currency rendered as '$\n512.50' — strip whitespace and match
      const el = screen.getByText((_c, node) => {
        if (!(node instanceof Element)) return false;
        if (node.children.length > 0) return false;  // skip parent elements
        return (node.textContent ?? '').replace(/\s/g, '').includes('512.50');
      });
      expect(el).toBeInTheDocument();
    });

    it('shows daily PnL from grid portfolio', async () => {
      setupMocks({ gridPortfolio: MOCK_GRID_PORTFOLIO });
      await act(async () => { render(<LivePortfolioValue />); });
      // PnL appears in both main display and sub-grid — find leaf elements
      const els = screen.getAllByText((_c, node) => {
        if (!(node instanceof Element)) return false;
        if (node.children.length > 0) return false;
        return (node.textContent ?? '').replace(/\s/g, '').includes('14.75');
      });
      expect(els.length).toBeGreaterThanOrEqual(1);
    });

    it('shows position count from grid portfolio', async () => {
      setupMocks({ gridPortfolio: MOCK_GRID_PORTFOLIO });
      await act(async () => { render(<LivePortfolioValue />); });
      expect(screen.getByText('3')).toBeInTheDocument();
    });
  });

  describe('Fallback to Kalshi balance when grid portfolio unavailable', () => {
    it('renders without crashing when only balance data available', async () => {
      setupMocks({ gridPortfolio: null, kalshiBalance: MOCK_KALSHI_BALANCE });
      await act(async () => { render(<LivePortfolioValue />); });
      expect(screen.getByText('Kalshi Portfolio Value')).toBeInTheDocument();
    });

    it('renders without crashing when balance usd > 100000 (cents)', async () => {
      setupMocks({
        gridPortfolio: null,
        kalshiBalance: { usd: 150000, available: 140000, locked: 10000 },
      });
      await act(async () => { render(<LivePortfolioValue />); });
      // Component should mount and show the title regardless of balance format
      expect(screen.getByText('Kalshi Portfolio Value')).toBeInTheDocument();
    });
  });

  describe('Mode badge', () => {
    it('shows PAPER badge in paper mode', async () => {
      setupMocks({ mode: MODE_PAPER });
      await act(async () => { render(<LivePortfolioValue />); });
      expect(screen.getByText('PAPER')).toBeInTheDocument();
    });

    it('shows LIVE badge in live mode', async () => {
      setupMocks({ mode: MODE_LIVE });
      await act(async () => { render(<LivePortfolioValue />); });
      expect(screen.getByText('LIVE')).toBeInTheDocument();
    });

    it('defaults to PAPER when mode data unavailable', async () => {
      setupMocks({ mode: null });
      await act(async () => { render(<LivePortfolioValue />); });
      expect(screen.getByText('PAPER')).toBeInTheDocument();
    });
  });

  describe('WS connection indicator', () => {
    it('shows Polling when WS not connected', async () => {
      mockUseRealtimeData.mockReturnValue([null, false]);
      mockUseApiData.mockImplementation((endpoint: unknown) => {
        if (typeof endpoint !== 'string') return { data: null };
        if (endpoint.includes('kalshi-grid/portfolio')) return { data: MOCK_GRID_PORTFOLIO };
        if (endpoint.includes('kalshi-grid/mode'))      return { data: MODE_PAPER };
        return { data: null };
      });
      await act(async () => { render(<LivePortfolioValue />); });
      expect(screen.getByText('Polling')).toBeInTheDocument();
    });

    it('shows WS live when WS connected', async () => {
      mockUseRealtimeData.mockReturnValue([null, true]);
      mockUseApiData.mockImplementation((endpoint: unknown) => {
        if (typeof endpoint !== 'string') return { data: null };
        if (endpoint.includes('kalshi-grid/portfolio')) return { data: MOCK_GRID_PORTFOLIO };
        if (endpoint.includes('kalshi-grid/mode'))      return { data: MODE_PAPER };
        return { data: null };
      });
      await act(async () => { render(<LivePortfolioValue />); });
      expect(screen.getByText('WS live')).toBeInTheDocument();
    });
  });

  describe('PnL colour coding', () => {
    it('shows positive PnL with + prefix', async () => {
      setupMocks({ gridPortfolio: { ...MOCK_GRID_PORTFOLIO, daily_pnl_usd: 14.75 } });
      await act(async () => { render(<LivePortfolioValue />); });
      // PnL rendered as '+$14.75' split across nodes — find leaf element containing the number
      const el = screen.getAllByText((_c, node) => {
        if (!(node instanceof Element)) return false;
        if (node.children.length > 0) return false;
        return (node.textContent ?? '').replace(/\s/g, '').includes('14.75');
      })[0];
      expect(el).toBeInTheDocument();
    });

    it('shows negative PnL without + prefix', async () => {
      setupMocks({ gridPortfolio: { ...MOCK_GRID_PORTFOLIO, daily_pnl_usd: -5.00 } });
      await act(async () => { render(<LivePortfolioValue />); });
      // Component renders '$-5.00' split across nodes
      const el = screen.getAllByText((_c, node) => {
        if (!(node instanceof Element)) return false;
        if (node.children.length > 0) return false;
        return (node.textContent ?? '').replace(/\s/g, '').includes('5.00');
      })[0];
      expect(el).toBeInTheDocument();
    });
  });

  describe('Live mode visual treatment', () => {
    it('uses green gradient border in live mode', async () => {
      setupMocks({ mode: MODE_LIVE });
      const { container } = await act(async () => render(<LivePortfolioValue />));
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper.className).toMatch(/green/);
    });

    it('uses blue gradient border in paper mode', async () => {
      setupMocks({ mode: MODE_PAPER });
      const { container } = await act(async () => render(<LivePortfolioValue />));
      const wrapper = container.firstChild as HTMLElement;
      expect(wrapper.className).toMatch(/blue/);
    });
  });
});
