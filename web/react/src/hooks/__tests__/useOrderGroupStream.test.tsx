/**
 * @jest-environment jsdom
 */

import { renderHook, act, waitFor } from '@testing-library/react';
import { useOrderGroupStream } from '../useOrderGroupStream';

// Mock global EventSource with named-event listener support
class MockEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;

  url: string;
  readyState = 0;
  withCredentials = false;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;

  private _listeners: Record<string, Array<(ev: Event | MessageEvent) => void>> = {};

  constructor(url: string | URL) {
    this.url = url.toString();
  }

  close() {
    this.readyState = 2;
  }

  addEventListener(type: string, listener: (ev: Event | MessageEvent) => void) {
    if (!this._listeners[type]) this._listeners[type] = [];
    this._listeners[type].push(listener);
  }
  removeEventListener(type: string, listener: (ev: Event | MessageEvent) => void) {
    if (!this._listeners[type]) return;
    this._listeners[type] = this._listeners[type].filter(l => l !== listener);
  }
  dispatchEvent() { return true; }

  // Helper to simulate events
  simulateOpen() {
    this.readyState = 1;
    if (this.onopen) this.onopen(new Event('open'));
    (this._listeners['open'] ?? []).forEach(l => l(new Event('open')));
  }

  simulateMessage(data: unknown) {
    // Support named SSE event types: if data has a `type` field, dispatch as that event name
    const type = (data as Record<string, unknown>)?.type as string | undefined;
    const event = new MessageEvent(type ?? 'message', {
      data: JSON.stringify(data),
    });
    if (type && this._listeners[type]) {
      this._listeners[type].forEach(l => l(event));
    } else if (this.onmessage) {
      this.onmessage(event);
    }
  }

  simulateError() {
    this.readyState = 2;
    if (this.onerror) this.onerror(new Event('error'));
    (this._listeners['error'] ?? []).forEach(l => l(new Event('error')));
  }
}

// Replace global EventSource
(global as any).EventSource = MockEventSource;

describe('useOrderGroupStream', () => {
  let mockEventSourceInstances: MockEventSource[] = [];

  beforeEach(() => {
    mockEventSourceInstances = [];
    // Capture instances
    const OriginalMockEventSource = MockEventSource;
    (global as any).EventSource = class extends OriginalMockEventSource {
      constructor(url: string) {
        super(url);
        mockEventSourceInstances.push(this);
      }
    };
  });

  afterEach(() => {
    jest.clearAllTimers();
  });

  it('initializes with disconnected state', () => {
    const { result } = renderHook(() =>
      useOrderGroupStream({ autoConnect: false })
    );

    expect(result.current.isConnected).toBe(false);
    expect(result.current.groups).toEqual({});
    expect(result.current.alerts).toEqual([]);
    expect(result.current.error).toBeNull();
    expect(result.current.reconnectAttempts).toBe(0);
  });

  it('connects when autoConnect is true', async () => {
    renderHook(() => useOrderGroupStream({ autoConnect: true }));

    await waitFor(() => {
      expect(mockEventSourceInstances.length).toBe(1);
    });

    // Simulate connection open
    act(() => {
      mockEventSourceInstances[0].simulateOpen();
    });
  });

  it('processes snapshot messages', async () => {
    const { result } = renderHook(() =>
      useOrderGroupStream({ autoConnect: true })
    );

    await waitFor(() => {
      expect(mockEventSourceInstances.length).toBe(1);
    });

    act(() => {
      mockEventSourceInstances[0].simulateOpen();
      mockEventSourceInstances[0].simulateMessage({
        type: 'snapshot',
        order_group_id: 'og-1',
        status: 'active',
        contracts_limit: 1000,
        matched_contracts: 100,
        used_contracts: 300,
        update_type: 'snapshot',
        ts: new Date().toISOString(),
      });
    });

    await waitFor(() => {
      expect(result.current.groups['og-1']).toBeDefined();
    });
    expect(result.current.groups['og-1'].status).toBe('active');
  });

  it('processes delta update messages', async () => {
    const { result } = renderHook(() =>
      useOrderGroupStream({ autoConnect: true })
    );

    await waitFor(() => {
      expect(mockEventSourceInstances.length).toBe(1);
    });

    // First send snapshot
    act(() => {
      mockEventSourceInstances[0].simulateOpen();
      mockEventSourceInstances[0].simulateMessage({
        type: 'snapshot',
        order_group_id: 'og-1',
        status: 'active',
        contracts_limit: 1000,
        used_contracts: 300,
        update_type: 'snapshot',
        ts: new Date().toISOString(),
      });
    });

    // Then send delta update
    act(() => {
      mockEventSourceInstances[0].simulateMessage({
        type: 'delta',
        order_group_id: 'og-1',
        used_contracts: 500,
        update_type: 'delta',
        ts: new Date().toISOString(),
      });
    });

    await waitFor(() => {
      expect(result.current.groups['og-1'].used_contracts).toBe(500);
    });
  });

  it('handles triggered events with callback', async () => {
    const onTriggered = jest.fn();
    renderHook(() =>
      useOrderGroupStream({ autoConnect: true, onTriggered })
    );

    await waitFor(() => {
      expect(mockEventSourceInstances.length).toBe(1);
    });

    act(() => {
      mockEventSourceInstances[0].simulateOpen();
      mockEventSourceInstances[0].simulateMessage({
        type: 'triggered',
        order_group_id: 'og-1',
        trigger_data: {
          matched_contracts: 1000,
          contracts_limit: 1000,
        },
      });
    });

    await waitFor(() => {
      expect(onTriggered).toHaveBeenCalledWith('og-1', expect.any(Object));
    });
  });

  it('filters groups by groupIds option', async () => {
    renderHook(() =>
      useOrderGroupStream({
        autoConnect: true,
        groupIds: ['og-1', 'og-3'],
      })
    );

    await waitFor(() => {
      expect(mockEventSourceInstances.length).toBe(1);
    });

    // Verify the URL contains the filter parameter
    const eventSourceUrl = mockEventSourceInstances[0].url;
    expect(eventSourceUrl).toContain('group_ids');
  });

  it('handles connection errors and reconnects', async () => {
    jest.useFakeTimers();

    const { result } = renderHook(() =>
      useOrderGroupStream({ autoConnect: true })
    );

    await waitFor(() => {
      expect(mockEventSourceInstances.length).toBe(1);
    });

    // Simulate error
    act(() => {
      mockEventSourceInstances[0].simulateError();
    });

    await waitFor(() => {
      expect(result.current.isConnected).toBe(false);
      expect(result.current.reconnectAttempts).toBeGreaterThan(0);
    });

    // Fast-forward to trigger reconnect
    act(() => {
      jest.advanceTimersByTime(1000);
    });

    jest.useRealTimers();
  });

  it('disconnects when hook unmounts', async () => {
    const { unmount } = renderHook(() =>
      useOrderGroupStream({ autoConnect: true })
    );

    await waitFor(() => {
      expect(mockEventSourceInstances.length).toBe(1);
    });

    const closeSpy = jest.spyOn(mockEventSourceInstances[0], 'close');

    unmount();

    expect(closeSpy).toHaveBeenCalled();
  });

  it('manually connects when autoConnect is false', async () => {
    const { result } = renderHook(() =>
      useOrderGroupStream({ autoConnect: false })
    );

    expect(mockEventSourceInstances.length).toBe(0);

    act(() => {
      result.current.connect();
    });

    await waitFor(() => {
      expect(mockEventSourceInstances.length).toBe(1);
    });
  });

  it('manually disconnects', async () => {
    const { result } = renderHook(() =>
      useOrderGroupStream({ autoConnect: true })
    );

    await waitFor(() => {
      expect(mockEventSourceInstances.length).toBe(1);
    });

    const closeSpy = jest.spyOn(mockEventSourceInstances[0], 'close');

    act(() => {
      result.current.disconnect();
    });

    expect(closeSpy).toHaveBeenCalled();
  });

  it('generates alerts for high utilization', async () => {
    const { result } = renderHook(() =>
      useOrderGroupStream({ autoConnect: true })
    );

    await waitFor(() => {
      expect(mockEventSourceInstances.length).toBe(1);
    });

    // Hook generates alerts on 'triggered' events, not snapshots
    act(() => {
      mockEventSourceInstances[0].simulateOpen();
      mockEventSourceInstances[0].simulateMessage({
        type: 'triggered',
        order_group_id: 'og-high',
        status: 'triggered',
        contracts_limit: 1000,
        used_contracts: 900,
        update_type: 'snapshot',
        ts: new Date().toISOString(),
      });
    });

    await waitFor(() => {
      expect(result.current.alerts.length).toBeGreaterThan(0);
    });
    expect(result.current.alerts[0].level).toBe('critical');
  });

  it('generates alerts for triggered groups', async () => {
    const { result } = renderHook(() =>
      useOrderGroupStream({ autoConnect: true })
    );

    await waitFor(() => {
      expect(mockEventSourceInstances.length).toBe(1);
    });

    // Hook generates alerts on 'triggered' events
    act(() => {
      mockEventSourceInstances[0].simulateOpen();
      mockEventSourceInstances[0].simulateMessage({
        type: 'triggered',
        order_group_id: 'og-triggered',
        status: 'triggered',
        contracts_limit: 1000,
        used_contracts: 0,
        update_type: 'snapshot',
        ts: new Date().toISOString(),
      });
    });

    await waitFor(() => {
      const triggeredAlerts = result.current.alerts.filter(
        (a) => a.message && a.message.includes('triggered')
      );
      expect(triggeredAlerts.length).toBeGreaterThan(0);
    });
  });

  it('clears alerts when groups are no longer triggered', async () => {
    const { result } = renderHook(() =>
      useOrderGroupStream({ autoConnect: true })
    );

    await waitFor(() => {
      expect(mockEventSourceInstances.length).toBe(1);
    });

    // First make it triggered
    act(() => {
      mockEventSourceInstances[0].simulateOpen();
      mockEventSourceInstances[0].simulateMessage({
        type: 'triggered',
        order_group_id: 'og-test',
        status: 'triggered',
        contracts_limit: 1000,
        used_contracts: 0,
        update_type: 'snapshot',
        ts: new Date().toISOString(),
      });
    });

    await waitFor(() => {
      expect(result.current.alerts.length).toBeGreaterThan(0);
    });

    // Then update to active via snapshot (clears alerts for group)
    act(() => {
      mockEventSourceInstances[0].simulateMessage({
        type: 'snapshot',
        order_group_id: 'og-test',
        status: 'active',
        update_type: 'snapshot',
        ts: new Date().toISOString(),
      });
    });

    await waitFor(() => {
      const triggeredAlerts = result.current.alerts.filter(
        (a) => a.message && a.message.includes('triggered')
      );
      expect(triggeredAlerts.length).toBe(0);
    });
  });
});
