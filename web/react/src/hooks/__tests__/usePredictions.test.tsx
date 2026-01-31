import { renderHook, waitFor } from '@testing-library/react';
import { usePredictions } from '../usePredictions';
import { useApiData } from '../useApiData';
import { useMeridSocket } from '../useMeridSocket';
import type { PredictionsResponse, PredictionMarket } from '../../types/predictions';
import type { PredictionPriceChangedPayload, PredictionResolvedPayload } from '../../types/predictions';

// Mock the dependencies
jest.mock('../useApiData');
jest.mock('../useMeridSocket');

describe('usePredictions', () => {
  const mockUseApiData = useApiData as jest.MockedFunction<typeof useApiData>;
  const mockUseMeridSocket = useMeridSocket as jest.MockedFunction<typeof useMeridSocket>;

  const mockOn = jest.fn();
  const mockOff = jest.fn();

  const mockMarket: PredictionMarket = {
    id: 'market-1',
    symbol: 'BTC-YES',
    question: 'Will Bitcoin exceed $100k by end of 2024?',
    marketType: 'BINARY',
    yesPrice: 0.65,
    noPrice: 0.35,
    volume: 1500000,
    liquidity: 250000,
    ourPosition: 'YES',
    ourSize: 1000,
    ourAvgPrice: 0.55,
    ourPnl: 100,
    modelConfidence: 0.75,
    modelPrediction: 'YES',
    status: 'OPEN',
    endTime: '2024-12-31T23:59:59Z',
    lastUpdated: '2024-01-20T12:00:00Z',
  };

  const mockResponse: PredictionsResponse = {
    markets: [mockMarket],
    meta: {
      total: 1,
      open: 1,
      closed: 0,
      totalVolume: 1500000,
      totalPnl: 100,
    },
  };

  beforeEach(() => {
    jest.clearAllMocks();
    jest.spyOn(console, 'log').mockImplementation(() => {});
    jest.spyOn(console, 'warn').mockImplementation(() => {});
    jest.spyOn(console, 'error').mockImplementation(() => {});

    mockUseMeridSocket.mockReturnValue({
      socket: {
        on: mockOn,
        off: mockOff,
        emit: jest.fn(),
        connected: true,
      },
      connected: true,
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('should initialize with empty state when no data', () => {
    mockUseApiData.mockReturnValue({
      data: null,
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: null,
    });

    const { result } = renderHook(() => usePredictions());

    expect(result.current.markets).toEqual([]);
    expect(result.current.meta.total).toBe(0);
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.lastUpdated).toBeNull();
  });

  it('should load markets from REST API', async () => {
    mockUseApiData.mockReturnValue({
      data: mockResponse,
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
    });

    const { result } = renderHook(() => usePredictions());

    await waitFor(() => {
      expect(result.current.markets).toHaveLength(1);
    });

    expect(result.current.markets[0].symbol).toBe('BTC-YES');
    expect(result.current.meta.total).toBe(1);
    expect(result.current.meta.totalPnl).toBe(100);
    expect(result.current.lastUpdated).not.toBeNull();
  });

  it('should handle loading state', () => {
    mockUseApiData.mockReturnValue({
      data: null,
      loading: true,
      error: null,
      refetch: jest.fn(),
      lastUpdated: null,
    });

    const { result } = renderHook(() => usePredictions());

    expect(result.current.loading).toBe(true);
  });

  it('should handle error state', () => {
    mockUseApiData.mockReturnValue({
      data: null,
      loading: false,
      error: new Error('Network error'),
      refetch: jest.fn(),
      lastUpdated: null,
    });

    const { result } = renderHook(() => usePredictions());

    expect(result.current.error).toBeInstanceOf(Error);
  });

  it('should subscribe to WebSocket events on mount', () => {
    mockUseApiData.mockReturnValue({
      data: mockResponse,
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
    });

    renderHook(() => usePredictions());

    expect(mockOn).toHaveBeenCalledWith('prediction:price_changed', expect.any(Function));
    expect(mockOn).toHaveBeenCalledWith('prediction:resolved', expect.any(Function));
  });

  it('should unsubscribe from WebSocket events on unmount', () => {
    mockUseApiData.mockReturnValue({
      data: mockResponse,
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
    });

    const { unmount } = renderHook(() => usePredictions());
    unmount();

    expect(mockOff).toHaveBeenCalledWith('prediction:price_changed', expect.any(Function));
    expect(mockOff).toHaveBeenCalledWith('prediction:resolved', expect.any(Function));
  });

  it('should update market on WebSocket price_changed event', async () => {
    mockUseApiData.mockReturnValue({
      data: mockResponse,
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
    });

    const { result } = renderHook(() => usePredictions());

    await waitFor(() => {
      expect(result.current.markets).toHaveLength(1);
    });

    // Get the update handler
    const updateHandler = mockOn.mock.calls.find(
      call => call[0] === 'prediction:price_changed'
    )?.[1];

    expect(updateHandler).toBeDefined();

    const updatePayload: PredictionPriceChangedPayload = {
      type: 'prediction:price_changed',
      id: 'market-1',
      yesPrice: 0.7,
      noPrice: 0.3,
      volume: 1600000,
      timestamp: '2024-01-20T12:00:00Z',
    };

    // Simulate WebSocket update
    updateHandler(updatePayload);

    await waitFor(() => {
      expect(result.current.markets[0].yesPrice).toBe(0.7);
      expect(result.current.markets[0].volume).toBe(1600000);
    });
  });

  it('should update market on resolution event', async () => {
    mockUseApiData.mockReturnValue({
      data: mockResponse,
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
    });

    const { result } = renderHook(() => usePredictions());

    await waitFor(() => {
      expect(result.current.markets).toHaveLength(1);
    });

    // Get the resolution handler
    const resolveHandler = mockOn.mock.calls.find(
      call => call[0] === 'prediction:resolved'
    )?.[1];

    expect(resolveHandler).toBeDefined();

    const resolvePayload: PredictionResolvedPayload = {
      type: 'prediction:resolved',
      id: 'market-1',
      outcome: 'YES',
      resolutionPrice: 1.0,
      ourPnl: 450,
      resolvedAt: '2024-12-31T23:59:59Z',
    };

    // Simulate resolution
    resolveHandler(resolvePayload);

    await waitFor(() => {
      expect(result.current.markets[0].status).toBe('RESOLVED');
      expect(result.current.markets[0].ourPnl).toBe(450);
    });
  });

  it('should handle invalid WebSocket payload gracefully', async () => {
    mockUseApiData.mockReturnValue({
      data: mockResponse,
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
    });

    renderHook(() => usePredictions());

    const updateHandler = mockOn.mock.calls.find(
      call => call[0] === 'prediction:price_changed'
    )?.[1];

    // Simulate invalid payload
    updateHandler(null);

    expect(console.warn).toHaveBeenCalledWith(
      '[usePredictions] Invalid price_changed payload:',
      null
    );
  });

  it('should compute meta statistics correctly', async () => {
    const multiMarketResponse: PredictionsResponse = {
      markets: [
        { ...mockMarket, id: '1', status: 'OPEN', volume: 1000, ourPnl: 50 },
        { ...mockMarket, id: '2', status: 'OPEN', volume: 2000, ourPnl: -30 },
        { ...mockMarket, id: '3', status: 'CLOSED', volume: 500, ourPnl: 20 },
      ],
      meta: {
        total: 3,
        open: 2,
        closed: 1,
        totalVolume: 3500,
        totalPnl: 40,
      },
    };

    mockUseApiData.mockReturnValue({
      data: multiMarketResponse,
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date(),
    });

    const { result } = renderHook(() => usePredictions());

    await waitFor(() => {
      expect(result.current.markets).toHaveLength(3);
    });

    expect(result.current.meta.total).toBe(3);
    expect(result.current.meta.open).toBe(2);
    expect(result.current.meta.closed).toBe(1);
  });
});
