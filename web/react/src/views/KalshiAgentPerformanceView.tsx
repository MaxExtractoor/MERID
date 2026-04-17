/**
 * KalshiAgentPerformanceView — Agent performance tracking and calibration
 */

import { useState } from 'react';
import { Award, Download, BarChart3, Activity, Trophy, Crosshair } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS, AUTH_TOKEN_KEY} from '../config/constants';
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import KalshiModeBadge from '../components/KalshiModeBadge';

interface AgentMetrics {
  agent_id: string;
  total_fills: number;
  total_closes: number;
  total_volume_usd: number;
  win_rate: number;
  avg_pnl_per_trade: number;
  total_pnl: number;
  sharpe_ratio: number | null;
  edge_accuracy: number;
  confidence_calibration_error: number;
  last_trade_at: string | null;
}

interface PerformanceSummary {
  total_agents: number;
  total_fills: number;
  total_closes: number;
  system_win_rate: number;
  total_pnl: number;
  avg_sharpe: number;
  best_agent: string | null;
  worst_agent: string | null;
}

interface TopAgent {
  agent_id: string;
  rank: number;
  win_rate: number;
  total_pnl: number;
  edge_accuracy: number;
}

interface CalibrationEntry {
  agent_id: string;
  calibration_error: number;
  avg_confidence: number;
  brier_score: number | null;
  well_calibrated: boolean;
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return '0.0%';
  return `${((v ?? 0) * 100).toFixed(1)}%`;
}

function fmtUsd(v: number | null | undefined): string {
  if (v == null) return '$0.00';
  return (v ?? 0).toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 });
}

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`bg-slate-700/50 rounded animate-pulse ${className}`} />;
}

export default function KalshiAgentPerformanceView() {
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  
  const { data: agentsResponse, loading: loadingAgents } = useApiData<{ agents: Record<string, AgentMetrics>; count: number }>(
    API_ENDPOINTS.KALSHI_GRID_PERFORMANCE_AGENTS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );
  
  const { data: summary, loading: loadingSummary } = useApiData<PerformanceSummary>(
    API_ENDPOINTS.KALSHI_GRID_PERFORMANCE_SUMMARY,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );
  const { data: topAgentsResponse } = useApiData<{ top: TopAgent[] }>(
    API_ENDPOINTS.KALSHI_GRID_PERFORMANCE_TOP,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );
  const { data: calibrationResponse } = useApiData<{ agents: CalibrationEntry[] }>(
    API_ENDPOINTS.KALSHI_GRID_PERFORMANCE_CALIBRATION,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );
  const { data: agentDetail } = useApiData<AgentMetrics>(
    selectedAgent ? API_ENDPOINTS.KALSHI_GRID_PERFORMANCE_AGENT(selectedAgent) : '',
    { pollingInterval: selectedAgent ? DEFAULTS.POLLING_INTERVALS.SLOW : 0 }
  );

  // Convert agents object to array for rendering
  const agents = agentsResponse?.agents 
    ? Object.values(agentsResponse.agents)
    : [];

  const handleExport = async () => {
    try {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_GRID_PERFORMANCE_EXPORT}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
        },
      });
      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `kalshi-trades-${Date.now()}.csv`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
      }
    } catch {
      // Export failed — non-critical, user can retry
    }
  };

  return (
    <div className="space-y-5">
      <ExecutionGateStrip />

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2">
            <Award className="w-6 h-6 text-orange-400" />
            Agent Performance <KalshiModeBadge />
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Track win rates, edge accuracy, and calibration metrics
          </p>
        </div>
        <button type="button"
          onClick={handleExport}
          className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg flex items-center gap-2 transition-colors"
        >
          <Download className="w-4 h-4" />
          Export CSV
        </button>
      </div>

      {/* Summary Cards */}
      {loadingSummary ? (
        <div className="grid grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
              <Skeleton className="h-4 w-24 mb-2" />
              <Skeleton className="h-8 w-32" />
            </div>
          ))}
        </div>
      ) : summary ? (
        <div className="grid grid-cols-4 gap-4">
          <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
            <div className="text-xs text-slate-500 mb-1">Total Agents</div>
            <div className="text-2xl font-bold text-slate-100">{summary.total_agents}</div>
          </div>
          <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
            <div className="text-xs text-slate-500 mb-1">System Win Rate</div>
            <div className="text-2xl font-bold text-emerald-400">{fmtPct(summary.system_win_rate)}</div>
          </div>
          <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
            <div className="text-xs text-slate-500 mb-1">Total P&L</div>
            <div className={`text-2xl font-bold ${(summary.total_pnl ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {fmtUsd(summary.total_pnl)}
            </div>
          </div>
          <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
            <div className="text-xs text-slate-500 mb-1">Avg Sharpe</div>
            <div className="text-2xl font-bold text-slate-100">{summary.avg_sharpe?.toFixed(2) ?? '0.00'}</div>
          </div>
        </div>
      ) : null}

      {/* Agent Detail Panel */}
      {selectedAgent && (
        <div className="bg-slate-900/70 rounded-2xl border border-orange-500/30 overflow-hidden">
          <div className="p-4 border-b border-slate-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-orange-400" />
              <h2 className="text-sm font-semibold text-slate-200">
                {selectedAgent.replace('kalshi-', '')} — Detail
              </h2>
            </div>
            <button
              type="button"
              onClick={() => setSelectedAgent(null)}
              className="text-slate-500 hover:text-slate-300 text-xs"
            >
              ✕ Close
            </button>
          </div>
          {agentDetail ? (
            <div className="p-4 grid grid-cols-3 md:grid-cols-5 gap-3">
              {[
                { label: 'Total Fills', value: String(agentDetail.total_fills) },
                { label: 'Total Closes', value: String(agentDetail.total_closes) },
                { label: 'Win Rate', value: fmtPct(agentDetail.win_rate), highlight: agentDetail.win_rate >= 0.5 },
                { label: 'Avg P&L', value: fmtUsd(agentDetail.avg_pnl_per_trade), pos: agentDetail.avg_pnl_per_trade >= 0 },
                { label: 'Total P&L', value: fmtUsd(agentDetail.total_pnl), pos: agentDetail.total_pnl >= 0 },
                { label: 'Sharpe', value: agentDetail.sharpe_ratio != null ? (agentDetail.sharpe_ratio ?? 0).toFixed(2) : 'N/A' },
                { label: 'Edge Accuracy', value: fmtPct(agentDetail.edge_accuracy), highlight: agentDetail.edge_accuracy >= 0.6 },
                { label: 'Calib Error', value: (agentDetail.confidence_calibration_error ?? 0).toFixed(3) },
                { label: 'Volume USD', value: fmtUsd(agentDetail.total_volume_usd) },
                { label: 'Last Trade', value: agentDetail.last_trade_at ? new Date(agentDetail.last_trade_at).toLocaleString() : 'Never' },
              ].map(m => (
                <div key={m.label} className="bg-slate-800 rounded-lg p-3">
                  <p className="text-[10px] text-slate-500 mb-1">{m.label}</p>
                  <p className={`text-sm font-bold ${'pos' in m ? (m.pos ? 'text-emerald-400' : 'text-red-400') : 'highlight' in m ? (m.highlight ? 'text-emerald-400' : 'text-yellow-400') : 'text-white'}`}>
                    {m.value}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <div className="p-6 text-center text-slate-500 text-sm">Loading agent detail…</div>
          )}
        </div>
      )}

      {/* Top Performers */}
      {topAgentsResponse?.top && topAgentsResponse.top.length > 0 && (
        <div className="bg-slate-900/70 rounded-2xl border border-slate-800 overflow-hidden">
          <div className="p-4 border-b border-slate-800 flex items-center gap-2">
            <Trophy className="w-4 h-4 text-yellow-400" />
            <h2 className="text-sm font-semibold text-slate-200">Top Performers</h2>
          </div>
          <div className="divide-y divide-slate-800">
            {topAgentsResponse.top.map((a) => (
              <div key={a.agent_id} className="px-4 py-3 flex items-center gap-4">
                <span className={`text-lg font-bold w-6 text-center ${
                  a.rank === 1 ? 'text-yellow-400' : a.rank === 2 ? 'text-slate-300' : 'text-orange-400'
                }`}>#{a.rank}</span>
                <span className="font-mono text-sm text-slate-200 flex-1">{a.agent_id.replace('kalshi-', '')}</span>
                <span className={`text-sm font-medium ${ a.win_rate >= 0.5 ? 'text-emerald-400' : 'text-red-400' }`}>{fmtPct(a.win_rate)} win</span>
                <span className={`text-sm font-medium ${ a.total_pnl >= 0 ? 'text-emerald-400' : 'text-red-400' }`}>{fmtUsd(a.total_pnl)}</span>
                <span className="text-sm text-slate-400">{fmtPct(a.edge_accuracy)} edge acc</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Agent Table */}
      <div className="bg-slate-900/70 rounded-2xl border border-slate-800 overflow-hidden">
        <div className="p-5 border-b border-slate-800">
          <h2 className="text-lg font-semibold text-slate-200 flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-cyan-400" />
            Agent Metrics
          </h2>
        </div>
        
        {loadingAgents ? (
          <div className="p-5 space-y-3">
            {[...Array(5)].map((_, i) => (
              <Skeleton key={i} className="h-16" />
            ))}
          </div>
        ) : agents && agents.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-slate-800/50 text-xs text-slate-400 uppercase">
                <tr>
                  <th className="px-4 py-3 text-left">Agent</th>
                  <th className="px-4 py-3 text-center">Fills</th>
                  <th className="px-4 py-3 text-center">Closes</th>
                  <th className="px-4 py-3 text-center">Win Rate</th>
                  <th className="px-4 py-3 text-right">Avg P&L</th>
                  <th className="px-4 py-3 text-right">Total P&L</th>
                  <th className="px-4 py-3 text-center">Sharpe</th>
                  <th className="px-4 py-3 text-center">Edge Acc</th>
                  <th className="px-4 py-3 text-center">Calib Err</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {agents
                  .sort((a, b) => b.win_rate - a.win_rate)
                  .map((agent) => (
                    <tr
                      key={agent.agent_id}
                      className="hover:bg-slate-800/30 cursor-pointer transition-colors"
                      onClick={() => setSelectedAgent(agent.agent_id)}
                    >
                      <td className="px-4 py-3 text-sm font-medium text-slate-200">
                        {agent.agent_id.replace('kalshi-', '')}
                      </td>
                      <td className="px-4 py-3 text-sm text-center text-slate-300">{agent.total_fills}</td>
                      <td className="px-4 py-3 text-sm text-center text-slate-300">{agent.total_closes}</td>
                      <td className="px-4 py-3 text-sm text-center">
                        <span className={agent.win_rate >= 0.5 ? 'text-emerald-400 font-semibold' : 'text-red-400'}>
                          {fmtPct(agent.win_rate)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-right">
                        <span className={agent.avg_pnl_per_trade >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                          {fmtUsd(agent.avg_pnl_per_trade)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-right">
                        <span className={agent.total_pnl >= 0 ? 'text-emerald-400 font-semibold' : 'text-red-400'}>
                          {fmtUsd(agent.total_pnl)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-center text-slate-300">
                        {agent.sharpe_ratio != null ? (agent.sharpe_ratio ?? 0).toFixed(2) : 'N/A'}
                      </td>
                      <td className="px-4 py-3 text-sm text-center">
                        <span className={agent.edge_accuracy >= 0.6 ? 'text-emerald-400' : 'text-yellow-400'}>
                          {fmtPct(agent.edge_accuracy)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-center">
                        <span className={(agent.confidence_calibration_error ?? 0) < 0.1 ? 'text-emerald-400' : 'text-yellow-400'}>
                          {(agent.confidence_calibration_error ?? 0).toFixed(3)}
                        </span>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-10 text-center text-slate-500">
            <Activity className="w-12 h-12 mx-auto mb-3 opacity-50" />
            <p>No agent performance data available yet</p>
            <p className="text-sm mt-1">Data will appear after agents execute trades</p>
          </div>
        )}
      </div>

      {/* Calibration */}
      {calibrationResponse?.agents && calibrationResponse.agents.length > 0 && (
        <div className="bg-slate-900/70 rounded-2xl border border-slate-800 overflow-hidden">
          <div className="p-4 border-b border-slate-800 flex items-center gap-2">
            <Crosshair className="w-4 h-4 text-cyan-400" />
            <h2 className="text-sm font-semibold text-slate-200">Confidence Calibration</h2>
            <span className="ml-auto text-[10px] text-slate-500">Lower calibration error = better</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-slate-800/50 text-xs text-slate-400 uppercase">
                <tr>
                  <th className="px-4 py-3 text-left">Agent</th>
                  <th className="px-4 py-3 text-center">Calib Error</th>
                  <th className="px-4 py-3 text-center">Avg Confidence</th>
                  <th className="px-4 py-3 text-center">Brier Score</th>
                  <th className="px-4 py-3 text-center">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {calibrationResponse.agents
                  .sort((a, b) => a.calibration_error - b.calibration_error)
                  .map((c) => (
                    <tr key={c.agent_id} className="hover:bg-slate-800/30">
                      <td className="px-4 py-3 text-sm font-mono text-slate-200">{c.agent_id.replace('kalshi-', '')}</td>
                      <td className="px-4 py-3 text-sm text-center">
                        <span className={(c.calibration_error ?? 0) < 0.1 ? 'text-emerald-400' : (c.calibration_error ?? 0) < 0.2 ? 'text-yellow-400' : 'text-red-400'}>
                          {(c.calibration_error ?? 0).toFixed(3)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-center text-slate-300">{fmtPct(c.avg_confidence)}</td>
                      <td className="px-4 py-3 text-sm text-center text-slate-300">
                        {c.brier_score != null ? (c.brier_score ?? 0).toFixed(3) : '—'}
                      </td>
                      <td className="px-4 py-3 text-sm text-center">
                        {c.well_calibrated
                          ? <span className="px-2 py-0.5 rounded text-xs bg-emerald-500/20 text-emerald-400">Good</span>
                          : <span className="px-2 py-0.5 rounded text-xs bg-yellow-500/20 text-yellow-400">Needs tuning</span>
                        }
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
