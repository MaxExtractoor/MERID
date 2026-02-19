import { renderHook, waitFor } from '@testing-library/react';
import { useRiskMetrics } from '../useRiskMetrics';
import { useApiData } from '../useApiData';
import { useMeridSocket } from '../useMeridSocket';

// Mock the hooks
jest.mock('../useApiData');
jest.mock('../useMeridSocket');

describe('useRiskMetrics', () => {
  const mockUseApiData = useApiData as jest.MockedFunction<typeof useApiData>;
  const mockUseMeridSocket = useMeridSocket as jest.MockedFunction<typeof useMeridSocket>;
  const mockOn = jest.fn();
  const mockOff = jest.fn();
  const mockEmit = jest.fn();
  const apiBase = { rawResponse: null, isStub: false, stubMessage: '' };

  beforeEach(() => {
    jest.clearAllMocks();

    // Default mock for WebSocket
    mockUseMeridSocket.mockReturnValue({
      socket: { on: mockOn, off: mockOff, emit: mockEmit, connected: true },
      connected: true,
    });
  });

  it('initializes with empty state when no API data', () => {
    mockUseApiData.mockReturnValue({
      data: null,
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: null,
      ...apiBase,
    });

    const { result } = renderHook(() => useRiskMetrics());

    expect(result.current.metrics.totalPnL).toBe(0);
    expect(result.current.metrics.dailyDrawdown).toBe(0);
    expect(result.current.metrics.marginUtilizationPercent).toBe(0);
    expect(result.current.alerts).toEqual([]);
  });

  it('loads initial metrics from API', () => {
    const mockData = {
      totalPnL: 125000.50,
      dailyDrawdown: 2.5,
      maxDrawdown: 8.3,
      marginUsed: 450000,
      marginAvailable: 550000,
      exposure: {
        'BTC-USD': { long: 2.5, short: 0.5 },
        'ETH-USD': { long: 15.0, short: 2.0 },
      },
      alerts: [
        {
          id: 'alert-001',
          metric: 'dailyDrawdown',
          value: 2.5,
          threshold: 2.0,
          severity: 'WARNING' as const,
          createdAt: '2026-01-30T20:15:00Z',
        },
      ],
    };

    mockUseApiData.mockReturnValue({
      data: mockData,
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
      ...apiBase,
    });

    const { result } = renderHook(() => useRiskMetrics());

    expect(result.current.metrics.totalPnL).toBe(125000.50);
    expect(result.current.metrics.dailyDrawdown).toBe(2.5);
    expect(result.current.metrics.marginUtilizationPercent).toBe(45);
    expect(result.current.alerts).toHaveLength(1);
  });

  it('calculates margin utilization correctly', () => {
    mockUseApiData.mockReturnValue({
      data: {
        totalPnL: 0,
        dailyDrawdown: 0,
        maxDrawdown: 0,
        marginUsed: 750000,
        marginAvailable: 250000,
        exposure: {},
        alerts: [],
      },
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
      ...apiBase,
    });

    const { result } = renderHook(() => useRiskMetrics());

    expect(result.current.metrics.marginUtilizationPercent).toBe(75);
  });

  it('handles WebSocket threshold_breached event', async () => {
    mockUseApiData.mockReturnValue({
      data: {
        totalPnL: 0,
        dailyDrawdown: 0,
        maxDrawdown: 0,
        marginUsed: 0,
        marginAvailable: 0,
        exposure: {},
        alerts: [],
      },
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
      ...apiBase,
    });

    const { result } = renderHook(() => useRiskMetrics());

    const breachedHandler = mockOn.mock.calls.find(
      call => call[0] === 'risk:threshold_breached'
    )?.[1];

    expect(breachedHandler).toBeDefined();

    breachedHandler({
      type: 'risk:threshold_breached',
      metric: 'marginUtilization',
      value: 85,
      threshold: 80,
      severity: 'CRITICAL',
    });

    await waitFor(() => {
      expect(result.current.alerts).toHaveLength(1);
    });
    expect(result.current.alerts[0].metric).toBe('marginUtilization');
    expect(result.current.alerts[0].severity).toBe('CRITICAL');
  });

  it('handles WebSocket exposure_changed event', async () => {
    mockUseApiData.mockReturnValue({
      data: {
        totalPnL: 0,
        dailyDrawdown: 0,
        maxDrawdown: 0,
        marginUsed: 0,
        marginAvailable: 0,
        exposure: {
          'BTC-USD': { long: 1.0, short: 0 },
        },
        alerts: [],
      },
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
      ...apiBase,
    });

    const { result } = renderHook(() => useRiskMetrics());

    const exposureHandler = mockOn.mock.calls.find(
      call => call[0] === 'risk:exposure_changed'
    )?.[1];

    exposureHandler({
      type: 'risk:exposure_changed',
      symbol: 'BTC-USD',
      side: 'LONG',
      newExposure: 2.5,
    });

    await waitFor(() => {
      expect(result.current.metrics.exposure['BTC-USD'].long).toBe(2.5);
    });
  });

  it('handles WebSocket pnl_updated event', async () => {
    mockUseApiData.mockReturnValue({
      data: {
        totalPnL: 100000,
        dailyDrawdown: 0,
        maxDrawdown: 0,
        marginUsed: 0,
        marginAvailable: 0,
        exposure: {},
        alerts: [],
      },
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
      ...apiBase,
    });

    const { result } = renderHook(() => useRiskMetrics());

    const pnlHandler = mockOn.mock.calls.find(
      call => call[0] === 'risk:pnl_updated'
    )?.[1];

    pnlHandler({
      type: 'risk:pnl_updated',
      realized: 50000,
      unrealized: 75000,
      total: 125000,
    });

    await waitFor(() => {
      expect(result.current.metrics.totalPnL).toBe(125000);
    });
  });

  it('exposes loading state from API', () => {
    mockUseApiData.mockReturnValue({
      data: null,
      loading: true,
      error: null,
      refetch: jest.fn(),
      lastUpdated: null,
      ...apiBase,
    });

    const { result } = renderHook(() => useRiskMetrics());

    expect(result.current.loading).toBe(true);
  });

  it('exposes error state from API', () => {
    mockUseApiData.mockReturnValue({
      data: null,
      loading: false,
      error: new Error('Network error'),
      refetch: jest.fn(),
      lastUpdated: null,
      ...apiBase,
    });

    const { result } = renderHook(() => useRiskMetrics());

    expect(result.current.error).toBeDefined();
    expect(result.current.error?.message).toBe('Network error');
  });

  it('limits alerts to last 50', async () => {
    mockUseApiData.mockReturnValue({
      data: {
        totalPnL: 0,
        dailyDrawdown: 0,
        maxDrawdown: 0,
        marginUsed: 0,
        marginAvailable: 0,
        exposure: {},
        alerts: [],
      },
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
      ...apiBase,
    });

    const { result } = renderHook(() => useRiskMetrics());

    const breachedHandler = mockOn.mock.calls.find(
      call => call[0] === 'risk:threshold_breached'
    )?.[1];

    // Add 55 alerts
    for (let i = 0; i < 55; i++) {
      breachedHandler({
        type: 'risk:threshold_breached',
        metric: `metric-${i}`,
        value: i,
        threshold: i - 1,
        severity: 'WARNING',
      });
    }

    await waitFor(() => {
      expect(result.current.alerts).toHaveLength(50);
    });
  });
});
