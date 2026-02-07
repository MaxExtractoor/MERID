import { useState, useCallback } from "react";
import { useMeridSocket } from "./useMeridSocket";

type UseMeridSocketCompleteResult = {
  socket: ReturnType<typeof useMeridSocket>['socket'];
  connected: boolean;
  lastError: string | null;
  reconnect: () => void;
};

export function useMeridSocketComplete(): UseMeridSocketCompleteResult {
  const { socket, connected } = useMeridSocket();
  const [lastError, setLastError] = useState<string | null>(null);

  const reconnect = useCallback(() => {
    setLastError(null);
    // The underlying useMeridSocket will handle reconnection
  }, []);

  return {
    socket,
    connected,
    lastError,
    reconnect,
  };
}
