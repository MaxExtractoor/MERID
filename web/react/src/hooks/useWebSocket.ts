import { useEffect, useRef, useState, useCallback } from 'react';

type UseWebSocketOptions = {
  url: string;
  protocols?: string | string[];
  autoConnect?: boolean;
};

type WebSocketState<TMessage = unknown> = {
  socket: WebSocket | null;
  connected: boolean;
  lastMessage: TMessage | null;
  error: Error | null;
  send: (data: string) => void;
  disconnect: () => void;
};

export function useWebSocket<TMessage = unknown>(
  { url, protocols, autoConnect = true }: UseWebSocketOptions
): WebSocketState<TMessage> {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<TMessage | null>(null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!autoConnect) return;

    try {
      const socket = new WebSocket(url, protocols);
      socketRef.current = socket;

      socket.onopen = () => {
        setConnected(true);
        setError(null);
      };

      socket.onclose = () => {
        setConnected(false);
      };

      socket.onerror = () => {
        setError(new Error('WebSocket connection error'));
      };

      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as TMessage;
          setLastMessage(data);
        } catch (err) {
          setError(new Error('Failed to parse WebSocket message'));
        }
      };

      return () => {
        socket.close();
        socketRef.current = null;
      };
    } catch (err) {
      setError(new Error('Failed to create WebSocket connection'));
    }
  }, [url, protocols, autoConnect]);

  const send = useCallback((data: string) => {
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) return;
    socketRef.current.send(data);
  }, []);

  const disconnect = useCallback(() => {
    if (!socketRef.current) return;
    socketRef.current.close();
  }, []);

  return {
    socket: socketRef.current,
    connected,
    lastMessage,
    error,
    send,
    disconnect,
  };
}
