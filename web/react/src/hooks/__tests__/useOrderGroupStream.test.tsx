/**
 * @jest-environment jsdom
 */

import { renderHook, act, waitFor } from '@testing-library/react';
import { useOrderGroupStream } from '../useOrderGroupStream';

// Mock global EventSource
class MockEventSource implements EventSource {
  static CONNECTING = 0 as const;
  static OPEN = 1 as const;
  static CLOSED = 2 as const;

  url: string;
  readyState = 0;
  withCredentials = false;
  onopen: ((this: EventSource, ev: Event) => any) | null = null;
  onmessage: ((this: EventSource, ev: MessageEvent) => any) | null = null;
  onerror: ((this: EventSource, ev: Event) => any) | null = null;

  constructor(url: string | URL, _eventSourceInitDict?: EventSourceInit) {
    this.url = url.toString();
  }

  close() {
    this.readyState = 2;
  }

  addEventListener(_type: string, _listener: EventListenerOrEventListenerObject, _options?: boolean | AddEventListenerOptions): void {}
  removeEventListener(_type: string, _listener: EventListenerOrEventListenerObject, _options?: boolean | EventListenerOptions): void {}
  dispatchEvent(_event: Event): boolean { return true; }

  // Helper to simulate events
  simulateOpen() {
    this.readyState = 1;
    if (this.onopen) {
      this.onopen(new Event('open'));
    }
  }

  simulateMessage(data: unknown) {
    if (this.onmessage) {
      const event = new MessageEvent('message', {
        data: JSON.stringify(data),
      });
      this.onmessage(event);
    }
  }

  simulateError() {
    this.readyState = 2;
    if (this.onerror) {
      this.onerror(new Event('error'));
    }
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

    const snapshotData = {
      type: 'snapshot',
      groups: {
        'og-1': {
          order_group_id: 'og-1',
          status: 'active',
          contracts_limit: 1000,
          matched_contracts: 100,
          used_contracts: 300,
          remaining_contracts: 700,
          utilization_pct: 30,
        },
      },
      timestamp: Date.now(),
    };

    act(() => {
      mockEventSourceInstances[0].simulateOpen();
      mockEventSourceInstances[0].simulateMessage(snapshotData);
    });

    await waitFor(() => {
      expect(result.current.groups['og-1']).toBeDefined();
      expect(result.current.groups['og-1'].status).toBe('active');
    });
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
        groups: {
          'og-1': {
            order_group_id: 'og-1',
            status: 'active',
            contracts_limit: 1000,
            used_contracts: 300,
          },
        },
      });
    });

    // Then send delta update
    act(() => {
      mockEventSourceInstances[0].simulateMessage({
        type: 'delta',
        group: {
          order_group_id: 'og-1',
          used_contracts: 500,
          utilization_pct: 50,
        },
      });
    });

    await waitFor(() => {
      expect(result.current.groups['og-1'].used_contracts).toBe(500);
    });
  });

  it('handles triggered events with callback', async () => {
    const onTriggered = jest.fn();
    const { result } = renderHook(() =>
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
    const { result } = renderHook(() =>
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

    act(() => {
      mockEventSourceInstances[0].simulateOpen();
      mockEventSourceInstances[0].simulateMessage({
        type: 'snapshot',
        groups: {
          'og-high': {
            order_group_id: 'og-high',
            status: 'active',
            contracts_limit: 1000,
            used_contracts: 900,
            utilization_pct: 90,
          },
        },
      });
    });

    await waitFor(() => {
      expect(result.current.alerts.length).toBeGreaterThan(0);
      expect(result.current.alerts[0].level).toBe('critical');
    });
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
      mockEventSourceInstances[0].simulateMessage({
        type: 'snapshot',
        groups: {
          'og-triggered': {
            order_group_id: 'og-triggered',
            status: 'triggered',
            contracts_limit: 1000,
            used_contracts: 0,
            utilization_pct: 100,
          },
        },
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
        type: 'snapshot',
        groups: {
          'og-test': {
            order_group_id: 'og-test',
            status: 'triggered',
            contracts_limit: 1000,
            used_contracts: 0,
          },
        },
      });
    });

    await waitFor(() => {
      expect(result.current.alerts.length).toBeGreaterThan(0);
    });

    // Then update to active
    act(() => {
      mockEventSourceInstances[0].simulateMessage({
        type: 'delta',
        group: {
          order_group_id: 'og-test',
          status: 'active',
        },
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
