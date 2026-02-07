import { useEffect, useRef, useState, useCallback } from "react";
import { useWebSocket } from "./useWebSocket";
import { WS_URL } from "../config/constants";

export function useMeridSocket() {
  const [connected, setConnected] = useState(false);
  const lastMessageRef = useRef<any>(null);
  const eventListenersRef = useRef<Map<string, Set<(data: any) => void>>>(new Map());

  // Use our WebSocket hook
  const { socket, send } = useWebSocket({
    url: WS_URL,
    autoConnect: true,
  });

  // Socket.io-like emit method
  const emit = useCallback((event: string, data?: any) => {
    const message = JSON.stringify({ event, data });
    send(message);
  }, [send]);

  // Socket.io-like on method
  const on = useCallback((event: string, callback: (data: any) => void) => {
    if (!eventListenersRef.current.has(event)) {
      eventListenersRef.current.set(event, new Set());
    }
    eventListenersRef.current.get(event)!.add(callback);
  }, []);

  // Socket.io-like off method
  const off = useCallback((event: string, callback: (data: any) => void) => {
    const listeners = eventListenersRef.current.get(event);
    if (listeners) {
      listeners.delete(callback);
    }
  }, []);

  // Handle incoming messages
  useEffect(() => {
    if (lastMessageRef.current && typeof lastMessageRef.current === 'object' && 'event' in lastMessageRef.current) {
      const { event, data } = lastMessageRef.current;
      const listeners = eventListenersRef.current.get(event);
      if (listeners) {
        listeners.forEach(listener => listener(data));
      }
    }
  }, []);

  // Update connected state
  useEffect(() => {
    setConnected(!!socket && socket.readyState === 1);
  }, [socket]);

  return { 
    socket: socket ? {
      emit,
      on,
      off,
      connected,
    } : null, 
    connected 
  };
}

// Native WebSocket with manual backoff
export function useNativeWebSocket(url: string) {
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const retriesRef = useRef(0);

  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket(url);
      
      ws.onopen = () => {
        retriesRef.current = 0;
        setConnected(true);
        setSocket(ws);
      };
      
      ws.onclose = () => {
        setConnected(false);
        setSocket(null);
        
        const timeout = Math.min(1000 * 2 ** retriesRef.current, 10000);
        retriesRef.current += 1;
        setTimeout(connect, timeout);
      };
      
      ws.onerror = () => ws.close();
    };

    connect();
  }, [url]);

  return { socket, connected };
}
