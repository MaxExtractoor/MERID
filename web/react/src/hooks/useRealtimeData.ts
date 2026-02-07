import { useEffect, useState, useCallback } from 'react';
import { websocketService } from '../services/websocket';

export function useRealtimeData<T>(
  messageType: string,
  initialData: T | null = null
): [T | null, boolean, Error | null] {
  const [data, setData] = useState<T | null>(initialData);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    // Subscribe to connection status
    const unsubscribeOpen = websocketService.onOpen(() => {
      setIsConnected(true);
      setError(null);
    });

    const unsubscribeClose = websocketService.onClose(() => {
      setIsConnected(false);
    });

    const unsubscribeError = websocketService.onError(() => {
      setError(new Error('WebSocket connection error'));
      setIsConnected(false);
    });

    // Subscribe to specific message type
    const unsubscribeMessage = websocketService.subscribe(messageType, (newData: T) => {
      setData(newData);
      setError(null);
    });

    // Check initial connection status
    setIsConnected(websocketService.isConnected());

    // Cleanup subscriptions
    return () => {
      unsubscribeOpen();
      unsubscribeClose();
      unsubscribeError();
      unsubscribeMessage();
    };
  }, [messageType]);

  return [data, isConnected, error];
}

export function useRealtimeSubscription<T>(
  messageType: string,
  callback: (data: T) => void
): [boolean, Error | null] {
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    const unsubscribeOpen = websocketService.onOpen(() => {
      setIsConnected(true);
      setError(null);
    });

    const unsubscribeClose = websocketService.onClose(() => {
      setIsConnected(false);
    });

    const unsubscribeError = websocketService.onError(() => {
      setError(new Error('WebSocket connection error'));
      setIsConnected(false);
    });

    const unsubscribeMessage = websocketService.subscribe(messageType, callback);

    setIsConnected(websocketService.isConnected());

    return () => {
      unsubscribeOpen();
      unsubscribeClose();
      unsubscribeError();
      unsubscribeMessage();
    };
  }, [messageType, callback]);

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

  const send = useCallback((type: string, data: any) => {
    websocketService.send(type, data);
  }, []);

  return { send, isConnected };
}
