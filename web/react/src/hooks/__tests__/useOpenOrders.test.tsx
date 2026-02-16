import { renderHook, waitFor } from '@testing-library/react';
import { useOpenOrders } from '../useOpenOrders';
import { useApiData } from '../useApiData';
import { useMeridSocket } from '../useMeridSocket';

// Mock the hooks
jest.mock('../useApiData');
jest.mock('../useMeridSocket');

describe('useOpenOrders', () => {
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

    const { result } = renderHook(() => useOpenOrders());

    expect(result.current.rows).toEqual([]);
    expect(result.current.meta).toEqual({
      total: 0,
      pending: 0,
      partiallyFilled: 0,
      totalNotional: 0,
    });
  });

  it('loads initial orders from API', () => {
    const mockOrders = [
      {
        id: 'ord-001',
        symbol: 'BTC-USD',
        side: 'BUY',
        type: 'LIMIT',
        status: 'PENDING',
        price: 42500.50,
        size: 0.5,
        filledSize: 0.0,
        remainingSize: 0.5,
        notional: 21250.25,
        leverage: 1.0,
        venue: 'COINBASE',
        strategyId: 'strat-001',
        agentId: 'agent-001',
        createdAt: '2026-01-30T20:15:00Z',
        expiresAt: '2026-01-31T20:15:00Z',
      },
    ];

    mockUseApiData.mockReturnValue({
      data: {
        orders: mockOrders,
        meta: { total: 1, pending: 1, partiallyFilled: 0, totalNotional: 21250.25 },
      },
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
      ...apiBase,
    });

    const { result } = renderHook(() => useOpenOrders());

    expect(result.current.rows).toHaveLength(1);
    expect(result.current.rows[0].id).toBe('ord-001');
    expect(result.current.meta.total).toBe(1);
    expect(result.current.meta.pending).toBe(1);
  });

  it('handles WebSocket order:created event', async () => {
    const mockOrders = [
      {
        id: 'ord-001',
        symbol: 'BTC-USD',
        side: 'BUY',
        type: 'LIMIT',
        status: 'PENDING',
        price: 42500.50,
        size: 0.5,
        filledSize: 0.0,
        remainingSize: 0.5,
        notional: 21250.25,
        leverage: 1.0,
        venue: 'COINBASE',
        strategyId: 'strat-001',
        agentId: 'agent-001',
        createdAt: '2026-01-30T20:15:00Z',
        expiresAt: '2026-01-31T20:15:00Z',
      },
    ];

    mockUseApiData.mockReturnValue({
      data: {
        orders: mockOrders,
        meta: { total: 1, pending: 1, partiallyFilled: 0, totalNotional: 21250.25 },
      },
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
      ...apiBase,
    });

    const { result } = renderHook(() => useOpenOrders());

    const createdHandler = mockOn.mock.calls.find(
      call => call[0] === 'order:created'
    )?.[1];

    expect(createdHandler).toBeDefined();

    createdHandler({
      id: 'ord-002',
      symbol: 'ETH-USD',
      side: 'SELL',
      type: 'MARKET',
      status: 'PENDING',
      price: null,
      size: 10.0,
      filledSize: 0.0,
      remainingSize: 10.0,
      notional: 25200.00,
      leverage: 2.0,
      venue: 'BINANCE',
      strategyId: 'strat-002',
      agentId: 'agent-002',
      createdAt: '2026-01-30T20:20:00Z',
      expiresAt: null,
    });

    await waitFor(() => {
      expect(result.current.rows).toHaveLength(2);
    });
    expect(result.current.meta.total).toBe(2);
  });

  it('handles WebSocket order:updated event (partial fill)', async () => {
    const mockOrders = [
      {
        id: 'ord-001',
        symbol: 'BTC-USD',
        side: 'BUY',
        type: 'LIMIT',
        status: 'PENDING',
        price: 42500.50,
        size: 1.0,
        filledSize: 0.0,
        remainingSize: 1.0,
        notional: 42500.50,
        leverage: 1.0,
        venue: 'COINBASE',
        strategyId: 'strat-001',
        agentId: 'agent-001',
        createdAt: '2026-01-30T20:15:00Z',
        expiresAt: null,
      },
    ];

    mockUseApiData.mockReturnValue({
      data: {
        orders: mockOrders,
        meta: { total: 1, pending: 1, partiallyFilled: 0, totalNotional: 42500.50 },
      },
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
      ...apiBase,
    });

    const { result } = renderHook(() => useOpenOrders());

    const updatedHandler = mockOn.mock.calls.find(
      call => call[0] === 'order:updated'
    )?.[1];

    updatedHandler({
      id: 'ord-001',
      status: 'PARTIALLY_FILLED',
      filledSize: 0.5,
      remainingSize: 0.5,
    });

    await waitFor(() => {
      expect(result.current.rows[0].status).toBe('PARTIALLY_FILLED');
    });
    expect(result.current.rows[0].filledSize).toBe(0.5);
    expect(result.current.meta.partiallyFilled).toBe(1);
    expect(result.current.meta.pending).toBe(0);
  });

  it('handles WebSocket order:canceled event', async () => {
    const mockOrders = [
      {
        id: 'ord-001',
        symbol: 'BTC-USD',
        side: 'BUY',
        type: 'LIMIT',
        status: 'PENDING',
        price: 42500.50,
        size: 0.5,
        filledSize: 0.0,
        remainingSize: 0.5,
        notional: 21250.25,
        leverage: 1.0,
        venue: 'COINBASE',
        strategyId: 'strat-001',
        agentId: 'agent-001',
        createdAt: '2026-01-30T20:15:00Z',
        expiresAt: null,
      },
    ];

    mockUseApiData.mockReturnValue({
      data: {
        orders: mockOrders,
        meta: { total: 1, pending: 1, partiallyFilled: 0, totalNotional: 21250.25 },
      },
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
      ...apiBase,
    });

    const { result } = renderHook(() => useOpenOrders());

    const canceledHandler = mockOn.mock.calls.find(
      call => call[0] === 'order:canceled'
    )?.[1];

    canceledHandler({
      id: 'ord-001',
      canceledAt: '2026-01-30T20:25:00Z',
      status: 'CANCELED',
    });

    await waitFor(() => {
      expect(result.current.rows[0].status).toBe('CANCELED');
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

    const { result } = renderHook(() => useOpenOrders());

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

    const { result } = renderHook(() => useOpenOrders());

    expect(result.current.error).toBeDefined();
    expect(result.current.error?.message).toBe('Network error');
  });
});
