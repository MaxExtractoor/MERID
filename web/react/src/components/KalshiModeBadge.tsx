/**
 * KalshiModeBadge — Shows PAPER vs LIVE mode badge with tooltip.
 *
 * Fetches the current trade mode from the API and displays a clear
 * colored badge. Used across all Kalshi views so the operator always
 * knows which execution context is active.
 */

import React from 'react';
import { useKalshiMode } from '../context/KalshiModeContext';
import { Shield, Zap } from 'lucide-react';
import { MODE_COLORS, resolveModeKey } from '../config/modeColors';

function KalshiModeBadge() {
  const { data, loading } = useKalshiMode();

  if (loading && !data) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border bg-slate-700/50 text-slate-500 border-slate-600/30">
        <Shield className="w-3 h-3" />
        …
      </span>
    );
  }

  const isLive = data?.is_live ?? false;
  const modeKey = resolveModeKey(data?.mode, isLive);
  const colors = MODE_COLORS[modeKey];

  const LABELS: Record<typeof modeKey, string> = {
    live: 'LIVE',
    paper: 'PAPER',
    shadow: 'SHADOW',
    unknown: (data?.mode ?? '').toUpperCase() || 'UNKNOWN',
  };
  const TOOLTIPS: Record<typeof modeKey, string> = {
    live: 'Live trading mode — real orders on Kalshi with real money',
    paper: 'Paper trading mode — orders are simulated, no real money at risk',
    shadow: 'Shadow mode — signals generated but not executed',
    unknown: `Trading mode: ${data?.mode ?? 'unknown'}`,
  };

  const Icon = isLive ? Zap : Shield;

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold ${colors.badge}`}
      title={TOOLTIPS[modeKey]}
    >
      {isLive && <span className={`w-1.5 h-1.5 rounded-full ${colors.dot} animate-pulse`} />}
      <Icon className="w-3 h-3" />
      {LABELS[modeKey]}
    </span>
  );
}

KalshiModeBadge.displayName = 'KalshiModeBadge';
export default React.memo(KalshiModeBadge);
