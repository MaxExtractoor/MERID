/**
 * RiskDashboardView — unified risk monitoring dashboard.
 *
 * Combines:
 *   • GlobalRiskStatusPanel (drawdown bar, zone, profit-lock, kill-switch)
 *   • Per-agent table with effective size multiplier and tradeability reason
 *   • StateTransitionsLog (chronological risk state changes)
 *   • EffectiveRiskConfigPanel (read-only live config mirror)
 */

import { useState } from 'react';
import { RefreshCw, Shield, Filter, ChevronDown, ChevronRight } from 'lucide-react';
import { GlobalRiskStatusPanel } from '../components/GlobalRiskStatusPanel';
import { StateTransitionsLog } from '../components/StateTransitionsLog';
import { EffectiveRiskConfigPanel } from '../components/EffectiveRiskConfigPanel';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import type { GridAgent } from '../types/kalshi';

// ── Per-agent table ───────────────────────────────────────────────────────────

interface AgentCardListResponse {
  agent_cards: GridAgent[];
  [key: string]: unknown;
}

const effMultColor = (mult: number): string => {
  if (mult >= 0.9) return 'text-emerald-400';
  if (mult >= 0.5) return 'text-yellow-400';
  if (mult > 0)    return 'text-orange-400';
  return 'text-red-400';
}

interface AgentFilter {
  drawdownHalt: boolean;
  profitLockReduced: boolean;
}

function AgentRiskTable({ filter }: { filter: AgentFilter }) {
  const { data, loading, refetch } = useApiData<AgentCardListResponse>(
    API_ENDPOINTS.KALSHI_GRID_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );

  const agents: GridAgent[] = data?.agent_cards ?? [];

  const filtered = agents.filter(a => {
    if (filter.drawdownHalt && a.reason_not_trading !== 'drawdown_halt_active') return false;
    if (filter.profitLockReduced && (a.profit_lock_multiplier ?? 1.0) >= 1.0) return false;
    return true;
  });

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      <div className="px-5 py-3 border-b border-slate-800 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">Per-Agent Risk View</h3>
        <button
          type="button"
          onClick={refetch}
          disabled={loading}
          className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white"
          title="Refresh"
          aria-label="Refresh agents"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {filtered.length === 0 ? (
        <div className="px-5 py-8 text-center text-sm text-slate-600">
          {agents.length === 0 ? 'No agents available.' : 'No agents match the current filter.'}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-800/50">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-slate-400">Agent</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-slate-400">Asset</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-slate-400">TF</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-slate-400">Status</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-slate-400">DD mult</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-slate-400">PL mult</th>
                <th
                  className="px-4 py-2 text-right text-xs font-medium text-slate-400"
                  title="DD zone × profit-lock × size_factor"
                >
                  Eff. size
                </th>
                <th className="px-4 py-2 text-left text-xs font-medium text-slate-400">Reason (if not trading)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50">
              {filtered.map((a, i) => {
                const effMult = a.effective_size_multiplier ?? null;
                const ddMult  = a.dd_zone_multiplier        ?? null;
                const plMult  = a.profit_lock_multiplier    ?? null;
                return (
                  <tr key={`${a.name}-${i}`} className="hover:bg-slate-800/30">
                    <td className="px-4 py-2 text-xs text-slate-300 font-mono">{a.name}</td>
                    <td className="px-4 py-2 text-xs text-slate-300">{a.asset}</td>
                    <td className="px-4 py-2 text-xs text-slate-400">{a.timeframe}</td>
                    <td className="px-4 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                        a.status === 'running' ? 'text-emerald-400 bg-emerald-500/10' :
                        a.status === 'stopped' ? 'text-slate-400 bg-slate-700/50' :
                        'text-slate-500 bg-slate-700/30'
                      }`}>
                        {a.status}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right text-xs font-mono">
                      {ddMult != null ? ddMult.toFixed(3) : '—'}
                    </td>
                    <td className="px-4 py-2 text-right text-xs font-mono">
                      {plMult != null ? plMult.toFixed(3) : '—'}
                    </td>
                    <td className={`px-4 py-2 text-right text-xs font-bold font-mono ${effMult != null ? effMultColor(effMult) : 'text-slate-500'}`}>
                      {effMult != null ? `${effMult.toFixed(4)}×` : '—'}
                    </td>
                    <td className="px-4 py-2 text-xs text-slate-500 italic">
                      {a.reason_not_trading ?? '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Error budget panel ────────────────────────────────────────────────────────

function ErrorBudgetPanel() {
  const { data } = useApiData<{
    error_budget_used: number;
    error_budget_threshold: number;
    error_budget_pct: number;
    drawdown_halt_active: boolean;
  }>(API_ENDPOINTS.KALSHI_GLOBAL_RISK_STATUS, { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH });

  const used = data?.error_budget_used ?? 0;
  const threshold = data?.error_budget_threshold ?? 50;
  const pct = data?.error_budget_pct ?? 0;
  const ddHalt = data?.drawdown_halt_active ?? false;

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-4 space-y-3">
      <h3 className="text-sm font-semibold text-white">Error Budget vs Drawdown</h3>
      <div className="flex items-center gap-4">
        <div className="flex-1">
          <div className="flex justify-between text-xs mb-1">
            <span className="text-slate-400">Errors (1h)</span>
            <span className={pct >= 90 ? 'text-red-400 font-bold' : pct >= 70 ? 'text-amber-400' : 'text-slate-300'}>
              {used} / {threshold}
            </span>
          </div>
          <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${pct >= 90 ? 'bg-red-500' : pct >= 70 ? 'bg-amber-500' : 'bg-slate-500'}`}
              style={{ width: `${Math.min(100, pct)}%` }}
            />
          </div>
        </div>
        <div className={`text-xs px-2.5 py-1.5 rounded font-medium ${ddHalt ? 'text-red-400 bg-red-500/20' : 'text-slate-500 bg-slate-800/60'}`}>
          DD rejects: {ddHalt ? 'ACTIVE' : '0'}
        </div>
      </div>
      <p className="text-xs text-slate-600 italic">
        Drawdown rejects are classified LOW and exempt from the error budget.
      </p>
    </div>
  );
}

// ── Main view ─────────────────────────────────────────────────────────────────

export default function RiskDashboardView() {
  const [filter, setFilter] = useState<AgentFilter>({ drawdownHalt: false, profitLockReduced: false });
  const [configOpen, setConfigOpen] = useState(false);

  return (
    <div className="space-y-5">
      {/* Page header */}
      <div className="flex items-center gap-3">
        <Shield className="w-7 h-7 text-blue-400" />
        <div>
          <h1 className="text-2xl font-bold text-white">Risk Dashboard</h1>
          <p className="text-sm text-slate-400">
            Drawdown zones · Profit-lock · Kill-switch · State transitions
          </p>
        </div>
      </div>

      {/* Top: Global risk status panel */}
      <GlobalRiskStatusPanel />

      {/* Middle row: error budget + transitions */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <ErrorBudgetPanel />
        <StateTransitionsLog limit={20} />
      </div>

      {/* Per-agent table with filters */}
      <div className="space-y-3">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-1.5 text-sm text-slate-400">
            <Filter className="w-4 h-4" />
            Quick filters:
          </div>
          <button
            type="button"
            onClick={() => setFilter(f => ({ ...f, drawdownHalt: !f.drawdownHalt }))}
            className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
              filter.drawdownHalt
                ? 'bg-red-500/20 border-red-500/50 text-red-400'
                : 'bg-slate-800 border-slate-700 text-slate-400 hover:text-white'
            }`}
          >
            Affected by drawdown halt
          </button>
          <button
            type="button"
            onClick={() => setFilter(f => ({ ...f, profitLockReduced: !f.profitLockReduced }))}
            className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
              filter.profitLockReduced
                ? 'bg-amber-500/20 border-amber-500/50 text-amber-400'
                : 'bg-slate-800 border-slate-700 text-slate-400 hover:text-white'
            }`}
          >
            Reduced by profit-lock
          </button>
          {(filter.drawdownHalt || filter.profitLockReduced) && (
            <button
              type="button"
              onClick={() => setFilter({ drawdownHalt: false, profitLockReduced: false })}
              className="text-xs px-3 py-1.5 rounded-lg border border-slate-700 text-slate-500 hover:text-white"
            >
              Clear filters
            </button>
          )}
        </div>

        <AgentRiskTable filter={filter} />
      </div>

      {/* Collapsible effective config */}
      <div>
        <button
          type="button"
          onClick={() => setConfigOpen(o => !o)}
          className="flex items-center gap-2 text-sm text-slate-400 hover:text-white mb-3 transition-colors"
        >
          {configOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          Effective risk settings (live)
        </button>
        {configOpen && <EffectiveRiskConfigPanel />}
      </div>
    </div>
  );
}
