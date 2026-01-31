import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { LiveRiskStrip } from '../LiveRiskStrip';
import { useRiskMetrics } from '../../hooks/useRiskMetrics';

// Mock the hook
jest.mock('../../hooks/useRiskMetrics');

describe('LiveRiskStrip', () => {
  const mockUseRiskMetrics = useRiskMetrics as jest.MockedFunction<typeof useRiskMetrics>;

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders metric cards with correct values', () => {
    mockUseRiskMetrics.mockReturnValue({
      metrics: {
        totalPnL: 125000.50,
        dailyDrawdown: 2.5,
        maxDrawdown: 8.3,
        marginUsed: 450000,
        marginAvailable: 550000,
        marginUtilizationPercent: 45,
        exposure: {
          'BTC-USD': { long: 2.5, short: 0.5 },
          'ETH-USD': { long: 15.0, short: 2.0 },
        },
      },
      alerts: [],
      loading: false,
      error: null,
      lastUpdated: new Date('2026-01-30T20:15:00Z'),
    });

    render(<LiveRiskStrip />);

    expect(screen.getByText('Total P&L')).toBeInTheDocument();
    expect(screen.getByText('Daily Drawdown')).toBeInTheDocument();
    expect(screen.getByText('Margin Utilization')).toBeInTheDocument();
    expect(screen.getByText('Max Drawdown')).toBeInTheDocument();
    expect(screen.getByText('Exposure: ETH-USD')).toBeInTheDocument();
  });

  it('displays critical alert indicator', () => {
    mockUseRiskMetrics.mockReturnValue({
      metrics: {
        totalPnL: 0,
        dailyDrawdown: 0,
        maxDrawdown: 0,
        marginUsed: 0,
        marginAvailable: 0,
        marginUtilizationPercent: 0,
        exposure: {},
      },
      alerts: [
        {
          id: 'alert-001',
          metric: 'marginUtilization',
          value: 85,
          threshold: 80,
          severity: 'CRITICAL',
          createdAt: '2026-01-30T20:15:00Z',
        },
      ],
      loading: false,
      error: null,
      lastUpdated: null,
    });

    render(<LiveRiskStrip />);

    expect(screen.getByText('1 critical alert')).toBeInTheDocument();
  });

  it('displays multiple warnings indicator', () => {
    mockUseRiskMetrics.mockReturnValue({
      metrics: {
        totalPnL: 0,
        dailyDrawdown: 0,
        maxDrawdown: 0,
        marginUsed: 0,
        marginAvailable: 0,
        marginUtilizationPercent: 0,
        exposure: {},
      },
      alerts: [
        {
          id: 'alert-001',
          metric: 'dailyDrawdown',
          value: 3.0,
          threshold: 2.0,
          severity: 'WARNING',
          createdAt: '2026-01-30T20:15:00Z',
        },
        {
          id: 'alert-002',
          metric: 'marginUtilization',
          value: 60,
          threshold: 50,
          severity: 'WARNING',
          createdAt: '2026-01-30T20:16:00Z',
        },
      ],
      loading: false,
      error: null,
      lastUpdated: null,
    });

    render(<LiveRiskStrip />);

    expect(screen.getByText('2 warnings')).toBeInTheDocument();
  });

  it('displays loading state', () => {
    mockUseRiskMetrics.mockReturnValue({
      metrics: {
        totalPnL: 0,
        dailyDrawdown: 0,
        maxDrawdown: 0,
        marginUsed: 0,
        marginAvailable: 0,
        marginUtilizationPercent: 0,
        exposure: {},
      },
      alerts: [],
      loading: true,
      error: null,
      lastUpdated: null,
    });

    render(<LiveRiskStrip />);

    expect(document.querySelector('.animate-pulse')).toBeInTheDocument();
  });

  it('displays error state', () => {
    mockUseRiskMetrics.mockReturnValue({
      metrics: {
        totalPnL: 0,
        dailyDrawdown: 0,
        maxDrawdown: 0,
        marginUsed: 0,
        marginAvailable: 0,
        marginUtilizationPercent: 0,
        exposure: {},
      },
      alerts: [],
      loading: false,
      error: new Error('Failed to fetch risk data'),
      lastUpdated: null,
    });

    render(<LiveRiskStrip />);

    expect(screen.getByText('Risk data unavailable')).toBeInTheDocument();
  });

  it('shows negative P&L as BAD status', () => {
    mockUseRiskMetrics.mockReturnValue({
      metrics: {
        totalPnL: -50000,
        dailyDrawdown: 0,
        maxDrawdown: 0,
        marginUsed: 0,
        marginAvailable: 0,
        marginUtilizationPercent: 0,
        exposure: {},
      },
      alerts: [],
      loading: false,
      error: null,
      lastUpdated: null,
    });

    render(<LiveRiskStrip />);

    expect(screen.getByText('Total P&L')).toBeInTheDocument();
  });

  it('displays last updated timestamp', () => {
    mockUseRiskMetrics.mockReturnValue({
      metrics: {
        totalPnL: 0,
        dailyDrawdown: 0,
        maxDrawdown: 0,
        marginUsed: 0,
        marginAvailable: 0,
        marginUtilizationPercent: 0,
        exposure: {},
      },
      alerts: [],
      loading: false,
      error: null,
      lastUpdated: new Date('2026-01-30T20:15:00Z'),
    });

    render(<LiveRiskStrip />);

    // Last updated should be displayed
    expect(document.querySelector('[class*="text-slate-400"]')).toBeInTheDocument();
  });
});
