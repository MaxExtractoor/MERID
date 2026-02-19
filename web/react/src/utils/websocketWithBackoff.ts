/**
 * WebSocket utility with exponential backoff and feature availability detection.
 * 
 * Provides robust reconnection logic that:
 * - Uses exponential backoff with jitter
 * - Enforces maximum retry attempts
 * - Detects "feature_unavailable" messages and stops retrying
 * - Reduces console noise after max retries
 */

export type WebSocketStatus = 
  | 'connecting' 
  | 'connected' 
  | 'disconnected' 
  | 'unavailable' 
  | 'max_retries_exceeded';

export interface WebSocketWithBackoffOptions {
  /** Maximum number of reconnect attempts (default: 5) */
  maxRetries?: number;
  /** Initial reconnect delay in ms (default: 1000) */
  initialDelay?: number;
  /** Maximum reconnect delay in ms (default: 30000) */
  maxDelay?: number;
  /** Backoff multiplier (default: 2) */
  backoffMultiplier?: number;
  /** Add jitter to delays (default: true) */
  useJitter?: boolean;
  /** Callback when message received */
  onMessage?: (data: Record<string, unknown>) => void;
  /** Callback when status changes */
  onStatusChange?: (status: WebSocketStatus, reason?: string) => void;
  /** Callback on error (called once per session, not every retry) */
  onError?: (error: Error) => void;
}

export interface WebSocketController {
  /** Current connection status */
  status: WebSocketStatus;
  /** Number of reconnect attempts */
  reconnectCount: number;
  /** Reason if unavailable */
  unavailableReason?: string;
  /** Send a message */
  send: (data: Record<string, unknown>) => boolean;
  /** Manually reconnect (resets retry counter) */
  reconnect: () => void;
  /** Close connection and stop retrying */
  close: () => void;
}

/**
 * Create a WebSocket connection with automatic reconnection and backoff.
 */
export function createWebSocketWithBackoff(
  url: string,
  options: WebSocketWithBackoffOptions = {}
): WebSocketController {
  const {
    maxRetries = 5,
    initialDelay = 1000,
    maxDelay = 30000,
    backoffMultiplier = 2,
    useJitter = true,
    onMessage,
    onStatusChange,
    onError,
  } = options;

  let ws: WebSocket | null = null;
  let status: WebSocketStatus = 'disconnected';
  let reconnectCount = 0;
  let reconnectTimeout: NodeJS.Timeout | null = null;
  let unavailableReason: string | undefined;
  let isManualClose = false;
  let hasLoggedError = false;

  const setStatus = (newStatus: WebSocketStatus, reason?: string) => {
    status = newStatus;
    if (reason) {
      unavailableReason = reason;
    }
    onStatusChange?.(newStatus, reason);
  };

  const calculateDelay = (): number => {
    const baseDelay = Math.min(
      initialDelay * Math.pow(backoffMultiplier, reconnectCount),
      maxDelay
    );
    
    if (useJitter) {
      // Add up to 30% jitter
      const jitter = baseDelay * 0.3 * Math.random();
      return Math.floor(baseDelay + jitter);
    }
    
    return baseDelay;
  };

  const connect = () => {
    if (status === 'unavailable' || status === 'max_retries_exceeded') {
      return;
    }

    if (ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) {
      return;
    }

    setStatus('connecting');

    try {
      ws = new WebSocket(url);

      ws.onopen = () => {
        reconnectCount = 0;
        hasLoggedError = false;
        setStatus('connected');
      };

      ws.onmessage = (event) => {
        try {
          const data = typeof event.data === 'string' 
            ? JSON.parse(event.data) 
            : event.data;

          // Check for feature_unavailable message from server
          if (data.type === 'feature_unavailable') {
            const reason = data.reason || 'Feature not available';
            setStatus('unavailable', reason);
            ws?.close(1000, 'Feature unavailable');
            return;
          }

          onMessage?.(data);
        } catch (e) {
          // If not JSON, pass raw data
          onMessage?.(event.data);
        }
      };

      ws.onerror = () => {
        // Only log error once per session to reduce noise
        if (!hasLoggedError) {
          hasLoggedError = true;
          onError?.(new Error(`WebSocket connection failed for ${url}`));
        }
      };

      ws.onclose = () => {
        ws = null;

        // Don't reconnect if manually closed or feature unavailable
        if (isManualClose || status === 'unavailable') {
          setStatus(status === 'unavailable' ? 'unavailable' : 'disconnected');
          return;
        }

        // Check if we've exceeded max retries
        if (reconnectCount >= maxRetries) {
          setStatus('max_retries_exceeded', `Exceeded ${maxRetries} reconnect attempts`);
          return;
        }

        // Schedule reconnect with backoff
        reconnectCount++;
        const delay = calculateDelay();
        
        // Only log reconnect on first few attempts
        if (reconnectCount <= 3) {
          console.debug(`[WS] Reconnecting to ${url} in ${delay}ms (attempt ${reconnectCount}/${maxRetries})`);
        }

        setStatus('disconnected');
        reconnectTimeout = setTimeout(connect, delay);
      };

    } catch (err) {
      if (!hasLoggedError) {
        hasLoggedError = true;
        onError?.(err as Error);
      }
      setStatus('disconnected');
    }
  };

  const send = (data: unknown): boolean => {
    if (ws?.readyState === WebSocket.OPEN) {
      const payload = typeof data === 'string' ? data : JSON.stringify(data);
      ws.send(payload);
      return true;
    }
    return false;
  };

  const reconnect = () => {
    // Reset state for manual reconnect
    reconnectCount = 0;
    hasLoggedError = false;
    isManualClose = false;
    unavailableReason = undefined;
    
    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout);
      reconnectTimeout = null;
    }
    
    if (ws) {
      ws.close();
      ws = null;
    }
    
    connect();
  };

  const close = () => {
    isManualClose = true;
    
    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout);
      reconnectTimeout = null;
    }
    
    if (ws) {
      ws.close(1000, 'Manual close');
      ws = null;
    }
    
    setStatus('disconnected');
  };

  // Start initial connection
  connect();

  return {
    get status() { return status; },
    get reconnectCount() { return reconnectCount; },
    get unavailableReason() { return unavailableReason; },
    send,
    reconnect,
    close,
  };
}

/**
 * Build WebSocket URL for MERID backend
 */
export function buildWsUrl(endpoint: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.hostname;
  const port = '8000';
  return `${protocol}//${host}:${port}${endpoint}`;
}
