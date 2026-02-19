import { WS_URL } from '../config/constants';
import { logUiError } from '../utils/logger';

type MessageHandler = (data: unknown) => void;
type ErrorHandler = (error: Event) => void;
type ConnectionHandler = () => void;

interface WebSocketConfig {
  url: string;
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
}

export class WebSocketService {
  private ws: WebSocket | null = null;
  private config: WebSocketConfig;
  private messageHandlers: Map<string, Set<MessageHandler>> = new Map();
  private errorHandlers: Set<ErrorHandler> = new Set();
  private openHandlers: Set<ConnectionHandler> = new Set();
  private closeHandlers: Set<ConnectionHandler> = new Set();
  private reconnectAttempts = 0;
  private reconnectTimeout: NodeJS.Timeout | null = null;
  private isIntentionallyClosed = false;

  constructor(config: WebSocketConfig) {
    this.config = {
      reconnectInterval: 5000,
      maxReconnectAttempts: 10,
      ...config,
    };
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      console.log('[WebSocket] Already connected');
      return;
    }

    console.log(`[WebSocket] Attempting to connect to ${this.config.url}...`);
    
    try {
      this.ws = new WebSocket(this.config.url);
      
      this.ws.onopen = () => {
        console.log('[WebSocket] ✓ Connected successfully');
        this.reconnectAttempts = 0;
        this.openHandlers.forEach(handler => handler());
      };

      this.ws.onmessage = (event) => {
        console.log('[WebSocket] ← Message received:', event.data.substring(0, 100));
        try {
          const message = JSON.parse(event.data);
          if (!message || typeof message !== 'object') {
            return;
          }
          const messageType = message.type || message.event_type || message.event || null;
          if (!messageType) {
            return;
          }
          const payload = message.data ?? message.payload ?? message;
          const handlers = this.messageHandlers.get(messageType);
          if (handlers) {
            handlers.forEach(handler => handler(payload));
          }
        } catch (error) {
          logUiError('WebSocket', 'Error parsing WebSocket message', error);
        }
      };

      this.ws.onerror = (error) => {
        logUiError('WebSocket', 'Connection error', error, { url: this.config.url });
        this.errorHandlers.forEach(handler => handler(error));
      };

      this.ws.onclose = () => {
        console.log('WebSocket disconnected');
        this.closeHandlers.forEach(handler => handler());
        
        if (!this.isIntentionallyClosed) {
          this.attemptReconnect();
        }
      };
    } catch (error) {
      logUiError('WebSocket', 'Error creating WebSocket', error);
      this.attemptReconnect();
    }
  }

  private attemptReconnect(): void {
    if (this.reconnectAttempts >= (this.config.maxReconnectAttempts || 10)) {
      logUiError('WebSocket', 'Max reconnection attempts reached');
      return;
    }

    this.reconnectAttempts++;
    console.log(`Reconnecting... Attempt ${this.reconnectAttempts}`);

    this.reconnectTimeout = setTimeout(() => {
      this.connect();
    }, this.config.reconnectInterval);
  }

  disconnect(): void {
    this.isIntentionallyClosed = true;
    
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  send(type: string, data: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type, data }));
    } else {
      console.warn('WebSocket not connected, cannot send message');
    }
  }

  subscribe(type: string, handler: MessageHandler): () => void {
    let handlers = this.messageHandlers.get(type);
    if (!handlers) {
      handlers = new Set();
      this.messageHandlers.set(type, handlers);
    }
    
    handlers.add(handler);

    // Return unsubscribe function
    return () => {
      const handlers = this.messageHandlers.get(type);
      if (handlers) {
        handlers.delete(handler);
        if (handlers.size === 0) {
          this.messageHandlers.delete(type);
        }
      }
    };
  }

  onError(handler: ErrorHandler): () => void {
    this.errorHandlers.add(handler);
    return () => this.errorHandlers.delete(handler);
  }

  onOpen(handler: ConnectionHandler): () => void {
    this.openHandlers.add(handler);
    return () => this.openHandlers.delete(handler);
  }

  onClose(handler: ConnectionHandler): () => void {
    this.closeHandlers.add(handler);
    return () => this.closeHandlers.delete(handler);
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}

// Create singleton instance
const metaEnv = (import.meta as { env?: { VITE_WS_URL?: string } }).env;
const wsUrl = metaEnv?.VITE_WS_URL || WS_URL;
export const websocketService = new WebSocketService({ url: wsUrl });

// Auto-connect on import
if (typeof window !== 'undefined') {
  websocketService.connect();
}
