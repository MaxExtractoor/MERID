import { render, screen, act } from '@testing-library/react';
import Trading from '../Trading';

jest.mock('../../hooks/useRiskMetrics');
jest.mock('../../hooks/useOpenOrders');
jest.mock('../../hooks/useApiData');
jest.mock('../../hooks/useMeridSocket');

import { useRiskMetrics } from '../../hooks/useRiskMetrics';
import { useOpenOrders } from '../../hooks/useOpenOrders';
import { useApiData } from '../../hooks/useApiData';
import { useMeridSocket } from '../../hooks/useMeridSocket';

const mockEmit = jest.fn();
const mockOn = jest.fn();
const mockOff = jest.fn();

beforeEach(() => {
  jest.clearAllMocks();

  (useRiskMetrics as jest.Mock).mockReturnValue({
    metrics: { totalPnL: 0, dailyDrawdown: 0, maxDrawdown: 0, marginUsed: 0, marginAvailable: 1, exposure: {} },
    alerts: [],
    loading: false,
    error: null,
    lastUpdated: null,
  });

  (useOpenOrders as jest.Mock).mockReturnValue({
    rows: [],
    meta: { total: 0, pending: 0, partiallyFilled: 0, totalNotional: 0 },
    loading: false,
    error: null,
    lastUpdated: null,
  });

  (useMeridSocket as jest.Mock).mockReturnValue({
    socket: { emit: mockEmit, on: mockOn, off: mockOff, connected: true },
    connected: true,
  });

  (useApiData as jest.Mock).mockImplementation((endpoint: string) => {
    if (endpoint?.includes('/orders') && !endpoint?.includes('/fills')) {
      return {
        data: [{ id: 'ord-1', symbol: 'BTC-USD', side: 'buy', orderType: 'limit', size: 0.5, price: 42500.5, venue: 'COINBASE', status: 'pending', timestamp: '2026-01-30T20:15:00Z' }],
        loading: false,
        error: null,
        refetch: jest.fn(),
        lastUpdated: null,
      };
    }
    return { data: [], loading: false, error: null, refetch: jest.fn(), lastUpdated: null };
  });
});

describe('Trading View Flow', () => {
  it('renders without crashing', () => {
    (useRiskMetrics as jest.Mock).mockReturnValue({
      metrics: { totalPnL: 1234.56, dailyDrawdown: -100, maxDrawdown: -500, marginUsed: 0.25, marginAvailable: 0.75, exposure: {} },
      alerts: [],
      loading: false,
      error: null,
      lastUpdated: new Date('2026-01-30T12:00:00Z'),
    });

    (useOpenOrders as jest.Mock).mockReturnValue({
      rows: [{ id: 'ord-1', symbol: 'BTC-USD', side: 'BUY', type: 'LIMIT', status: 'PENDING', price: 42500.5, size: 0.5, filledSize: 0, remainingSize: 0.5, notional: 21250.25, leverage: 1, venue: 'COINBASE', strategyId: 'strat-1', agentId: 'agent-1', createdAt: '2026-01-30T20:15:00Z', expiresAt: null }],
      meta: { total: 1, pending: 1, partiallyFilled: 0, totalNotional: 21250.25 },
      loading: false,
      error: null,
      lastUpdated: new Date('2026-01-30T12:00:00Z'),
    });

    const { container } = render(<Trading />);
    expect(container).toBeTruthy();
    expect(screen.getByText(/Live Trading/i)).toBeInTheDocument();
  });

  it('handles state updates without crashing', () => {
    const setRiskState: any = {};
    const setOrdersState: any = {};

    (useRiskMetrics as jest.Mock).mockImplementation(() => ({
      metrics: setRiskState.metrics ?? { totalPnL: 0, dailyDrawdown: 0, maxDrawdown: 0, marginUsed: 0, marginAvailable: 1, exposure: {} },
      alerts: setRiskState.alerts ?? [],
      loading: false,
      error: null,
      lastUpdated: setRiskState.lastUpdated ?? null,
    }));

    (useOpenOrders as jest.Mock).mockImplementation(() => ({
      rows: setOrdersState.rows ?? [],
      meta: setOrdersState.meta ?? { total: 0, pending: 0, partiallyFilled: 0, totalNotional: 0 },
      loading: false,
      error: null,
      lastUpdated: setOrdersState.lastUpdated ?? null,
    }));

    const { rerender } = render(<Trading />);

    act(() => {
      setRiskState.metrics = { totalPnL: -500, dailyDrawdown: -300, maxDrawdown: -800, marginUsed: 0.9, marginAvailable: 0.1, exposure: {} };
      setRiskState.alerts = [{ id: 'alert-1', metric: 'marginUsed', value: 0.9, threshold: 0.8, severity: 'CRITICAL', createdAt: '2026-01-30T21:00:00Z' }];
      setOrdersState.rows = [{ id: 'ord-1', symbol: 'BTC-USD', side: 'BUY', type: 'LIMIT', status: 'PARTIALLY_FILLED', price: 42500.5, size: 1, filledSize: 0.5, remainingSize: 0.5, notional: 42500.5, leverage: 1, venue: 'COINBASE', strategyId: 'strat-1', agentId: 'agent-1', createdAt: '2026-01-30T20:15:00Z', expiresAt: null }];
      setOrdersState.meta = { total: 1, pending: 0, partiallyFilled: 1, totalNotional: 42500.5 };
      rerender(<Trading />);
    });

    expect(screen.getByText(/Live Trading/i)).toBeInTheDocument();
  });

  it('does not crash under rapid updates', () => {
    const setRiskState: any = {};
    const setOrdersState: any = {};

    (useRiskMetrics as jest.Mock).mockImplementation(() => ({
      metrics: setRiskState.metrics ?? { totalPnL: 0, dailyDrawdown: 0, maxDrawdown: 0, marginUsed: 0, marginAvailable: 1, exposure: {} },
      alerts: [],
      loading: false,
      error: null,
      lastUpdated: null,
    }));

    (useOpenOrders as jest.Mock).mockImplementation(() => ({
      rows: setOrdersState.rows ?? [],
      meta: setOrdersState.meta ?? { total: 0, pending: 0, partiallyFilled: 0, totalNotional: 0 },
      loading: false,
      error: null,
      lastUpdated: null,
    }));

    const { rerender } = render(<Trading />);

    expect(() => {
      for (let i = 0; i < 50; i++) {
        act(() => {
          setRiskState.metrics = { totalPnL: i, dailyDrawdown: -i, maxDrawdown: -i * 2, marginUsed: Math.min(1, i / 100), marginAvailable: Math.max(0, 1 - i / 100), exposure: {} };
          setOrdersState.rows = [{ id: `ord-${i}`, symbol: 'BTC-USD', side: 'BUY', type: 'LIMIT', status: 'PENDING', price: 40000 + i, size: 0.1, filledSize: 0, remainingSize: 0.1, notional: 4000 + i * 10, leverage: 1, venue: 'COINBASE', strategyId: 'strat-1', agentId: 'agent-1', createdAt: '2026-01-30T20:15:00Z', expiresAt: null }];
          rerender(<Trading />);
        });
      }
    }).not.toThrow();
  });
});
