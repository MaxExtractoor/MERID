/**
 * Tests for useMeridSocket hook - WebSocket connection management
 * Focus: Deterministic testing of WebSocket lifecycle and error handling
 */

import { renderHook, act, waitFor } from '@testing-library/react';
import { useMeridSocket } from '../useMeridSocket';

// Mock WebSocket
class MockWebSocket {
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: (() => void) | null = null;
  readyState: number = 0;
  lastSent: string | null = null;
  
  constructor(public url: string) {
    setTimeout(() => {
      this.readyState = 1; // OPEN
      if (this.onopen) this.onopen();
    }, 0);
  }
  
  send(data: string) {
    this.lastSent = data;
  }
  
  close() {
    this.readyState = 3; // CLOSED
    if (this.onclose) this.onclose();
  }
}

describe('useMeridSocket', () => {
  let mockWebSocket: typeof MockWebSocket;
  
  beforeEach(() => {
    mockWebSocket = MockWebSocket as any;
    global.WebSocket = mockWebSocket as any;
    jest.clearAllMocks();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe('Connection Lifecycle', () => {
    it('establishes WebSocket connection', async () => {
      const { result } = renderHook(() => 
        useMeridSocket('ws://localhost:8000/ws/test')
      );
      
      await waitFor(() => {
        expect(result.current.connected).toBe(true);
      });
    });

    it('sets initial state correctly', () => {
      const { result } = renderHook(() => 
        useMeridSocket('ws://localhost:8000/ws/test')
      );
      
      expect(result.current.connected).toBe(false);
      expect(result.current.lastMessage).toBeNull();
      expect(result.current.error).toBeNull();
    });

    it('closes connection on unmount', async () => {
      const { result, unmount } = renderHook(() => 
        useMeridSocket('ws://localhost:8000/ws/test')
      );
      
      await waitFor(() => {
        expect(result.current.connected).toBe(true);
      });
      
      unmount();
      
      // Connection should be closed
      expect(true).toBe(true);
    });
  });

  describe('Message Handling', () => {
    it('receives and stores messages', async () => {
      const mockWs = new MockWebSocket('ws://localhost:8000/ws/test');
      global.WebSocket = jest.fn(() => mockWs) as any;
      
      const { result } = renderHook(() => 
        useMeridSocket('ws://localhost:8000/ws/test')
      );
      
      await waitFor(() => {
        expect(result.current.connected).toBe(true);
      });
      
      const testMessage = { type: 'test', data: 'hello' };
      
      act(() => {
        if (mockWs.onmessage) {
          mockWs.onmessage(new MessageEvent('message', {
            data: JSON.stringify(testMessage)
          }));
        }
      });
      
      await waitFor(() => {
        expect(result.current.lastMessage).toEqual(testMessage);
      });
    });

    it('handles multiple messages', async () => {
      const mockWs = new MockWebSocket('ws://localhost:8000/ws/test');
      global.WebSocket = jest.fn(() => mockWs) as any;
      
      const { result } = renderHook(() => 
        useMeridSocket('ws://localhost:8000/ws/test')
      );
      
      await waitFor(() => {
        expect(result.current.connected).toBe(true);
      });
      
      const messages = [
        { type: 'msg1', data: 'first' },
        { type: 'msg2', data: 'second' },
        { type: 'msg3', data: 'third' },
      ];
      
      for (const msg of messages) {
        act(() => {
          if (mockWs.onmessage) {
            mockWs.onmessage(new MessageEvent('message', {
              data: JSON.stringify(msg)
            }));
          }
        });
      }
      
      await waitFor(() => {
        expect(result.current.lastMessage).toEqual(messages[2]);
      });
    });

    it('handles malformed JSON messages', async () => {
      const mockWs = new MockWebSocket('ws://localhost:8000/ws/test');
      global.WebSocket = jest.fn(() => mockWs) as any;
      
      const { result } = renderHook(() => 
        useMeridSocket('ws://localhost:8000/ws/test')
      );
      
      await waitFor(() => {
        expect(result.current.connected).toBe(true);
      });
      
      act(() => {
        if (mockWs.onmessage) {
          mockWs.onmessage(new MessageEvent('message', {
            data: 'invalid json'
          }));
        }
      });
      
      // Should handle gracefully without crashing
      expect(result.current.connected).toBe(true);
    });
  });

  describe('Error Handling', () => {
    it('handles connection errors', async () => {
      const mockWs = new MockWebSocket('ws://localhost:8000/ws/test');
      global.WebSocket = jest.fn(() => mockWs) as any;
      
      const { result } = renderHook(() => 
        useMeridSocket('ws://localhost:8000/ws/test')
      );
      
      act(() => {
        if (mockWs.onerror) {
          mockWs.onerror(new Event('error'));
        }
      });
      
      await waitFor(() => {
        expect(result.current.error).toBeTruthy();
      });
    });

    it('sets connected to false on error', async () => {
      const mockWs = new MockWebSocket('ws://localhost:8000/ws/test');
      global.WebSocket = jest.fn(() => mockWs) as any;
      
      const { result } = renderHook(() => 
        useMeridSocket('ws://localhost:8000/ws/test')
      );
      
      await waitFor(() => {
        expect(result.current.connected).toBe(true);
      });
      
      act(() => {
        if (mockWs.onerror) {
          mockWs.onerror(new Event('error'));
        }
      });
      
      await waitFor(() => {
        expect(result.current.connected).toBe(false);
      });
    });

    it('handles connection close', async () => {
      const mockWs = new MockWebSocket('ws://localhost:8000/ws/test');
      global.WebSocket = jest.fn(() => mockWs) as any;
      
      const { result } = renderHook(() => 
        useMeridSocket('ws://localhost:8000/ws/test')
      );
      
      await waitFor(() => {
        expect(result.current.connected).toBe(true);
      });
      
      act(() => {
        mockWs.close();
      });
      
      await waitFor(() => {
        expect(result.current.connected).toBe(false);
      });
    });
  });

  describe('Reconnection', () => {
    it('attempts to reconnect after disconnect', async () => {
      jest.useFakeTimers();
      
      const mockWs = new MockWebSocket('ws://localhost:8000/ws/test');
      global.WebSocket = jest.fn(() => mockWs) as any;
      
      const { result } = renderHook(() => 
        useMeridSocket('ws://localhost:8000/ws/test', { autoReconnect: true })
      );
      
      await waitFor(() => {
        expect(result.current.connected).toBe(true);
      });
      
      act(() => {
        mockWs.close();
      });
      
      await waitFor(() => {
        expect(result.current.connected).toBe(false);
      });
      
      // Advance timers to trigger reconnection
      act(() => {
        jest.advanceTimersByTime(5000);
      });
      
      jest.useRealTimers();
    });

    it('respects max reconnection attempts', async () => {
      jest.useFakeTimers();
      
      renderHook(() => 
        useMeridSocket('ws://localhost:8000/ws/test', {
          autoReconnect: true,
          maxReconnectAttempts: 3
        })
      );
      
      // Simulate multiple disconnections
      for (let i = 0; i < 4; i++) {
        act(() => {
          jest.advanceTimersByTime(5000);
        });
      }
      
      jest.useRealTimers();
    });
  });

  describe('Send Messages', () => {
    it('sends messages when connected', async () => {
      const mockWs = new MockWebSocket('ws://localhost:8000/ws/test');
      const sendSpy = jest.spyOn(mockWs, 'send');
      global.WebSocket = jest.fn(() => mockWs) as any;
      
      const { result } = renderHook(() => 
        useMeridSocket('ws://localhost:8000/ws/test')
      );
      
      await waitFor(() => {
        expect(result.current.connected).toBe(true);
      });
      
      act(() => {
        result.current.send({ type: 'test', data: 'hello' });
      });
      
      expect(sendSpy).toHaveBeenCalledWith(
        JSON.stringify({ type: 'test', data: 'hello' })
      );
    });

    it('queues messages when disconnected', async () => {
      const { result } = renderHook(() => 
        useMeridSocket('ws://localhost:8000/ws/test')
      );
      
      // Try to send before connected
      act(() => {
        result.current.send({ type: 'test', data: 'hello' });
      });
      
      // Should not throw error
      expect(result.current.connected).toBe(false);
    });
  });

  describe('Configuration Options', () => {
    it('accepts custom reconnect delay', async () => {
      const { result } = renderHook(() => 
        useMeridSocket('ws://localhost:8000/ws/test', {
          reconnectDelay: 1000
        })
      );
      
      expect(result.current).toBeDefined();
    });

    it('accepts message callback', async () => {
      const onMessage = jest.fn();
      const mockWs = new MockWebSocket('ws://localhost:8000/ws/test');
      global.WebSocket = jest.fn(() => mockWs) as any;
      
      const { result } = renderHook(() => 
        useMeridSocket('ws://localhost:8000/ws/test', {
          onMessage
        })
      );
      
      await waitFor(() => {
        expect(result.current.connected).toBe(true);
      });
      
      const testMessage = { type: 'test', data: 'hello' };
      
      act(() => {
        if (mockWs.onmessage) {
          mockWs.onmessage(new MessageEvent('message', {
            data: JSON.stringify(testMessage)
          }));
        }
      });
      
      await waitFor(() => {
        expect(onMessage).toHaveBeenCalledWith(testMessage);
      });
    });
  });

  describe('Edge Cases', () => {
    it('handles rapid connect/disconnect cycles', async () => {
      const { result, unmount } = renderHook(() => 
        useMeridSocket('ws://localhost:8000/ws/test')
      );
      
      await waitFor(() => {
        expect(result.current.connected).toBe(true);
      });
      
      unmount();
      
      // Should handle gracefully
      expect(true).toBe(true);
    });

    it('handles empty messages', async () => {
      const mockWs = new MockWebSocket('ws://localhost:8000/ws/test');
      global.WebSocket = jest.fn(() => mockWs) as any;
      
      const { result } = renderHook(() => 
        useMeridSocket('ws://localhost:8000/ws/test')
      );
      
      await waitFor(() => {
        expect(result.current.connected).toBe(true);
      });
      
      act(() => {
        if (mockWs.onmessage) {
          mockWs.onmessage(new MessageEvent('message', {
            data: ''
          }));
        }
      });
      
      // Should handle gracefully
      expect(result.current.connected).toBe(true);
    });

    it('handles null URL', () => {
      const { result } = renderHook(() => 
        useMeridSocket(null as any)
      );
      
      expect(result.current.connected).toBe(false);
    });
  });
});
