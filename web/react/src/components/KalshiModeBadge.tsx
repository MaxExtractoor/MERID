/**
 * KalshiModeBadge — Shows PAPER vs LIVE mode badge with tooltip.
 *
 * Fetches the current trade mode from the API and displays a clear
 * colored badge. Used across all Kalshi views so the operator always
 * knows which execution context is active.
 */

import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { Shield, Zap } from 'lucide-react';

interface VenueGateMode {
  mode: string;
  is_live: boolean;
  live_enabled: boolean;
}

export default function KalshiModeBadge() {
  const { data } = useApiData<VenueGateMode>(API_ENDPOINTS.KALSHI_GRID_MODE, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD,
  });

  const kalshiMode = (data?.mode ?? 'paper').toLowerCase();
  const isPaper = kalshiMode === 'paper' || kalshiMode === 'mock';
  const isShadow = kalshiMode === 'shadow';

  let label: string;
  let colorClass: string;
  let Icon: typeof Shield;
  let tooltip: string;

  if (isPaper) {
    label = 'PAPER';
    colorClass = 'bg-amber-500/20 text-amber-400 border-amber-500/30';
    Icon = Shield;
    tooltip = 'Paper trading mode — orders are simulated, no real money at risk';
  } else if (isShadow) {
    label = 'SHADOW';
    colorClass = 'bg-purple-500/20 text-purple-400 border-purple-500/30';
    Icon = Shield;
    tooltip = 'Shadow mode — signals generated but not executed';
  } else {
    label = 'LIVE';
    colorClass = 'bg-green-500/20 text-green-400 border-green-500/30';
    Icon = Zap;
    tooltip = 'Live trading mode — real orders on Kalshi';
  }

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border ${colorClass}`}
      title={tooltip}
    >
      <Icon className="w-3 h-3" />
      {label}
    </span>
  );
}
