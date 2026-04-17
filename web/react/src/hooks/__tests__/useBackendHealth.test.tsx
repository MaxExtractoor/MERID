/**
 * Tests for BackendHealthContext, useApiData backoff integration,
 * useKalshiRiskStream offline flag, and BackendOfflineBanner.
 */

import React from 'react';
import { render, screen, waitFor, act, renderHook } from '@testing-library/react';
import { BackendHealthProvider, useBackendHealth } from '../../context/BackendHealthContext';
import { useApiData } from '../useApiData';
import BackendOfflineBanner from '../../components/BackendOfflineBanner';

// ── Helpers ──

const wrapper: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <BackendHealthProvider>{children}</BackendHealthProvider>
);

let fetchMock: jest.Mock;

beforeEach(() => {
  jest.useFakeTimers();
  fetchMock = jest.fn();
  global.fetch = fetchMock;
});

afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});

// ── BackendHealthContext tests ──

describe('BackendHealthContext', () => {
  it('starts with backendOffline=false', () => {
    // Probe will fire but hasn't failed yet.
    fetchMock.mockResolvedValue({ ok: true, status: 200 });
    const { result } = renderHook(() => useBackendHealth(), { wrapper });
    expect(result.current.backendOffline).toBe(false);
    expect(result.current.consecutiveFailures).toBe(0);
  });

  it('marks offline after 2 consecutive probe failures', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    const { result } = renderHook(() => useBackendHealth(), { wrapper });

    // First probe fires on mount — wait for it.
    await act(async () => {
      await Promise.resolve(); // flush microtasks
    });
    // After 1 failure: not yet offline (threshold is 2).
    expect(result.current.consecutiveFailures).toBe(1);
    expect(result.current.backendOffline).toBe(false);

    // Advance timer to trigger second probe.
    await act(async () => {
      jest.advanceTimersByTime(3_000);
      await Promise.resolve();
    });

    expect(result.current.consecutiveFailures).toBe(2);
    expect(result.current.backendOffline).toBe(true);
  });

  it('recovers when probe succeeds after being offline', async () => {
    // First two probes fail, third succeeds.
    fetchMock
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce({ ok: true, status: 200 });

    const { result } = renderHook(() => useBackendHealth(), { wrapper });

    // First probe.
    await act(async () => { await Promise.resolve(); });

    // Second probe.
    await act(async () => {
      jest.advanceTimersByTime(3_000);
      await Promise.resolve();
    });
    expect(result.current.backendOffline).toBe(true);

    // Third probe — succeeds.
    await act(async () => {
      jest.advanceTimersByTime(5_000);
      await Promise.resolve();
    });
    expect(result.current.backendOffline).toBe(false);
    expect(result.current.consecutiveFailures).toBe(0);
  });

  it('reportSuccess resets offline state immediately', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    const { result } = renderHook(() => useBackendHealth(), { wrapper });

    // Drive to offline.
    await act(async () => { await Promise.resolve(); });
    await act(async () => {
      jest.advanceTimersByTime(3_000);
      await Promise.resolve();
    });
    expect(result.current.backendOffline).toBe(true);

    // External hook reports success.
    act(() => { result.current.reportSuccess(); });
    expect(result.current.backendOffline).toBe(false);
  });

  it('treats 401/403 responses as reachable (not offline)', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 401 });

    const { result } = renderHook(() => useBackendHealth(), { wrapper });

    await act(async () => { await Promise.resolve(); });
    expect(result.current.backendOffline).toBe(false);
    expect(result.current.consecutiveFailures).toBe(0);
  });
});

// ── useApiData backoff integration ──

describe('useApiData with BackendHealthContext', () => {
  function TestDataComponent({ endpoint }: { endpoint: string }) {
    const result = useApiData(endpoint, { pollingInterval: 5000 });
    return (
      <div>
        <div data-testid="offline">{result.backendOffline ? 'yes' : 'no'}</div>
        <div data-testid="data">{JSON.stringify(result.data)}</div>
        <div data-testid="error">{result.error?.message || 'none'}</div>
      </div>
    );
  }

  it('exposes backendOffline=false when backend is healthy', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ value: 42 }),
      headers: new Headers(),
    });

    render(
      <BackendHealthProvider>
        <TestDataComponent endpoint="/api/v1/test" />
      </BackendHealthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('offline')).toHaveTextContent('no');
    });
  });

  it('exposes backendOffline=true when backend is unreachable', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    render(
      <BackendHealthProvider>
        <TestDataComponent endpoint="/api/v1/test" />
      </BackendHealthProvider>
    );

    // Allow probes to fail enough times.
    await act(async () => { await Promise.resolve(); });
    await act(async () => {
      jest.advanceTimersByTime(3_000);
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.getByTestId('offline')).toHaveTextContent('yes');
    });
  });
});

// ── BackendOfflineBanner tests ──

describe('BackendOfflineBanner', () => {
  it('renders nothing when backend is healthy', async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200 });

    const { container } = render(
      <BackendHealthProvider>
        <BackendOfflineBanner />
      </BackendHealthProvider>
    );

    await act(async () => { await Promise.resolve(); });
    expect(container.innerHTML).toBe('');
  });

  it('shows banner with retry button when offline', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    render(
      <BackendHealthProvider>
        <BackendOfflineBanner />
      </BackendHealthProvider>
    );

    // Drive to offline.
    await act(async () => { await Promise.resolve(); });
    await act(async () => {
      jest.advanceTimersByTime(3_000);
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.getByText(/Backend unavailable/)).toBeInTheDocument();
    });
    expect(screen.getByText(/Retry Now/)).toBeInTheDocument();
  });

  it('shows failure count', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    render(
      <BackendHealthProvider>
        <BackendOfflineBanner />
      </BackendHealthProvider>
    );

    await act(async () => { await Promise.resolve(); });
    await act(async () => {
      jest.advanceTimersByTime(3_000);
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.getByText(/2 failed attempts/)).toBeInTheDocument();
    });
  });

  it('disappears when backend recovers', async () => {
    fetchMock
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValue({ ok: true, status: 200 });

    const { container } = render(
      <BackendHealthProvider>
        <BackendOfflineBanner />
      </BackendHealthProvider>
    );

    // Go offline.
    await act(async () => { await Promise.resolve(); });
    await act(async () => {
      jest.advanceTimersByTime(3_000);
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(screen.getByText(/Backend unavailable/)).toBeInTheDocument();
    });

    // Recover.
    await act(async () => {
      jest.advanceTimersByTime(5_000);
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(container.querySelector('[class*="bg-amber"]')).toBeNull();
    });
  });
});

// ── useKalshiRiskStream offline flag ──

describe('useKalshiRiskStream backendOffline flag', () => {
  it('exposes backendOffline from context', async () => {
    // We test that the hook's return type includes the flag.
    // The actual WS behavior is covered by existing tests;
    // here we verify the flag propagation.
    const { useKalshiRiskStream } = await import('../useKalshiRiskStream');

    fetchMock.mockResolvedValue({ ok: true, status: 200 });

    const { result } = renderHook(() => useKalshiRiskStream(), { wrapper });

    expect(result.current.backendOffline).toBe(false);
    expect(typeof result.current.backendOffline).toBe('boolean');
  });
});
