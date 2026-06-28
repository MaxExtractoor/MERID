/**
 * GlobalModeBanner — Persistent top-of-page indicator for trading mode
 * 
 * This banner is IMPOSSIBLE TO MISS. It shows at the top of every view
 * when not in LIVE mode, or when synthetic/manual data is displayed.
 */

import React from 'react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

type TradingMode = 'LIVE' | 'PAPER' | 'SHADOW' | 'HALTED' | 'MIXED';

interface ModeState {
  mode: TradingMode;
  profile: string;
  hasSyntheticData: boolean;
  hasExternalOrders: boolean;
  killSwitchActive: boolean;
  reconciliationStatus: 'ok' | 'degraded' | 'broken' | 'unknown';
}

export function GlobalModeBanner() {
  // Fetch mode from multiple sources
  const modeResult = useApiData<{ mode: string; is_live: boolean }>(
    API_ENDPOINTS.KALSHI_GRID_MODE,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );

  const riskResult = useApiData<{ kill_switch_active?: boolean }>(
    API_ENDPOINTS.KALSHI_RISK,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );

  const reconResult = useApiData<{ status?: 'ok' | 'degraded' | 'broken' | 'unknown' }>(
    API_ENDPOINTS.KALSHI_HEALTH + '/reconciliation',
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );

  const ordersResult = useApiData<{ orders: Array<{ synthetic?: boolean; manual_or_external?: boolean }> }>(
    API_ENDPOINTS.KALSHI_ORDERS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );

  const positionsResult = useApiData<{ positions: Array<{ synthetic?: boolean; manual_or_external?: boolean }> }>(
    API_ENDPOINTS.KALSHI_POSITIONS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );

  // Determine effective mode
  const modeState = React.useMemo<ModeState>(() => {
    const modeStr = (modeResult.data?.mode || 'paper').toLowerCase();
    const isLive = modeResult.data?.is_live || false;
    const killSwitch = riskResult.data?.kill_switch_active || false;
    const reconStatus = reconResult.data?.status || 'unknown';

    // Check for synthetic/manual data
    const hasSyntheticOrders = (ordersResult.data?.orders || []).some(o => o.synthetic);
    const hasExternalOrders = (ordersResult.data?.orders || []).some(o => o.manual_or_external);
    const hasSyntheticPositions = (positionsResult.data?.positions || []).some(p => p.synthetic);
    const hasExternalPositions = (positionsResult.data?.positions || []).some(p => p.manual_or_external);

    const hasSyntheticData = hasSyntheticOrders || hasSyntheticPositions;
    const hasExternalData = hasExternalOrders || hasExternalPositions;

    // Determine trading mode
    let mode: TradingMode = 'PAPER';
    if (killSwitch) {
      mode = 'HALTED';
    } else if (isLive && !hasSyntheticData && !hasExternalData) {
      mode = 'LIVE';
    } else if (modeStr.includes('shadow')) {
      mode = 'SHADOW';
    } else if (hasSyntheticData || hasExternalData) {
      mode = 'MIXED';
    }

    return {
      mode,
      profile: modeStr,
      hasSyntheticData,
      hasExternalOrders: hasExternalData,
      killSwitchActive: killSwitch,
      reconciliationStatus: reconStatus,
    };
  }, [modeResult.data, riskResult.data, reconResult.data, ordersResult.data, positionsResult.data]);

  // Don't show banner in clean LIVE mode with no issues
  if (modeState.mode === 'LIVE' && modeState.reconciliationStatus === 'ok') {
    return (
      <div className="h-1 bg-gradient-to-r from-green-500 via-emerald-500 to-green-500" title="LIVE TRADING MODE" />
    );
  }

  // Banner configurations by mode
  const config: Record<TradingMode, { color: string; icon: string; desc: string }> = {
    LIVE: { color: 'green', icon: '●', desc: 'Real orders, real capital' },
    PAPER: { color: 'blue', icon: '◎', desc: 'Simulated orders, no real capital' },
    SHADOW: { color: 'cyan', icon: '◐', desc: 'Shadow trading (parallel paper)' },
    HALTED: { color: 'red', icon: '◼', desc: 'Trading halted by kill switch' },
    MIXED: { color: 'orange', icon: '◑', desc: 'Mixed data sources detected' },
  };

  const c = config[modeState.mode];

  return (
    <div className={`relative ${
      modeState.mode === 'HALTED' ? 'bg-red-950/90 border-b-2 border-red-500' :
      modeState.mode === 'MIXED' ? 'bg-orange-950/90 border-b-2 border-orange-500' :
      'bg-blue-950/90 border-b-2 border-blue-500'
    }`}>
      <div className="flex items-center justify-between px-4 py-2">
        <div className="flex items-center gap-3">
          {/* Pulsing indicator */}
          <span className={`w-3 h-3 rounded-full animate-pulse ${
            modeState.mode === 'HALTED' ? 'bg-red-500' :
            modeState.mode === 'MIXED' ? 'bg-orange-500' :
            'bg-blue-500'
          }`} />
          
          {/* Mode text */}
          <div className="flex items-baseline gap-2">
            <span className={`text-sm font-bold uppercase tracking-wider ${
              modeState.mode === 'HALTED' ? 'text-red-400' :
              modeState.mode === 'MIXED' ? 'text-orange-400' :
              'text-blue-400'
            }`}>
              {modeState.mode} MODE
            </span>
            <span className="text-xs text-gray-400">— {c.desc}</span>
          </div>
        </div>

        {/* Right side: Issue indicators */}
        <div className="flex items-center gap-3">
          {modeState.killSwitchActive && (
            <span className="px-2 py-0.5 rounded bg-red-500/30 text-red-400 text-xs font-bold uppercase">
              KILL SWITCH ACTIVE
            </span>
          )}
          
          {modeState.hasSyntheticData && (
            <span className="px-2 py-0.5 rounded bg-purple-500/30 text-purple-400 text-xs">
              SYNTHETIC DATA
            </span>
          )}
          
          {modeState.hasExternalOrders && (
            <span className="px-2 py-0.5 rounded bg-orange-500/30 text-orange-400 text-xs">
              EXTERNAL ORDERS
            </span>
          )}
          
          {modeState.reconciliationStatus !== 'ok' && (
            <span className={`px-2 py-0.5 rounded text-xs ${
              modeState.reconciliationStatus === 'broken' 
                ? 'bg-red-500/30 text-red-400' 
                : 'bg-yellow-500/30 text-yellow-400'
            }`}>
              RECON: {modeState.reconciliationStatus.toUpperCase()}
            </span>
          )}
        </div>
      </div>

      {/* Progress bar for visual emphasis */}
      <div className={`h-0.5 ${
        modeState.mode === 'HALTED' ? 'bg-red-500' :
        modeState.mode === 'MIXED' ? 'bg-orange-500' :
        'bg-blue-500'
      } animate-pulse`} />
    </div>
  );
}
