import { renderHook, waitFor } from '@testing-library/react';
import { useSystemHealth, usePnLSummary, useAgentsSummary, useTradingSummary } from '../useDashboard';
import { api } from '../../services/api';

// Mock the api service
jest.mock('../../services/api', () => ({
  api: {
    getSystemHealth: jest.fn(),
    getPnLSummary: jest.fn(),
    getAgentSummary: jest.fn(),
    getTradingSummary: jest.fn(),
  },
}));

const mockApi = api as jest.Mocked<typeof api>;

describe('useSystemHealth', () => {
  const mockHealthData = {
    status: 'healthy',
    uptime_seconds: 3600,
    version: '1.0.0',
    components: {
      database: { status: 'healthy', latency_ms: 5 },
      redis: { status: 'healthy', latency_ms: 2 },
    },
  };

  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('should fetch health data on mount', async () => {
    mockApi.getSystemHealth.mockResolvedValueOnce(mockHealthData as any);

    const { result } = renderHook(() => useSystemHealth());

    expect(result.current.loading).toBe(true);

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.health).toEqual(mockHealthData);
    expect(result.current.error).toBeNull();
  });

  it('should handle fetch error', async () => {
    mockApi.getSystemHealth.mockRejectedValueOnce(new Error('API Error'));

    const { result } = renderHook(() => useSystemHealth());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.error).toBe('API Error');
    expect(result.current.health).toBeNull();
  });

  it('should handle non-Error rejection', async () => {
    mockApi.getSystemHealth.mockRejectedValueOnce('String error');

    const { result } = renderHook(() => useSystemHealth());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.error).toBe('Failed to fetch health');
  });
});

describe('usePnLSummary', () => {
  const mockPnLData = {
    today_pnl: 150.50,
    today_pnl_pct: 1.5,
    mtm_pnl: 200.00,
    max_drawdown: -50.00,
    max_drawdown_pct: -0.5,
    limit_daily_loss: 1000,
    limit_utilization_pct: 15,
  };

  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('should fetch P&L data on mount', async () => {
    mockApi.getPnLSummary.mockResolvedValueOnce(mockPnLData as any);

    const { result } = renderHook(() => usePnLSummary());

    expect(result.current.loading).toBe(true);

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.pnl).toEqual(mockPnLData);
  });

  it('should handle fetch error gracefully', async () => {
    mockApi.getPnLSummary.mockRejectedValueOnce(new Error('API Error'));

    const { result } = renderHook(() => usePnLSummary());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    // Error is logged but not exposed
    expect(result.current.pnl).toBeNull();
  });
});

describe('useAgentsSummary', () => {
  const mockAgentsData = {
    agents: [
      {
        id: 'agent-1',
        name: 'Test Agent',
        status: 'active',
        heartbeat_age_ms: 100,
        strategy: 'arbitrage',
        state: 'running',
        positions_count: 2,
        today_pnl: 50.0,
      },
    ],
    summary: {
      total: 5,
      healthy: 4,
      paused: 1,
      unhealthy: 0,
    },
  };

  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('should fetch agents data on mount', async () => {
    mockApi.getAgentSummary.mockResolvedValueOnce(mockAgentsData as any);

    const { result } = renderHook(() => useAgentsSummary());

    expect(result.current.loading).toBe(true);

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.agents).toEqual(mockAgentsData);
  });

  it('should handle fetch error gracefully', async () => {
    mockApi.getAgentSummary.mockRejectedValueOnce(new Error('API Error'));

    const { result } = renderHook(() => useAgentsSummary());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.agents).toBeNull();
  });
});

describe('useTradingSummary', () => {
  const mockTradingData = {
    active_strategies: 3,
    paused_strategies: 1,
    venues_connected: 2,
    venues: ['binance', 'kraken'],
    notional_deployed: 5000,
    notional_capacity: 10000,
    utilization_pct: 50,
  };

  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('should fetch trading data on mount', async () => {
    mockApi.getTradingSummary.mockResolvedValueOnce(mockTradingData as any);

    const { result } = renderHook(() => useTradingSummary());

    expect(result.current.loading).toBe(true);

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.trading).toEqual(mockTradingData);
  });

  it('should handle fetch error gracefully', async () => {
    mockApi.getTradingSummary.mockRejectedValueOnce(new Error('API Error'));

    const { result } = renderHook(() => useTradingSummary());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.trading).toBeNull();
  });
});
