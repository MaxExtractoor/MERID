/**
 * KalshiModeBadge — Shows PAPER vs LIVE mode badge with tooltip.
 *
 * Fetches the current trade mode from the API and displays a clear
 * colored badge. Used across all Kalshi views so the operator always
 * knows which execution context is active.
 */

import { useKalshiMode } from '../context/KalshiModeContext';
import { Shield, Zap } from 'lucide-react';

export default function KalshiModeBadge() {
  const { data, loading } = useKalshiMode();

  if (loading && !data) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border bg-slate-700/50 text-slate-500 border-slate-600/30">
        <Shield className="w-3 h-3" />
        …
      </span>
    );
  }

  const kalshiMode = (data?.mode ?? 'paper').toLowerCase();
  const isLive = data?.is_live ?? false;
  const isPaper = !isLive && (kalshiMode === 'paper' || kalshiMode === 'mock' || kalshiMode === 'sim');
  const isShadow = kalshiMode === 'shadow';

  let label: string;
  let colorClass: string;
  let Icon: typeof Shield;
  let tooltip: string;

  if (isLive) {
    label = 'LIVE';
    colorClass = 'bg-green-500/20 text-green-400 border-green-500/30';
    Icon = Zap;
    tooltip = 'Live trading mode — real orders on Kalshi with real money';
  } else if (isShadow) {
    label = 'SHADOW';
    colorClass = 'bg-purple-500/20 text-purple-400 border-purple-500/30';
    Icon = Shield;
    tooltip = 'Shadow mode — signals generated but not executed';
  } else if (isPaper) {
    label = 'PAPER';
    colorClass = 'bg-amber-500/20 text-amber-400 border-amber-500/30';
    Icon = Shield;
    tooltip = 'Paper trading mode — orders are simulated, no real money at risk';
  } else {
    label = kalshiMode.toUpperCase();
    colorClass = 'bg-slate-700/50 text-slate-400 border-slate-600/30';
    Icon = Shield;
    tooltip = `Trading mode: ${kalshiMode}`;
  }

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border ${colorClass}`}
      title={tooltip}
    >
      {isLive && <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />}
      <Icon className="w-3 h-3" />
      {label}
    </span>
  );
}
