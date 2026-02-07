import { useEffect } from "react";
import { useMeridSocket } from "./useMeridSocket";

export function useSocketAuth() {
  const { socket, connected } = useMeridSocket();

  useEffect(() => {
    if (socket && connected) {
      // Auth is handled by the underlying useMeridSocket hook
      // which reads the token from localStorage automatically
      console.log("Socket authenticated and connected");
    }
  }, [socket, connected]);

  return { socket, connected };
}
