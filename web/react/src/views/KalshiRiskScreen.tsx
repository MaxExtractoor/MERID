/**
 * KalshiRiskScreen — Production risk & health dashboard for Kalshi trading.
 *
 * Integrates with:
 * - useKalshiRiskStream (real-time alerts)
 * - RISK_SUMMARY (overall risk metrics)
 * - RISK_ALERTS (polled alerts)
 * - SYSTEM_HEALTH (connectivity, latency)
 */

import { useMemo, useState, useCallback } from 'react';
import { useApiData } from '../hooks/useApiData';
import { useKalshiRiskStream } from '../hooks/useKalshiRiskStream';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { authHeaders } from '../api/auth';
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import KalshiPnlChart from '../components/KalshiPnlChart';
import KalshiBankrollPanel from '../components/KalshiBankrollPanel';
import { fmtTimestamp } from '../utils/formatters';

interface RiskSummary {
  overall_risk_level: 'low' | 'medium' | 'high';
  margin_usage_pct: number;
  position_risk_amount: number;
  position_risk_pct: number;
  leverage_ratio: number;
  connectivity_status: {
    rest_api: { status: 'connected' | 'degraded' | 'disconnected'; latency_ms: number };
    ws_risk: { status: 'connected' | 'degraded' | 'disconnected'; latency_ms: number };
    ws_positions: { status: 'connected' | 'degraded' | 'disconnected'; latency_ms: number };
    ws_orderbook: { status: 'connected' | 'degraded' | 'disconnected'; latency_ms: number };
  };
}

interface RiskAlert {
  id: string;
  timestamp: string;
  severity: 'info' | 'warning' | 'critical';
  type: string;
  description: string;
  source: string;
  status: 'active' | 'acknowledged' | 'resolved';
}

const RISK_LEVEL_COLORS = {
  low: 'text-green-400 border-green-500',
  medium: 'text-yellow-400 border-yellow-500',
  high: 'text-red-400 border-red-500',
};

const SEVERITY_COLORS = {
  info: 'text-blue-400',
  warning: 'text-yellow-400',
  critical: 'text-red-400',
};

const STATUS_COLORS = {
  active: 'text-red-400',
  acknowledged: 'text-yellow-400',
  resolved: 'text-green-400',
};

export default function KalshiRiskScreen() {
  const { alerts: wsAlerts } = useKalshiRiskStream();
  const { data: riskSummary, loading: loadingSummary } = useApiData<RiskSummary>(
    API_ENDPOINTS.RISK_SUMMARY,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );
  const { data: polledAlerts, refetch: refetchAlerts } = useApiData<{ alerts: RiskAlert[] }>(
    API_ENDPOINTS.RISK_ALERTS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );

  const [acknowledging, setAcknowledging] = useState<string | null>(null);
  const [acknowledgingAll, setAcknowledgingAll] = useState(false);
  const [ackError, setAckError] = useState<string | null>(null);
  const ALERTS_PAGE_SIZE = 50;
  const [alertsPage, setAlertsPage] = useState(1);

  // Combine WS and polled alerts, deduplicate by ID
  const allAlerts = useMemo(() => {
    const alertMap = new Map<string, RiskAlert>();
    polledAlerts?.alerts?.forEach(alert => { alertMap.set(alert.id, alert); });
    wsAlerts.forEach(wsAlert => {
      // Normalize WS alert ID to match polled alert ID format for reliable deduplication.
      // Polled alerts use string IDs from the backend; WS alerts use prefixed epoch IDs.
      // Prefer the polled entry if it already exists (it may have a resolved status).
      if (!alertMap.has(wsAlert.id)) {
        alertMap.set(wsAlert.id, {
          id: wsAlert.id,
          timestamp: wsAlert.ts,
          severity: wsAlert.level === 'error' ? 'critical' : wsAlert.level,
          type: wsAlert.type,
          description: wsAlert.message,
          source: wsAlert.source,
          status: 'active',
        });
      }
    });
    return Array.from(alertMap.values()).sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  }, [wsAlerts, polledAlerts]);

  const realAlertsTotalPages = Math.max(1, Math.ceil(allAlerts.length / ALERTS_PAGE_SIZE));
  // BUG-006 fix: clamp page when alert count shrinks
  const clampedAlertsPage = Math.min(alertsPage, realAlertsTotalPages);
  // Only show "Acknowledge All" when there is at least one active alert to acknowledge
  const activeCount = allAlerts.filter(a => a.status === 'active').length;
  const hasActiveAlerts = activeCount > 0;
  const pagedAlerts = useMemo(
    () => allAlerts.slice((clampedAlertsPage - 1) * ALERTS_PAGE_SIZE, clampedAlertsPage * ALERTS_PAGE_SIZE),
    [allAlerts, clampedAlertsPage]
  );

  const handleAcknowledgeAlert = useCallback(async (alertId: string) => {
    setAcknowledging(alertId);
    setAckError(null);
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.RISK_ALERT_ACKNOWLEDGE(alertId)}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      refetchAlerts();
    } catch (err) {
      setAckError(err instanceof Error ? err.message : 'Failed to acknowledge alert');
    } finally {
      setAcknowledging(null);
    }
  }, [refetchAlerts]);

  const handleAcknowledgeAll = useCallback(async () => {
    setAcknowledgingAll(true);
    setAckError(null);
    try {
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.RISK_ALERTS_ACKNOWLEDGE_ALL}`, {
        method: 'POST',
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      refetchAlerts();
    } catch (err) {
      setAckError(err instanceof Error ? err.message : 'Failed to acknowledge all alerts');
    } finally {
      setAcknowledgingAll(false);
    }
  }, [refetchAlerts]);

  if (loadingSummary) {
    return (
      <div className="p-6">
        <div className="animate-pulse space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="bg-slate-800 rounded-lg p-4 h-24" />
            ))}
          </div>
          <div className="bg-slate-800 rounded-lg p-6 h-64" />
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <ExecutionGateStrip />

      {/* Continuous trader bankroll */}
      <KalshiBankrollPanel />

      {/* Risk Overview Dashboard */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className={`bg-slate-900 rounded-lg p-4 border-l-4 ${RISK_LEVEL_COLORS[riskSummary?.overall_risk_level || 'low']}`}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-slate-400">Overall Risk</span>
            <span className={`w-2 h-2 rounded-full ${
              riskSummary?.overall_risk_level === 'low' ? 'bg-green-400' :
              riskSummary?.overall_risk_level === 'medium' ? 'bg-yellow-400' : 'bg-red-400'
            }`} />
          </div>
          <div className={`text-2xl font-bold ${
            riskSummary?.overall_risk_level === 'low' ? 'text-green-400' :
            riskSummary?.overall_risk_level === 'medium' ? 'text-yellow-400' : 'text-red-400'
          }`}>
            {(riskSummary?.overall_risk_level ?? 'unknown').toUpperCase()}
          </div>
          <div className="text-xs text-slate-500">System risk assessment</div>
        </div>

        <div className="bg-slate-900 rounded-lg p-4 border-l-4 border-yellow-500">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-slate-400">Margin Usage</span>
            <span className={`w-2 h-2 rounded-full ${
              (riskSummary?.margin_usage_pct || 0) > 80 ? 'bg-red-400' :
              (riskSummary?.margin_usage_pct || 0) > 60 ? 'bg-yellow-400' : 'bg-green-400'
            }`} />
          </div>
          <div className={`text-2xl font-bold ${
            (riskSummary?.margin_usage_pct || 0) > 80 ? 'text-red-400' :
            (riskSummary?.margin_usage_pct || 0) > 60 ? 'text-yellow-400' : 'text-green-400'
          }`}>
            {riskSummary?.margin_usage_pct?.toFixed(1) || '0.0'}%
          </div>
          <div className="text-xs text-slate-500">
            {(riskSummary?.margin_usage_pct || 0) > 80 ? 'Near limit' : 'Within limits'}
          </div>
        </div>

        <div className={`bg-slate-900 rounded-lg p-4 border-l-4 ${
          (riskSummary?.position_risk_pct || 0) > 10 ? 'border-red-500' :
          (riskSummary?.position_risk_pct || 0) > 5 ? 'border-yellow-500' : 'border-green-500'
        }`}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-slate-400">Position Risk</span>
            <span className={`w-2 h-2 rounded-full ${
              (riskSummary?.position_risk_pct || 0) > 10 ? 'bg-red-400' :
              (riskSummary?.position_risk_pct || 0) > 5 ? 'bg-yellow-400' : 'bg-green-400'
            }`} />
          </div>
          <div className={`text-2xl font-bold ${
            (riskSummary?.position_risk_pct || 0) > 10 ? 'text-red-400' :
            (riskSummary?.position_risk_pct || 0) > 5 ? 'text-yellow-400' : 'text-green-400'
          }`}>
            ${(riskSummary?.position_risk_amount || 0).toLocaleString()}
          </div>
          <div className="text-xs text-slate-500">
            {(riskSummary?.position_risk_pct || 0).toFixed(1)}% of equity
          </div>
        </div>

        <div className={`bg-slate-900 rounded-lg p-4 border-l-4 ${
          (riskSummary?.leverage_ratio || 0) > 3 ? 'border-red-500' :
          (riskSummary?.leverage_ratio || 0) > 2 ? 'border-yellow-500' : 'border-green-500'
        }`}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-slate-400">Leverage</span>
            <span className={`w-2 h-2 rounded-full ${
              (riskSummary?.leverage_ratio || 0) > 3 ? 'bg-red-400' :
              (riskSummary?.leverage_ratio || 0) > 2 ? 'bg-yellow-400' : 'bg-green-400'
            }`} />
          </div>
          <div className={`text-2xl font-bold ${
            (riskSummary?.leverage_ratio || 0) > 3 ? 'text-red-400' :
            (riskSummary?.leverage_ratio || 0) > 2 ? 'text-yellow-400' : 'text-green-400'
          }`}>
            {(riskSummary?.leverage_ratio || 0).toFixed(1)}x
          </div>
          <div className="text-xs text-slate-500">
            {(riskSummary?.leverage_ratio || 0) > 3 ? 'High leverage' : 'Within limits'}
          </div>
        </div>
      </div>

      {/* System Health Panel */}
      <div className="bg-slate-900 rounded-lg p-6">
        <h2 className="text-lg font-semibold mb-4 text-slate-100">Kalshi Connectivity</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {Object.entries(riskSummary?.connectivity_status || {}).map(([key, status]) => (
            <div key={key} className="bg-slate-800 rounded-lg p-4">
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm font-medium text-slate-200 capitalize">
                  {key.replace(/_/g, ' ')}
                </span>
                <span className={`w-2 h-2 rounded-full ${
                  status.status === 'connected' ? 'bg-green-400' :
                  status.status === 'degraded' ? 'bg-yellow-400' : 'bg-red-400'
                }`} />
              </div>
              <div className={`text-sm ${
                status.status === 'connected' ? 'text-green-400' :
                status.status === 'degraded' ? 'text-yellow-400' : 'text-red-400'
              }`}>
                {status.status} ({status.latency_ms}ms)
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Risk Alerts Table */}
      <div className="bg-slate-900 rounded-lg overflow-hidden">
        <div className="p-4 border-b border-slate-800 flex items-center justify-between gap-3 flex-wrap">
          <h2 className="text-lg font-semibold text-slate-100">
            Risk Alerts ({allAlerts.length})
          </h2>
          <div className="flex items-center gap-2 ml-auto flex-wrap">
            {realAlertsTotalPages > 1 && (
              <div className="flex items-center gap-1 text-xs text-slate-400">
                <button type="button" onClick={() => setAlertsPage(p => Math.max(1, p - 1))} disabled={clampedAlertsPage === 1}
                  className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-30" aria-label="Previous alerts page">
                  ‹
                </button>
                <span>{clampedAlertsPage}/{realAlertsTotalPages}</span>
                <button type="button" onClick={() => setAlertsPage(p => Math.min(realAlertsTotalPages, p + 1))} disabled={clampedAlertsPage === realAlertsTotalPages}
                  className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-30" aria-label="Next alerts page">
                  ›
                </button>
              </div>
            )}
            {ackError && (
              <div className="flex items-center gap-2 px-3 py-1 rounded bg-red-900/50 border border-red-700 text-red-300 text-xs">
                <span>{ackError}</span>
                <button type="button" onClick={() => setAckError(null)} className="text-red-400 hover:text-red-200">✕</button>
              </div>
            )}
            {hasActiveAlerts && (
              <button
                type="button"
                onClick={handleAcknowledgeAll}
                disabled={acknowledgingAll}
                title={`Acknowledge all ${activeCount} active alert${activeCount !== 1 ? 's' : ''}`}
                className="px-3 py-1 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded text-sm disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {acknowledgingAll ? 'Acknowledging…' : `Acknowledge All (${activeCount})`}
              </button>
            )}
          </div>
        </div>
        {allAlerts.length > 50 && (
          <div className="flex items-center gap-2 px-3 py-2 mb-2 rounded-lg bg-amber-900/40 border border-amber-600/50 text-amber-300 text-xs font-medium sticky top-0 z-10">
            <span>⚠ {allAlerts.length} alerts active — critical alerts may be on later pages. Review all pages carefully.</span>
          </div>
        )}
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-slate-800">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase">Timestamp</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase">Severity</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase">Type</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase">Description</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase">Source</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {pagedAlerts.map((alert) => (
                <tr key={alert.id} className="hover:bg-slate-800/50">
                  <td className="px-4 py-3 text-sm text-slate-300">
                    {fmtTimestamp(alert.timestamp)}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <span className={`px-2 py-1 rounded text-xs font-medium ${SEVERITY_COLORS[alert.severity]} bg-current/10`}>
                      {alert.severity}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-300 capitalize">
                    {alert.type.replace('_', ' ')}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-300 max-w-xs truncate">
                    {alert.description}
                  </td>
                  <td className="px-4 py-3 text-sm text-slate-300">
                    {alert.source}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <span className={`px-2 py-1 rounded text-xs font-medium ${STATUS_COLORS[alert.status]} bg-current/10`}>
                      {alert.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {alert.status === 'active' && (
                      <button
                        type="button"
                        onClick={() => handleAcknowledgeAlert(alert.id)}
                        disabled={acknowledging === alert.id || acknowledgingAll}
                        className="px-2 py-1 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded text-xs disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        {acknowledging === alert.id ? '…' : 'Ack'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {allAlerts.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-slate-500">
                    No risk alerts at this time
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* PnL / Equity curve over time */}
      <div className="bg-slate-900 rounded-lg p-6">
        <h2 className="text-lg font-semibold mb-4 text-slate-100">PnL &amp; Equity Over Time</h2>
        <KalshiPnlChart riskAlerts={allAlerts.filter(a => a.severity === 'critical').map(a => ({ ts: a.timestamp, title: a.type, severity: a.severity }))} />
      </div>
    </div>
  );
}
