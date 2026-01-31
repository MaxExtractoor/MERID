import { renderHook, waitFor } from '@testing-library/react';
import { useAgentsHealth } from '../useAgentsHealth';
import { useApiData } from '../useApiData';
import { useMeridSocket } from '../useMeridSocket';

// Mock the hooks
jest.mock('../useApiData');
jest.mock('../useMeridSocket');

describe('useAgentsHealth', () => {
  const mockUseApiData = useApiData as jest.MockedFunction<typeof useApiData>;
  const mockUseMeridSocket = useMeridSocket as jest.MockedFunction<typeof useMeridSocket>;
  const mockOn = jest.fn();
  const mockOff = jest.fn();
  const mockEmit = jest.fn();

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
    });

    const { result } = renderHook(() => useAgentsHealth());

    expect(result.current.rows).toEqual([]);
    expect(result.current.meta).toEqual({
      total: 0,
      online: 0,
      degraded: 0,
      offline: 0,
    });
  });

  it('loads initial agents from API', () => {
    const mockAgents = [
      {
        id: 'agent-001',
        name: 'Alpha',
        role: 'SCALPER',
        strategy: 'MEAN_REVERSION',
        cluster: 'primary',
        status: 'ONLINE',
        cpuPercent: 23.4,
        memoryMb: 512,
        taskCount: 3,
        latencyMs: 12,
        lastSeen: '2026-01-30T23:40:00Z',
      },
    ];

    mockUseApiData.mockReturnValue({
      data: {
        agents: mockAgents,
        meta: { total: 1, online: 1, degraded: 0, offline: 0 },
      },
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
    });

    const { result } = renderHook(() => useAgentsHealth());

    expect(result.current.rows).toHaveLength(1);
    expect(result.current.rows[0].id).toBe('agent-001');
    expect(result.current.meta.total).toBe(1);
  });

  it('handles WebSocket heartbeat updates', async () => {
    const mockAgents = [
      {
        id: 'agent-001',
        name: 'Alpha',
        role: 'SCALPER',
        strategy: 'MEAN_REVERSION',
        cluster: 'primary',
        status: 'ONLINE',
        cpuPercent: 23.4,
        memoryMb: 512,
        taskCount: 3,
        latencyMs: 12,
        lastSeen: '2026-01-30T23:40:00Z',
      },
    ];

    mockUseApiData.mockReturnValue({
      data: {
        agents: mockAgents,
        meta: { total: 1, online: 1, degraded: 0, offline: 0 },
      },
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
    });

    const { result } = renderHook(() => useAgentsHealth());

    // Get the heartbeat handler
    const heartbeatHandler = mockOn.mock.calls.find(
      call => call[0] === 'agent:heartbeat'
    )?.[1];

    expect(heartbeatHandler).toBeDefined();

    // Simulate heartbeat update
    heartbeatHandler({
      id: 'agent-001',
      cpuPercent: 45.0,
      memoryMb: 600,
    });

    await waitFor(() => {
      expect(result.current.rows[0].cpuPercent).toBe(45.0);
      expect(result.current.rows[0].memoryMb).toBe(600);
    });
  });

  it('handles WebSocket status change to offline', async () => {
    const mockAgents = [
      {
        id: 'agent-001',
        name: 'Alpha',
        role: 'SCALPER',
        strategy: 'MEAN_REVERSION',
        cluster: 'primary',
        status: 'ONLINE',
        cpuPercent: 23.4,
        memoryMb: 512,
        taskCount: 3,
        latencyMs: 12,
        lastSeen: '2026-01-30T23:40:00Z',
      },
    ];

    mockUseApiData.mockReturnValue({
      data: {
        agents: mockAgents,
        meta: { total: 1, online: 1, degraded: 0, offline: 0 },
      },
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
    });

    const { result } = renderHook(() => useAgentsHealth());

    const statusHandler = mockOn.mock.calls.find(
      call => call[0] === 'agent:status_changed'
    )?.[1];

    statusHandler({
      id: 'agent-001',
      status: 'OFFLINE',
      lastSeen: '2026-01-30T23:45:00Z',
    });

    await waitFor(() => {
      expect(result.current.rows[0].status).toBe('OFFLINE');
      expect(result.current.meta.offline).toBe(1);
      expect(result.current.meta.online).toBe(0);
    });
  });

  it('handles new agent connected via WebSocket', async () => {
    mockUseApiData.mockReturnValue({
      data: { agents: [], meta: { total: 0, online: 0, degraded: 0, offline: 0 } },
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
    });

    const { result } = renderHook(() => useAgentsHealth());

    const connectedHandler = mockOn.mock.calls.find(
      call => call[0] === 'agent:connected'
    )?.[1];

    connectedHandler({
      id: 'agent-002',
      name: 'Beta',
      role: 'ARBITRAGE',
      strategy: 'CROSS_EXCHANGE',
      cluster: 'primary',
      status: 'ONLINE',
      cpuPercent: 10.0,
      memoryMb: 256,
      taskCount: 1,
      latencyMs: 8,
      lastSeen: '2026-01-30T23:50:00Z',
    });

    await waitFor(() => {
      expect(result.current.rows).toHaveLength(1);
      expect(result.current.rows[0].id).toBe('agent-002');
      expect(result.current.meta.total).toBe(1);
    });
  });

  it('exposes loading state from API', () => {
    mockUseApiData.mockReturnValue({
      data: null,
      loading: true,
      error: null,
      refetch: jest.fn(),
      lastUpdated: null,
    });

    const { result } = renderHook(() => useAgentsHealth());

    expect(result.current.loading).toBe(true);
  });

  it('exposes error state from API', () => {
    mockUseApiData.mockReturnValue({
      data: null,
      loading: false,
      error: new Error('Network error'),
      refetch: jest.fn(),
      lastUpdated: null,
    });

    const { result } = renderHook(() => useAgentsHealth());

    expect(result.current.error).toBeDefined();
    expect(result.current.error?.message).toBe('Network error');
  });
});
