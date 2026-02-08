import { renderHook, waitFor, act } from '@testing-library/react';
import { useRiskProtections, getCircuitStatusText } from '../useRiskProtections';

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('useRiskProtections', () => {
  const mockData = {
    timestamp: '2024-01-01T00:00:00Z',
    circuit_breaker: {
      state: 'CLOSED' as const,
      state_color: 'green' as const,
      error_count: 0,
      window_seconds: 60,
      threshold: 5,
      last_error_at: null,
      opened_at: null,
      cooldown_seconds: 30,
      half_open_successes: 0,
    },
    lockdown: {
      trading_suite_enabled: true,
      global_mode: 'live',
      spectator_mode: false,
      lockdown_reason: null,
    },
    risk_limits: {
      max_daily_loss_usd: 1000,
      current_daily_pnl: 50,
      daily_loss_utilization_pct: 5,
      max_per_symbol_exposure_usd: 500,
      max_open_orders: 10,
      current_open_orders: 2,
    },
    recent_events: [],
  };

  beforeEach(() => {
    jest.useFakeTimers();
    mockFetch.mockReset();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('should fetch data on mount', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockData,
    });

    const { result } = renderHook(() => useRiskProtections());

    expect(result.current.loading).toBe(true);

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.data).toEqual(mockData);
    expect(result.current.error).toBeNull();
  });

  it('should handle fetch error', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
    });

    const { result } = renderHook(() => useRiskProtections());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.error).toContain('500');
    expect(result.current.data).toBeNull();
  });

  it('should handle network error', async () => {
    mockFetch.mockRejectedValueOnce(new Error('Network error'));

    const { result } = renderHook(() => useRiskProtections());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.error).toBe('Network error');
  });

  it('should poll at specified interval', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => mockData,
    });

    renderHook(() => useRiskProtections(1000));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    act(() => {
      jest.advanceTimersByTime(1000);
    });

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });
  });

  it('should refetch data', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => mockData,
    });

    const { result } = renderHook(() => useRiskProtections());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    await act(async () => {
      await result.current.refetch();
    });

    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it('should reset circuit breaker', async () => {
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockData,
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({}),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockData,
      });

    const { result } = renderHook(() => useRiskProtections());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let success: boolean = false;
    await act(async () => {
      success = await result.current.resetCircuit();
    });

    expect(success).toBe(true);
    expect(mockFetch).toHaveBeenCalledWith('/api/risk/circuit-breaker/reset', expect.any(Object));
  });

  it('should handle reset circuit failure', async () => {
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockData,
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 500,
      });

    const { result } = renderHook(() => useRiskProtections());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let success: boolean = true;
    await act(async () => {
      success = await result.current.resetCircuit();
    });

    expect(success).toBe(false);
  });

  it('should toggle kill switch enable', async () => {
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockData,
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({}),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockData,
      });

    const { result } = renderHook(() => useRiskProtections());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let success: boolean = false;
    await act(async () => {
      success = await result.current.toggleKillSwitch('enable');
    });

    expect(success).toBe(true);
    expect(mockFetch).toHaveBeenCalledWith('/api/risk/kill-switch/enable', expect.any(Object));
  });

  it('should toggle kill switch disable', async () => {
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockData,
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({}),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockData,
      });

    const { result } = renderHook(() => useRiskProtections());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let success: boolean = false;
    await act(async () => {
      success = await result.current.toggleKillSwitch('disable');
    });

    expect(success).toBe(true);
    expect(mockFetch).toHaveBeenCalledWith('/api/risk/kill-switch/disable', expect.any(Object));
  });

  it('should handle kill switch toggle failure', async () => {
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockData,
      })
      .mockRejectedValueOnce(new Error('Network error'));

    const { result } = renderHook(() => useRiskProtections());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    let success: boolean = true;
    await act(async () => {
      success = await result.current.toggleKillSwitch('enable');
    });

    expect(success).toBe(false);
  });
});

describe('getCircuitStatusText', () => {
  it('should return correct text for CLOSED state', () => {
    expect(getCircuitStatusText('CLOSED')).toBe('System Operational');
  });

  it('should return correct text for OPEN state', () => {
    expect(getCircuitStatusText('OPEN')).toBe('Circuit Open - Orders Blocked');
  });

  it('should return correct text for HALF_OPEN state', () => {
    expect(getCircuitStatusText('HALF_OPEN')).toBe('Circuit Half-Open - Testing');
  });

  it('should return Unknown for unknown state', () => {
    expect(getCircuitStatusText('UNKNOWN' as any)).toBe('Unknown');
  });
});
