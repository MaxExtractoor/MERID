/**
 * Kalshi15mShadowModePanel — Shadow mode logging panel for 15m stack.
 *
 * Shows recent *blocked* candidates/trades due to fail-closed behavior:
 * - Asset, market_id, window start/expiry
 * - Block reason and key metrics (spot age, spread, data_quality_score)
 * - Count of blocked candidates in the last N minutes
 *
 * This provides production-grade observability into the consequences of
 * Kalshi alignment rules, not just "is the loop running."
 */

import React from 'react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { XCircle, AlertTriangle, Clock, TrendingDown } from '../ui/icons';

interface BlockedCandidate {
  asset: string;
  market_id: string;
  window_start: string;
  window_expiry: string;
  block_reason: string;
  spot_age_ms: number;
  spread_cents: number | null;
  data_quality_score: number | null;
  edge_cents: number | null;
  timestamp: string;
}

interface ShadowResponse {
  total_blocked_last_5m: number;
  total_blocked_last_15m: number;
  total_blocked_last_60m: number;
  blocked_candidates: BlockedCandidate[];
  summary: {
    by_reason: Record<string, number>;
    by_asset: Record<string, number>;
  };
}

const BlockedCandidateRow: React.FC<{ candidate: BlockedCandidate }> = ({ candidate }) => {
  const formatAge = (ms: number) => {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}m`;
  };

  const formatTime = (ts: string) => {
    const date = new Date(ts);
    return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  const reasonColors: Record<string, string> = {
    'SPOT-PRICE-MISSING': 'text-red-400',
    'SPOT-PRICE-STALE': 'text-amber-400',
    'SPREAD-MISSING': 'text-red-400',
    'SPREAD-WIDE': 'text-amber-400',
    'DATA-QUALITY-LOW': 'text-amber-400',
    'EDGE-INSUFFICIENT': 'text-slate-400',
    'RISK-LIMIT': 'text-red-400',
  };

  const reasonColor = reasonColors[candidate.block_reason] || 'text-slate-400';

  return (
    <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <XCircle className="w-4 h-4 text-red-400" />
          <span className="font-semibold text-white">{candidate.asset}</span>
        </div>
        <span className="text-xs text-slate-500">{formatTime(candidate.timestamp)}</span>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs mb-2">
        <div>
          <span className="text-slate-500">Market:</span>
          <span className="ml-1 font-mono text-white">{candidate.market_id}</span>
        </div>
        <div>
          <span className="text-slate-500">Reason:</span>
          <span className={`ml-1 font-mono ${reasonColor}`}>{candidate.block_reason}</span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 text-xs">
        <div>
          <span className="text-slate-500">Spot age:</span>
          <span className="ml-1 font-mono text-white">{formatAge(candidate.spot_age_ms)}</span>
        </div>
        {candidate.spread_cents !== null && (
          <div>
            <span className="text-slate-500">Spread:</span>
            <span className="ml-1 font-mono text-white">{candidate.spread_cents}¢</span>
          </div>
        )}
        {candidate.data_quality_score !== null && (
          <div>
            <span className="text-slate-500">DQ:</span>
            <span className="ml-1 font-mono text-white">{candidate.data_quality_score.toFixed(2)}</span>
          </div>
        )}
        {candidate.edge_cents !== null && (
          <div>
            <span className="text-slate-500">Edge:</span>
            <span className="ml-1 font-mono text-white">{candidate.edge_cents}¢</span>
          </div>
        )}
      </div>
    </div>
  );
};

const Kalshi15mShadowModePanel: React.FC = () => {
  const { data, loading, error, refetch } = useApiData<ShadowResponse>(
    '/api/v1/kalshi/15m/shadow',
    {
      pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST,
    }
  );

  if (loading && !data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <div className="flex items-center gap-2 text-slate-400">
          <Clock className="w-4 h-4 animate-spin" />
          <span className="text-sm">Loading shadow mode data...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-slate-900 rounded-xl border border-red-800 p-6">
        <div className="flex items-center gap-2 text-red-400 mb-2">
          <XCircle className="w-4 h-4" />
          <span className="font-semibold">Shadow Mode Unavailable</span>
        </div>
        <p className="text-sm text-slate-400 mb-3">{error}</p>
        <button
          type="button"
          onClick={refetch}
          className="text-sm text-blue-400 hover:text-blue-300"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <p className="text-slate-500 text-sm">No shadow mode data available.</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold text-white">Shadow Mode Log</h3>
          <p className="text-sm text-slate-400">Blocked candidates (fail-closed)</p>
        </div>
        <div className="flex items-center gap-2">
          <TrendingDown className="w-4 h-4 text-amber-400" />
          <span className="text-sm text-slate-400">Last 60m</span>
        </div>
      </div>

      {/* Block Counters */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
          <div className="text-xs text-slate-500 mb-1">5m</div>
          <div className="font-mono text-white text-lg">{data.total_blocked_last_5m}</div>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
          <div className="text-xs text-slate-500 mb-1">15m</div>
          <div className="font-mono text-white text-lg">{data.total_blocked_last_15m}</div>
        </div>
        <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
          <div className="text-xs text-slate-500 mb-1">60m</div>
          <div className="font-mono text-white text-lg">{data.total_blocked_last_60m}</div>
        </div>
      </div>

      {/* Blocked Candidates */}
      {data.blocked_candidates.length > 0 ? (
        <div className="space-y-2">
          <h4 className="text-sm font-semibold text-slate-300 mb-2">Recent Blocks</h4>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {data.blocked_candidates.map((candidate, idx) => (
              <BlockedCandidateRow key={`${candidate.market_id}-${idx}`} candidate={candidate} />
            ))}
          </div>
        </div>
      ) : (
        <div className="text-center py-8">
          <AlertTriangle className="w-8 h-8 text-emerald-400 mx-auto mb-2" />
          <p className="text-sm text-slate-400">No blocked candidates in the last 60 minutes</p>
        </div>
      )}

      {/* Summary by Reason */}
      {Object.keys(data.summary.by_reason).length > 0 && (
        <div className="mt-4 pt-4 border-t border-slate-700">
          <h4 className="text-sm font-semibold text-slate-300 mb-2">Blocks by Reason</h4>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs">
            {Object.entries(data.summary.by_reason).map(([reason, count]) => (
              <div key={reason} className="flex justify-between">
                <span className="text-slate-500">{reason}:</span>
                <span className="font-mono text-white">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

Kalshi15mShadowModePanel.displayName = 'Kalshi15mShadowModePanel';
export default React.memo(Kalshi15mShadowModePanel);
