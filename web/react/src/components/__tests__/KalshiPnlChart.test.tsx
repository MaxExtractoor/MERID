/**
 * Tests for KalshiPnlChart — PnL equity curve.
 */

import { render, screen, fireEvent } from '@testing-library/react';

const mockUseApiData = jest.fn();
jest.mock('../../hooks/useApiData', () => ({
  useApiData: (...args: unknown[]) => mockUseApiData(...args),
}));

// Mock recharts to avoid canvas issues in test
jest.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div data-testid="chart-container">{children}</div>,
  ComposedChart: ({ children }: { children: React.ReactNode }) => <div data-testid="composed-chart">{children}</div>,
  Area: () => <div data-testid="area" />,
  Bar: () => <div data-testid="bar" />,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  ReferenceLine: () => null,
  ReferenceArea: () => null,
  Legend: () => null,
}));

import React from 'react';
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

  it('renders asset filter tabs', () => {
    mockUseApiData.mockReturnValue({ data: MOCK_PNL, loading: false });
    render(<KalshiPnlChart />);
    expect(screen.getByText('All')).toBeInTheDocument();
    expect(screen.getByText('BTC')).toBeInTheDocument();
    expect(screen.getByText('ETH')).toBeInTheDocument();
    expect(screen.getByText('SOL')).toBeInTheDocument();
  });

  it('clicking asset filter changes active state', () => {
    mockUseApiData.mockReturnValue({ data: MOCK_PNL, loading: false });
    render(<KalshiPnlChart />);
    const btcBtn = screen.getByText('BTC');
    fireEvent.click(btcBtn);
    // BTC tab should be highlighted
    expect(btcBtn.className).toContain('orange');
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
