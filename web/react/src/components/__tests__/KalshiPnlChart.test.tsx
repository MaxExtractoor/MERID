/**
 * Tests for KalshiPnlChart — PnL equity curve.
 */

import { render, screen, fireEvent } from '@testing-library/react';

const mockUseApiData = jest.fn();
jest.mock('../../hooks/useApiData', () => ({
  useApiData: (...args: unknown[]) => mockUseApiData(...args),
}));

// Mock constants (ts-jest import.meta workaround)
jest.mock('../../config/constants', () => ({
  API_BASE_URL: '',
  AUTH_TOKEN_KEY: 'merid-access',
  API_ENDPOINTS: { KALSHI_PNL_HISTORY: '/api/v1/kalshi/pnl-history' },
  DEFAULTS: { POLLING_INTERVALS: { STANDARD: 30000, FAST_REFRESH: 5000 } },
  CHART_COLORS: {
    GREEN: '#22c55e', RED: '#ef4444', AMBER: '#f59e0b', INDIGO: '#6366f1',
    AXIS_TICK: '#64748b', GRID_STROKE: '#334155', TOOLTIP_BG: '#0f172a',
    BAR_BASE: '#1e293b', SLATE_400: '#94a3b8', SLATE_600: '#475569',
  },
}));

// Mock recharts — don't render children to avoid SVG-in-div errors in jsdom
jest.mock('recharts', () => ({
  ResponsiveContainer: () => <div data-testid="chart-container" />,
  ComposedChart: () => <div data-testid="composed-chart" />,
  Area: () => null,
  Bar: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  ReferenceLine: () => null,
  ReferenceArea: () => null,
  Legend: () => null,
}));

import KalshiPnlChart from '../KalshiPnlChart';

const MOCK_PNL = {
  points: [
    { ts: '2026-02-16T10:00:00Z', equity: 100, daily_pnl: 0, cumulative_pnl: 0 },
    { ts: '2026-02-16T11:00:00Z', equity: 105, daily_pnl: 5, cumulative_pnl: 5 },
    { ts: '2026-02-16T12:00:00Z', equity: 103, daily_pnl: -2, cumulative_pnl: 3 },
    { ts: '2026-02-16T13:00:00Z', equity: 110, daily_pnl: 7, cumulative_pnl: 10 },
  ],
  breaches: [
    { ts: '2026-02-16T12:30:00Z', check: 'drawdown', reason: 'Hit 5% threshold' },
  ],
};

describe('KalshiPnlChart', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders loading skeleton when data is null and loading', () => {
    mockUseApiData.mockReturnValue({ data: null, loading: true });
    render(<KalshiPnlChart />);
    expect(document.querySelector('.animate-pulse')).toBeTruthy();
  });

  it('renders empty message when no PnL data', () => {
    mockUseApiData.mockReturnValue({ data: { points: [] }, loading: false });
    render(<KalshiPnlChart />);
    expect(screen.getByText(/No PnL history available/i)).toBeInTheDocument();
  });

  it('renders chart when PnL data is available', () => {
    mockUseApiData.mockReturnValue({ data: MOCK_PNL, loading: false });
    render(<KalshiPnlChart />);
    expect(screen.getByText('PnL Curve')).toBeInTheDocument();
    expect(screen.getByTestId('chart-container')).toBeInTheDocument();
    expect(screen.getByText(/\+\$10\.00/)).toBeInTheDocument();
  });

  it('renders category filter tabs', () => {
    mockUseApiData.mockReturnValue({ data: MOCK_PNL, loading: false });
    render(<KalshiPnlChart />);
    expect(screen.getByText('All')).toBeInTheDocument();
    expect(screen.getByText('Crypto')).toBeInTheDocument();
    // LEGACY REMOVAL: Politics category removed - 15m stack is crypto-only
  });

  it('clicking category filter changes active state', () => {
    mockUseApiData.mockReturnValue({ data: MOCK_PNL, loading: false });
    render(<KalshiPnlChart />);
    const cryptoBtn = screen.getByText('Crypto');
    fireEvent.click(cryptoBtn);
    expect(cryptoBtn.className).toContain('orange');
  });

  it('shows negative PnL styling when cumulative PnL is negative', () => {
    const negData = {
      points: [
        { ts: '2026-02-16T10:00:00Z', equity: 100, daily_pnl: 0, cumulative_pnl: 0 },
        { ts: '2026-02-16T11:00:00Z', equity: 95, daily_pnl: -5, cumulative_pnl: -5 },
      ],
      breaches: [],
    };
    mockUseApiData.mockReturnValue({ data: negData, loading: false });
    render(<KalshiPnlChart />);
    expect(screen.getByText(/\$-5\.00/)).toBeInTheDocument();
  });
});
