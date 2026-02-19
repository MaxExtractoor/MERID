import { useState, useEffect } from 'react';
import { WifiOff } from 'lucide-react';
import { useMeridSocket } from '../hooks/useMeridSocket';

/**
 * Prominent banner shown when the main WebSocket is disconnected.
 * Displays elapsed time since disconnect so the operator knows
 * how stale real-time data may be.
 */
export function RealtimeDisconnectedBanner() {
  const { connected } = useMeridSocket();
  const [disconnectedAt, setDisconnectedAt] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState('');

  useEffect(() => {
    if (!connected && disconnectedAt === null) {
      setDisconnectedAt(Date.now());
    } else if (connected) {
      setDisconnectedAt(null);
      setElapsed('');
    }
  }, [connected, disconnectedAt]);

  useEffect(() => {
    if (disconnectedAt === null) return;
    const tick = () => {
      const ms = Date.now() - disconnectedAt;
      if (ms < 60_000) setElapsed(`${Math.floor(ms / 1000)}s`);
      else if (ms < 3_600_000) setElapsed(`${Math.floor(ms / 60_000)}m`);
      else setElapsed(`${Math.floor(ms / 3_600_000)}h ${Math.floor((ms % 3_600_000) / 60_000)}m`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [disconnectedAt]);

  if (connected || disconnectedAt === null) return null;

  return (
    <div className="bg-red-900/90 border-b border-red-600/50 px-4 py-2 flex items-center justify-center gap-2 text-red-200 text-sm font-medium">
      <WifiOff className="w-4 h-4 flex-shrink-0 animate-pulse" />
      <span>
        Real-time feed disconnected ({elapsed}) — prices, fills, and alerts may be stale. Reconnecting...
      </span>
    </div>
  );
}
