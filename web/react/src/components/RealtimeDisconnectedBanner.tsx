import { useState, useEffect, useRef } from 'react';
import { WifiOff } from '../ui/icons';
import { useKalshiStore } from '../store';

const CLOCK_TICK_MS = 5000; // re-check staleness every 5s
const STALE_MS = 30_000;    // lastUpdate older than this = stale data
const MOUNT_GRACE_MS = 4_000; // don't flash the banner before first poll lands

/**
 * Prominent banner shown when the backend is unreachable or data is stale.
 * Driven by the store's `connected` flag (set by refreshAll probes) and
 * `lastUpdate` freshness — there is no WebSocket feed on this backend.
 */
export function RealtimeDisconnectedBanner() {
  const connected = useKalshiStore(s => s.connected);
  const lastUpdate = useKalshiStore(s => s.lastUpdate);
  const mountedAt = useRef(Date.now());
  const [now, setNow] = useState(Date.now());
  const [disconnectedAt, setDisconnectedAt] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState('');

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), CLOCK_TICK_MS);
    return () => clearInterval(id);
  }, []);

  const stale = lastUpdate > 0 && now - lastUpdate > STALE_MS;
  const disconnected = !connected || stale;

  useEffect(() => {
    if (disconnected && disconnectedAt === null) {
      setDisconnectedAt(now);
    } else if (!disconnected) {
      setDisconnectedAt(null);
      setElapsed('');
    }
  }, [disconnected, disconnectedAt, now]);

  useEffect(() => {
    if (disconnectedAt === null) return;
    const ms = now - disconnectedAt;
    if (ms < 60_000) setElapsed(`${Math.floor(ms / 1000)}s`);
    else if (ms < 3_600_000) setElapsed(`${Math.floor(ms / 60_000)}m`);
    else setElapsed(`${Math.floor(ms / 3_600_000)}h ${Math.floor((ms % 3_600_000) / 60_000)}m`);
  }, [disconnectedAt, now]);

  // Grace period: never show a false alarm while the first refresh is in flight.
  if (!disconnected || disconnectedAt === null) return null;
  if (lastUpdate === 0 && now - mountedAt.current < MOUNT_GRACE_MS) return null;

  return (
    <div className="bg-red-900/90 border-b border-red-600/50 px-4 py-2 flex items-center justify-center gap-2 text-red-200 text-sm font-medium">
      <WifiOff className="w-4 h-4 flex-shrink-0 animate-pulse" />
      <span>
        Backend unreachable ({elapsed}) — balances, positions, and risk data may be stale. Retrying automatically...
      </span>
    </div>
  );
}
