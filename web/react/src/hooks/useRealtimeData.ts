import { useEffect, useMemo, useState, useCallback } from 'react';
import { WebSocketService, websocketService } from '../services/websocket';

const wsClients = new Map<string, WebSocketService>();

const getWebSocketClient = (url: string): WebSocketService => {
  const existing = wsClients.get(url);
  if (existing) return existing;

  const client = new WebSocketService({ url });
  wsClients.set(url, client);
  if (typeof window !== 'undefined') {
    client.connect();
  }
  return client;
};

export function useRealtimeData<T>(
  messageType: string,
  initialData: T | null = null,
  wsUrl?: string
): [T | null, boolean, Error | null] {
  const [data, setData] = useState<T | null>(initialData);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const wsClient = useMemo(() => {
    return wsUrl ? getWebSocketClient(wsUrl) : websocketService;
  }, [wsUrl]);

  useEffect(() => {
    // Subscribe to connection status
    const unsubscribeOpen = wsClient.onOpen(() => {
      setIsConnected(true);
      setError(null);
    });

    const unsubscribeClose = wsClient.onClose(() => {
      setIsConnected(false);
    });

    const unsubscribeError = wsClient.onError(() => {
      setError(new Error('WebSocket connection error'));
      setIsConnected(false);
    });

    // Subscribe to specific message type
    const unsubscribeMessage = wsClient.subscribe(messageType, (newData: T) => {
      setData(newData);
      setError(null);
    });

    // Check initial connection status
    setIsConnected(wsClient.isConnected());

    // Cleanup subscriptions
    return () => {
      unsubscribeOpen();
      unsubscribeClose();
      unsubscribeError();
      unsubscribeMessage();
    };
  }, [messageType, wsClient]);

  return [data, isConnected, error];
}

export function useRealtimeSubscription<T>(
  messageType: string,
  callback: (data: T) => void,
  wsUrl?: string
): [boolean, Error | null] {
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const wsClient = useMemo(() => {
    return wsUrl ? getWebSocketClient(wsUrl) : websocketService;
  }, [wsUrl]);

  useEffect(() => {
    const unsubscribeOpen = wsClient.onOpen(() => {
      setIsConnected(true);
      setError(null);
    });

    const unsubscribeClose = wsClient.onClose(() => {
      setIsConnected(false);
    });

    const unsubscribeError = wsClient.onError(() => {
      setError(new Error('WebSocket connection error'));
      setIsConnected(false);
    });

    const unsubscribeMessage = wsClient.subscribe(messageType, callback);

    setIsConnected(wsClient.isConnected());

    return () => {
      unsubscribeOpen();
      unsubscribeClose();
      unsubscribeError();
      unsubscribeMessage();
    };
  }, [messageType, callback, wsClient]);

  return [isConnected, error];
}

export function useSendMessage() {
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    const unsubscribeOpen = websocketService.onOpen(() => {
      setIsConnected(true);
    });

    const unsubscribeClose = websocketService.onClose(() => {
      setIsConnected(false);
    });

    setIsConnected(websocketService.isConnected());

    return () => {
      unsubscribeOpen();
      unsubscribeClose();
    };
  }, []);

  const send = useCallback((type: string, data: unknown) => {
    websocketService.send(type, data);
  }, []);

  return { send, isConnected };
}
