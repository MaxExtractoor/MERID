/**
 * BackendOfflineBanner — Global banner shown when the backend is unreachable.
 *
 * Displays a single, non-spammy notification with:
 *  - "Backend unavailable (localhost:8011)"
 *  - Countdown to next retry
 *  - "Retry Now" button
 *
 * Renders nothing when the backend is healthy.
 */

import { useState, useEffect } from 'react';
import { WifiOff, RefreshCw } from 'lucide-react';
import { useBackendHealth } from '../context/BackendHealthContext';
import { API_BASE_URL } from '../config/constants';

export default function BackendOfflineBanner() {
  const { backendOffline, nextRetryAt, consecutiveFailures, probeNow } = useBackendHealth();
  const [countdownSec, setCountdownSec] = useState<number | null>(null);
  const [probing, setProbing] = useState(false);

  // Tick the countdown every second while offline.
  useEffect(() => {
    if (!backendOffline || !nextRetryAt) {
      setCountdownSec(null);
      return;
    }

    const tick = () => {
      const remaining = Math.max(0, Math.ceil((nextRetryAt - Date.now()) / 1000));
      setCountdownSec(remaining);
    };

    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [backendOffline, nextRetryAt]);

  if (!backendOffline) return null;

  const handleRetryNow = () => {
    setProbing(true);
    probeNow();
    // Reset after a short delay so the spinner shows briefly.
    setTimeout(() => setProbing(false), 2000);
  };

  // Extract the host portion from API_BASE_URL for display.
  let displayHost = API_BASE_URL;
  try {
    const u = new URL(API_BASE_URL);
    displayHost = u.host;
  } catch { /* keep the full string */ }

  return (
    <div className="flex items-center gap-3 px-4 py-2.5 bg-amber-900/30 border-b border-amber-600/40 text-amber-200 text-sm">
      <WifiOff className="w-4 h-4 shrink-0 text-amber-400" />
      <span className="font-medium">
        Backend unavailable
        <span className="text-amber-400/70 ml-1">({displayHost})</span>
      </span>

      {countdownSec !== null && countdownSec > 0 && (
        <span className="text-amber-400/60 text-xs">
          Retrying in {countdownSec}s
        </span>
      )}

      {consecutiveFailures > 0 && (
        <span className="text-amber-400/40 text-xs">
          ({consecutiveFailures} failed attempt{consecutiveFailures !== 1 ? 's' : ''})
        </span>
      )}

      <button
        type="button"
        onClick={handleRetryNow}
        disabled={probing}
        className="ml-auto flex items-center gap-1 px-2.5 py-1 rounded text-xs font-semibold
                   bg-amber-700/40 border border-amber-500/40 text-amber-200
                   hover:bg-amber-600/50 hover:text-white
                   disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        <RefreshCw className={`w-3 h-3 ${probing ? 'animate-spin' : ''}`} />
        {probing ? 'Checking\u2026' : 'Retry Now'}
      </button>
    </div>
  );
}
