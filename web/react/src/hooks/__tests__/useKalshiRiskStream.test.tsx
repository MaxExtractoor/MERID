/**
 * Tests for useKalshiRiskStream — Live WS risk alert stream hook.
 */

import { renderHook, act, waitFor } from '@testing-library/react';
import { useKalshiRiskStream } from '../useKalshiRiskStream';

// Capture WS instances created by the global mock from setupTests
let capturedWs: any = null;
const OriginalWS = global.WebSocket;

beforeEach(() => {
  capturedWs = null;
  // Wrap the global mock to capture instances
  (global as any).WebSocket = function(url: string) {
    const ws = new OriginalWS(url);
    capturedWs = ws;
    return ws;
  };
  (global as any).WebSocket.OPEN = 1;
  (global as any).WebSocket.CLOSED = 3;
});

afterEach(() => {
  (global as any).WebSocket = OriginalWS;
});

describe('useKalshiRiskStream', () => {
  it('starts disconnected', () => {
    const { result } = renderHook(() => useKalshiRiskStream());
    expect(result.current.connected).toBe(false);
    expect(result.current.alerts).toEqual([]);
    expect(result.current.summary).toBeNull();
  });

  it('connects to WS endpoint', async () => {
    const { result } = renderHook(() => useKalshiRiskStream());

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 10));
    });

    expect(result.current.connected).toBe(true);
    expect(capturedWs).not.toBeNull();
  });

  it('processes risk_summary messages', async () => {
    const { result } = renderHook(() => useKalshiRiskStream());

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 10));
    });

    act(() => {
      capturedWs?.onmessage?.(new MessageEvent('message', {
        data: JSON.stringify({
          event_type: 'risk_summary',
          timestamp: 1708070400,
          total_equity: 1000.50,
          total_pnl: 25.30,
          unrealized_pnl: 10.00,
          position_count: 3,
          exposure: 150.00,
        }),
      }));
    });

    await waitFor(() => {
      expect(result.current.summary).not.toBeNull();
    });

    expect(result.current.summary?.total_equity).toBe(1000.50);
    expect(result.current.summary?.total_pnl).toBe(25.30);
    expect(result.current.summary?.position_count).toBe(3);
  });

  it('accumulates risk_alert messages', async () => {
    const { result } = renderHook(() => useKalshiRiskStream());

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 10));
    });

    act(() => {
      capturedWs?.onmessage?.(new MessageEvent('message', {
        data: JSON.stringify({
          event_type: 'risk_alert',
          timestamp: 1708070400,
          status: 'critical',
          signal: 'drawdown',
          reasoning: 'Drawdown at 12%',
          extra: { event_id: 'dd-critical', detail: 'Halt at 15%', category: 'drawdown' },
        }),
      }));
    });

    await waitFor(() => {
      expect(result.current.alerts.length).toBe(1);
    });

    expect(result.current.alerts[0].id).toBe('dd-critical');
    expect(result.current.alerts[0].severity).toBe('critical');
    expect(result.current.alerts[0].category).toBe('drawdown');
    expect(result.current.alerts[0].source).toBe('ws');
  });

  it('deduplicates alerts by id', async () => {
    const { result } = renderHook(() => useKalshiRiskStream());

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 10));
    });

    const alertMsg = JSON.stringify({
      event_type: 'risk_alert',
      timestamp: 1708070400,
      status: 'warning',
      signal: 'rate_limit',
      reasoning: 'Rate limit approaching',
      extra: { event_id: 'rate-warning', category: 'rate_limit' },
    });

    act(() => {
      capturedWs?.onmessage?.(new MessageEvent('message', { data: alertMsg }));
      capturedWs?.onmessage?.(new MessageEvent('message', { data: alertMsg }));
    });

    await waitFor(() => {
      expect(result.current.alerts.length).toBe(1);
    });
  });

  it('ignores heartbeat messages', async () => {
    const { result } = renderHook(() => useKalshiRiskStream());

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 10));
    });

    act(() => {
      capturedWs?.onmessage?.(new MessageEvent('message', {
        data: JSON.stringify({ event_type: 'heartbeat', timestamp: 123 }),
      }));
    });

    expect(result.current.alerts).toEqual([]);
    expect(result.current.summary).toBeNull();
  });

  it('handles malformed JSON gracefully', async () => {
    const { result } = renderHook(() => useKalshiRiskStream());

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 10));
    });

    act(() => {
      capturedWs?.onmessage?.(new MessageEvent('message', { data: 'not valid json' }));
    });

    expect(result.current.connected).toBe(true);
    expect(result.current.alerts).toEqual([]);
  });

  it('clearAlerts empties the alerts buffer', async () => {
    const { result } = renderHook(() => useKalshiRiskStream());

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 10));
    });

    act(() => {
      capturedWs?.onmessage?.(new MessageEvent('message', {
        data: JSON.stringify({
          event_type: 'risk_alert',
          timestamp: 1708070400,
          status: 'warning',
          signal: 'test',
          reasoning: 'Test alert',
          extra: { event_id: 'test-1', category: 'general' },
        }),
      }));
    });

    await waitFor(() => {
      expect(result.current.alerts.length).toBe(1);
    });

    act(() => {
      result.current.clearAlerts();
    });

    expect(result.current.alerts).toEqual([]);
  });
});
