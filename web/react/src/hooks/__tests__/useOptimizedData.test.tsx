/**
 * Tests for useOptimizedData hook
 * Covers race conditions, retry logic, caching, and error handling
 */
import { renderHook, waitFor, act } from '@testing-library/react';
import { useOptimizedData } from '../useOptimizedData';

// Mock constants
jest.mock('../../config/constants', () => ({
  API_BASE_URL: 'http://localhost:8000',
  API_ENDPOINTS: {},
  DEFAULTS: {
    POLLING_INTERVALS: {
      FAST_REFRESH: 5000,
      STANDARD: 10000,
      SLOW: 30000,
    },
  },
  RETRY_DEFAULTS: {
    COUNT: 3,
    DELAY_MS: 1000,
  },
  CACHE_TTL: {
    DEFAULT: 5 * 60 * 1000,
  },
  AUTH_TOKEN_KEY: 'merid-access',
}));

// Mock useWebSocket
jest.mock('../useWebSocket', () => ({
  useWebSocket: jest.fn(() => ({
    connected: false,
    lastMessage: null,
  })),
}));

describe('useOptimizedData', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    global.fetch = jest.fn();
  });

  it('should fetch data on mount', async () => {
    const mockData = { id: 1, name: 'Test' };
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => mockData,
    });

    const { result } = renderHook(() =>
      useOptimizedData({ endpoint: '/api/v1/test' })
    );

    // Initially loading
    expect(result.current.loading).toBe(true);

    // Wait for fetch to complete
    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.data).toEqual(mockData);
    expect(result.current.error).toBeNull();
  });

  it('should handle fetch errors', async () => {
    (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('Network error'));

    const { result } = renderHook(() =>
      useOptimizedData({ endpoint: '/api/v1/test', retryCount: 0 })
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.data).toBeNull();
  });

  it('should retry on failure', async () => {
    jest.useFakeTimers();
    
    (global.fetch as jest.Mock)
      .mockRejectedValueOnce(new Error('First attempt failed'))
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true }),
      });

    const { result } = renderHook(() =>
      useOptimizedData({ 
        endpoint: '/api/v1/test', 
        retryCount: 1, 
        retryDelay: 1000 
      })
    );

    // Wait for initial failure
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledTimes(1);
    });

    // Fast-forward retry delay
    act(() => {
      jest.advanceTimersByTime(1000);
    });

    // Wait for retry
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledTimes(2);
    });

    await waitFor(() => {
      expect(result.current.data).toEqual({ success: true });
    });

    jest.useRealTimers();
  });

  it('should use cached data on subsequent calls', async () => {
    const mockData = { id: 1, cached: true };
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => mockData,
    });

    const { result } = renderHook(() =>
      useOptimizedData({ 
        endpoint: '/api/v1/test',
        cacheKey: 'test-key',
        enableCache: true,
      })
    );

    await waitFor(() => {
      expect(result.current.data).toEqual(mockData);
    });

    // Reset fetch mock
    (global.fetch as jest.Mock).mockClear();

    // Re-render with same cache key
    const { result: result2 } = renderHook(() =>
      useOptimizedData({ 
        endpoint: '/api/v1/test',
        cacheKey: 'test-key',
        enableCache: true,
      })
    );

    // Should use cached data without fetching
    expect(result2.current.data).toEqual(mockData);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('should prevent state updates after unmount', async () => {
    const mockData = { id: 1 };
    let resolveFetch: (value: unknown) => void;
    
    (global.fetch as jest.Mock).mockImplementationOnce(() =>
      new Promise((resolve) => {
        resolveFetch = resolve;
      })
    );

    const { result, unmount } = renderHook(() =>
      useOptimizedData({ endpoint: '/api/v1/test' })
    );

    // Unmount before fetch completes
    unmount();

    // Resolve fetch after unmount
    resolveFetch!({
      ok: true,
      json: async () => mockData,
    });

    // Wait a bit to ensure any state updates would have happened
    await act(async () => {
      await new Promise((r) => setTimeout(r, 100));
    });

    // Component should not have crashed and no state updates should have occurred
    expect(result.current.loading).toBe(true); // Still loading because unmounted
  });

  it('should support manual refetch', async () => {
    const mockData1 = { version: 1 };
    const mockData2 = { version: 2 };
    
    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockData1,
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => mockData2,
      });

    const { result } = renderHook(() =>
      useOptimizedData({ endpoint: '/api/v1/test' })
    );

    await waitFor(() => {
      expect(result.current.data).toEqual(mockData1);
    });

    // Trigger refetch
    await act(async () => {
      await result.current.refetch();
    });

    expect(result.current.data).toEqual(mockData2);
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  it('should clear cache on invalidate', async () => {
    const mockData = { id: 1 };
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => mockData,
    });

    const { result } = renderHook(() =>
      useOptimizedData({ 
        endpoint: '/api/v1/test',
        cacheKey: 'invalidate-test',
        enableCache: true,
      })
    );

    await waitFor(() => {
      expect(result.current.data).toEqual(mockData);
    });

    // Invalidate cache
    act(() => {
      result.current.invalidate();
    });

    expect(result.current.data).toBeNull();
  });
});
