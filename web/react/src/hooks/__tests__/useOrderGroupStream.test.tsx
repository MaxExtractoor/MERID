/**
 * @jest-environment jsdom
 */

import { renderHook, act, waitFor } from '@testing-library/react';
import { useOrderGroupStream } from '../useOrderGroupStream';

// Mock global EventSource
class MockEventSource {
  static CONNECTING = 0 as const;
  static OPEN = 1 as const;
  static CLOSED = 2 as const;

  readonly CONNECTING = MockEventSource.CONNECTING;
  readonly OPEN = MockEventSource.OPEN;
  readonly CLOSED = MockEventSource.CLOSED;
  url: string;
  readyState = 0;
  withCredentials = false;
  onopen: ((ev: Event) => any) | null = null;
  onmessage: ((ev: MessageEvent) => any) | null = null;
  onerror: ((ev: Event) => any) | null = null;
  private listeners: Record<string, Array<(ev: Event | MessageEvent) => any>> = {};

  constructor(url: string | URL, eventSourceInitDict?: EventSourceInit) {
    this.url = url.toString();
    void eventSourceInitDict;
  }

  close() {
    this.readyState = 2;
  }

  addEventListener(
    type: string,
    listener: EventListenerOrEventListenerObject,
    _options?: boolean | AddEventListenerOptions,
  ): void;
  addEventListener(type?: string, listener?: EventListenerOrEventListenerObject): void {
    if (!type || !listener || typeof listener !== 'function') {
      return;
    }
    this.listeners[type] = [...(this.listeners[type] ?? []), listener];
  }
  removeEventListener(
    type: string,
    listener: EventListenerOrEventListenerObject,
    _options?: boolean | EventListenerOptions,
  ): void;
  removeEventListener(type?: string, listener?: EventListenerOrEventListenerObject): void {
    if (!type || !listener || typeof listener !== 'function') {
      return;
    }
    this.listeners[type] = (this.listeners[type] ?? []).filter((registered) => registered !== listener);
  }
  dispatchEvent(event: Event): boolean {
    void event;
    return true;
  }

  // Helper to simulate events
  simulateOpen() {
    this.readyState = 1;
    if (this.onopen) {
      this.onopen(new Event('open'));
    }
  }

  simulateEvent(type: string, data: unknown) {
    const event = new MessageEvent(type, {
        data: JSON.stringify(data),
    });
    const listeners = this.listeners[type] ?? [];
    listeners.forEach((listener) => {
      listener(event);
    });
  }

  simulateError() {
    this.readyState = 2;
    if (this.onerror) {
      this.onerror(new Event('error'));
    }
    const listeners = this.listeners.error ?? [];
    listeners.forEach((listener) => {
      listener(new Event('error'));
    });
  }
}

// Replace global EventSource
(global as any).EventSource = MockEventSource as unknown as typeof EventSource;

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

    const snapshotData = {
      order_group_id: 'og-1',
      status: 'active',
      contracts_limit: 1000,
      matched_contracts: 100,
      used_contracts: 300,
      update_type: 'snapshot',
      ts: '2026-04-04T18:00:00Z',
    };

    act(() => {
      mockEventSourceInstances[0].simulateOpen();
      mockEventSourceInstances[0].simulateEvent('snapshot', snapshotData);
    });

    await waitFor(() => expect(result.current.groups['og-1']).toBeDefined());
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
      mockEventSourceInstances[0].simulateEvent('snapshot', {
        order_group_id: 'og-1',
        status: 'active',
        contracts_limit: 1000,
        used_contracts: 300,
        update_type: 'snapshot',
        ts: '2026-04-04T18:00:00Z',
      });
    });

    // Then send delta update
    act(() => {
      mockEventSourceInstances[0].simulateEvent('delta', {
        order_group_id: 'og-1',
        used_contracts: 500,
        update_type: 'delta',
        ts: '2026-04-04T18:01:00Z',
      });
    });

    await waitFor(() => expect(result.current.groups['og-1'].used_contracts).toBe(500));
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
      mockEventSourceInstances[0].simulateEvent('triggered', {
        order_group_id: 'og-1',
        status: 'triggered',
        matched_contracts: 1000,
        contracts_limit: 1000,
        update_type: 'delta',
        ts: '2026-04-04T18:02:00Z',
      });
    });

    await waitFor(() => expect(onTriggered).toHaveBeenCalledWith('og-1', expect.any(Object)));
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

    await waitFor(() => expect(result.current.isConnected).toBe(false));
    await waitFor(() => expect(result.current.reconnectAttempts).toBeGreaterThan(0));

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

    act(() => {
      mockEventSourceInstances[0].simulateOpen();
      mockEventSourceInstances[0].simulateEvent('triggered', {
        order_group_id: 'og-high',
        status: 'triggered',
        contracts_limit: 1000,
        used_contracts: 900,
        matched_contracts: 900,
        update_type: 'delta',
        ts: '2026-04-04T18:03:00Z',
      });
    });

    await waitFor(() => expect(result.current.alerts.length).toBeGreaterThan(0));
    expect(result.current.alerts[0].level).toBe('critical');
  });

  it('generates alerts for triggered groups', async () => {
    const { result } = renderHook(() =>
      useOrderGroupStream({ autoConnect: true })
    );

    await waitFor(() => {
      expect(mockEventSourceInstances.length).toBe(1);
    });

    act(() => {
      mockEventSourceInstances[0].simulateOpen();
      mockEventSourceInstances[0].simulateEvent('triggered', {
        order_group_id: 'og-triggered',
        status: 'triggered',
        contracts_limit: 1000,
        used_contracts: 0,
        matched_contracts: 1000,
        update_type: 'delta',
        ts: '2026-04-04T18:04:00Z',
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
      mockEventSourceInstances[0].simulateEvent('triggered', {
        order_group_id: 'og-test',
        status: 'triggered',
        contracts_limit: 1000,
        used_contracts: 0,
        matched_contracts: 1000,
        update_type: 'delta',
        ts: '2026-04-04T18:05:00Z',
      });
    });

    await waitFor(() => {
      expect(result.current.alerts.length).toBeGreaterThan(0);
    });

    // Then update to active
    act(() => {
      mockEventSourceInstances[0].simulateEvent('snapshot', {
        order_group_id: 'og-test',
        status: 'active',
        contracts_limit: 1000,
        used_contracts: 0,
        update_type: 'snapshot',
        ts: '2026-04-04T18:06:00Z',
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
