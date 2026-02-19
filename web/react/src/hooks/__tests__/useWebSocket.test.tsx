import { renderHook, act } from '@testing-library/react';
import { useWebSocket } from '../useWebSocket';

// Mock WebSocket
class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  
  readyState = MockWebSocket.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  lastSent: string | null = null;
  
  constructor(public url: string, public protocols?: string | string[]) {
    // Simulate connection
    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN;
      if (this.onopen) {
        this.onopen(new Event('open'));
      }
    }, 0);
  }
  
  send(data: string) {
    this.lastSent = data;
  }
  
  close() {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) {
      this.onclose(new CloseEvent('close'));
    }
  }
}

// Replace global WebSocket
Object.defineProperty(global, 'WebSocket', {
  writable: true,
  value: MockWebSocket,
});

describe('useWebSocket', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('initializes with disconnected state', () => {
    const { result } = renderHook(() => useWebSocket({ url: 'ws://localhost:3000' }));
    
    expect(result.current.connected).toBe(false);
    expect(result.current.socket).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('connects when autoConnect is true', async () => {
    const { result } = renderHook(() => 
      useWebSocket({ url: 'ws://localhost:3000', autoConnect: true })
    );
    
    // Wait for connection
    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 10));
    });
    
    expect(result.current.connected).toBe(true);
    expect(result.current.socket).not.toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('does not connect when autoConnect is false', () => {
    const { result } = renderHook(() => 
      useWebSocket({ url: 'ws://localhost:3000', autoConnect: false })
    );
    
    expect(result.current.connected).toBe(false);
    expect(result.current.socket).toBeNull();
  });

  it('handles messages correctly', async () => {
    const { result } = renderHook(() => 
      useWebSocket({ url: 'ws://localhost:3000', autoConnect: true })
    );
    
    // Wait for connection
    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 10));
    });
    
    const mockSocket = result.current.socket as unknown as MockWebSocket;
    const testMessage = { type: 'test', data: 'hello' };
    
    // Simulate receiving a message
    act(() => {
      if (mockSocket.onmessage) {
        mockSocket.onmessage(new MessageEvent('message', { data: JSON.stringify(testMessage) }));
      }
    });
    
    expect(result.current.lastMessage).toEqual(testMessage);
  });

  it('sends messages correctly', async () => {
    const { result } = renderHook(() => 
      useWebSocket({ url: 'ws://localhost:3000', autoConnect: true })
    );
    
    // Wait for connection
    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 10));
    });
    
    const mockSocket = result.current.socket as unknown as MockWebSocket;
    const sendSpy = jest.spyOn(mockSocket, 'send');
    
    act(() => {
      result.current.send('test message');
    });
    
    expect(sendSpy).toHaveBeenCalledWith('test message');
  });

  it('disconnects correctly', async () => {
    const { result } = renderHook(() => 
      useWebSocket({ url: 'ws://localhost:3000', autoConnect: true })
    );
    
    // Wait for connection
    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 10));
    });
    
    const mockSocket = result.current.socket as unknown as MockWebSocket;
    const closeSpy = jest.spyOn(mockSocket, 'close');
    
    act(() => {
      result.current.disconnect();
    });
    
    expect(closeSpy).toHaveBeenCalled();
  });

  it('handles connection errors', () => {
    // Mock WebSocket to throw error
    Object.defineProperty(global, 'WebSocket', {
      writable: true,
      value: class {
        constructor() {
          throw new Error('Connection failed');
        }
      },
    });

    const { result } = renderHook(() => 
      useWebSocket({ url: 'ws://invalid-url', autoConnect: true })
    );
    
    expect(result.current.error?.message).toBe('Failed to create WebSocket connection');
    expect(result.current.connected).toBe(false);
  });
});
