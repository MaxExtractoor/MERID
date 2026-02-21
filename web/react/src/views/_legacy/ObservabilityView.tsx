/**
 * ObservabilityView — System observability dashboard.
 *
 * Shows:
 *   - Overall system status badge
 *   - Alert rules grid with firing/ok indicators
 *   - Health sections with status gauges
 *   - Firing alerts detail panel
 *   - Uptime and stats
 */

import { useState, useMemo } from 'react';
import { useObservability, type AlertRule, type HealthSection } from '../hooks/useObservability';
import { useLLMObservability } from '../hooks/useLLMObservability';
import { useSLOMetrics, useSportsSLO } from '../hooks/useSLOMetrics';
import { useFeatureFlags } from '../config/featureFlags';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import SLOBurndownChart from '../components/charts/SLOBurndownChart';
import SLOStatusCards from '../components/charts/SLOStatusCards';
import {
  Eye, AlertTriangle, CheckCircle, XCircle,
  RefreshCw, Shield, Activity, Clock,
  Bell, BellOff, ChevronDown, ChevronRight,
  HeartPulse, BarChart3, Zap, Gauge, Timer,
  Bot, Cpu, ShieldCheck, Wrench, LayoutGrid, ClipboardList,
} from 'lucide-react';

/* ── Tooltip ──────────────────────────────────────────────── */

function Tip({ text, children }: { text: string; children: React.ReactNode }) {
  return (
    <span className="relative group cursor-help">
      {children}
      <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 text-xs bg-slate-800 text-slate-200 rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-50 border border-slate-700">
        {text}
      </span>
    </span>
  );
}

/* ── Status helpers ───────────────────────────────────────── */

const STATUS_CONFIG: Record<string, { label: string; color: string; bg: string; Icon: React.ElementType }> = {
  healthy:   { label: 'Healthy',   color: 'text-emerald-400', bg: 'bg-emerald-500/20 border-emerald-500/30', Icon: CheckCircle },
  degraded:  { label: 'Degraded',  color: 'text-amber-400',   bg: 'bg-amber-500/20 border-amber-500/30',   Icon: AlertTriangle },
  unhealthy: { label: 'Unhealthy', color: 'text-rose-400',    bg: 'bg-rose-500/20 border-rose-500/30',     Icon: XCircle },
  unknown:   { label: 'Unknown',   color: 'text-slate-400',   bg: 'bg-slate-500/20 border-slate-500/30',   Icon: Activity },
};

const SEV_COLORS: Record<string, { dot: string; text: string; bg: string }> = {
  critical: { dot: 'bg-rose-500', text: 'text-rose-400', bg: 'bg-rose-500/10 border-rose-500/20' },
  warning:  { dot: 'bg-amber-500', text: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/20' },
  info:     { dot: 'bg-blue-500', text: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20' },
};

function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

/* ── Alert rule card ──────────────────────────────────────── */

function AlertRuleCard({ rule }: { rule: AlertRule }) {
  const [expanded, setExpanded] = useState(false);
  const sev = SEV_COLORS[rule.severity] ?? SEV_COLORS.info;

  return (
    <div
      className={`border rounded-xl p-3 transition-all cursor-pointer hover:border-slate-600/50 ${
        rule.firing ? sev.bg : 'bg-slate-800/40 border-slate-700/50'
      }`}
      onClick={() => setExpanded(!expanded)}
     role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); (() => setExpanded(!expanded))(); } }}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          {rule.firing ? (
            <Bell className={`w-4 h-4 ${sev.text} animate-pulse shrink-0`} />
          ) : (
            <BellOff className="w-4 h-4 text-slate-600 shrink-0" />
          )}
          <span className={`text-sm font-medium truncate ${rule.firing ? 'text-white' : 'text-slate-400'}`}>
            {rule.name}
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className={`px-2 py-0.5 text-xs rounded-full ${sev.text} ${rule.firing ? sev.bg : 'bg-slate-700/30'}`}>
            {rule.severity}
          </span>
          <span className={`w-2 h-2 rounded-full ${rule.firing ? sev.dot + ' animate-pulse' : 'bg-emerald-500'}`} />
        </div>
      </div>

      {expanded && (
        <div className="mt-2 pt-2 border-t border-slate-700/30 text-xs animate-in fade-in duration-200">
          <p className="text-slate-300 mb-2">{rule.description}</p>
          {rule.detail && Object.keys(rule.detail).length > 0 && (
            <div className="grid grid-cols-2 gap-1">
              {Object.entries(rule.detail).map(([k, v]) => (
                <div key={k}>
                  <span className="text-slate-500">{k}: </span>
                  <span className="text-white">{String(v)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Health section card ──────────────────────────────────── */

function HealthSectionCard({ name, section }: { name: string; section: HealthSection }) {
  const cfg = STATUS_CONFIG[section.status] ?? STATUS_CONFIG.unknown;
  const StatusIcon = cfg.Icon;

  return (
    <div className={`border rounded-xl p-4 ${cfg.bg} transition-all`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-white capitalize">{name.replace(/_/g, ' ')}</span>
        <div className="flex items-center gap-1.5">
          <StatusIcon className={`w-4 h-4 ${cfg.color}`} />
          <span className={`text-xs font-medium ${cfg.color}`}>{cfg.label}</span>
        </div>
      </div>
      {section.metrics && Object.keys(section.metrics).length > 0 && (
        <div className="grid grid-cols-2 gap-1 text-xs">
          {Object.entries(section.metrics).slice(0, 6).map(([k, v]) => (
            <div key={k}>
              <span className="text-slate-500">{k.replace(/_/g, ' ')}: </span>
              <span className="text-slate-300">{typeof v === 'number' ? v.toLocaleString() : String(v)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Main View ────────────────────────────────────────────── */

export default function ObservabilityView() {
  const { kalshiOnly } = useFeatureFlags();
  const { data, loading, error, refresh } = useObservability();
  const { data: llmData } = useLLMObservability(30_000);
  const { data: sloData } = useSLOMetrics(20_000);
  const { data: sportsSlo } = useSportsSLO(kalshiOnly ? 0 : 30_000);
  const { data: kalshiHealth } = useApiData<any>(
    kalshiOnly ? API_ENDPOINTS.KALSHI_GRID_HEALTH : '',
    { pollingInterval: kalshiOnly ? DEFAULTS.POLLING_INTERVALS.STANDARD : 0 }
  );
  const [filterFiring, setFilterFiring] = useState(false);
  const [showSLO, setShowSLO] = useState(true);

  const filteredAlerts = useMemo(() => {
    if (!data || !data.alerts || !Array.isArray(data.alerts)) return [];
    if (filterFiring) return data.alerts.filter(a => a.firing);
    return data.alerts;
  }, [data, filterFiring]);

  const firingBySeverity = useMemo(() => {
    if (!data || !data.alerts || !Array.isArray(data.alerts)) {
      return { critical: 0, warning: 0, info: 0 };
    }
    const counts = { critical: 0, warning: 0, info: 0 };
    data.alerts.filter(a => a.firing).forEach(a => {
      if (a.severity in counts) counts[a.severity as keyof typeof counts]++;
    });
    return counts;
  }, [data]);

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3">
          <div className="w-12 h-12 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-slate-400 text-sm">Loading observability...</span>
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="p-6">
        <div className="bg-rose-900/20 border border-rose-500/30 rounded-xl p-4">
          <h3 className="text-rose-400 font-semibold mb-1">Observability API Error</h3>
          <p className="text-rose-300 text-sm">{error}</p>
        </div>
      </div>
    );
  }

  const overallCfg = STATUS_CONFIG[data?.status ?? 'unknown'];
  const OverallIcon = overallCfg.Icon;
  const healthSections = Object.entries(data?.health_sections ?? {});

  const topTools = (llmData?.toolsSummary.by_tool ?? {});
  const guardrailTypes = (llmData?.guardrailsSummary.by_type ?? {});
  const roleCounts = (llmData?.tracesSummary.by_role ?? {});
  const toolEntries = Object.entries(topTools)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);
  const guardrailEntries = Object.entries(guardrailTypes)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);
  const roleEntries = Object.entries(roleCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white flex items-center gap-3">
            <Eye className="w-8 h-8 text-emerald-400" />
            System Observability
          </h1>
          <p className="text-slate-400 mt-1">Alert rules, health sections, and SLO monitoring</p>
        </div>
        <div className="flex items-center gap-3">
          <Tip text="Overall system status derived from alert rules and health checks">
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border ${overallCfg.bg}`}>
              <OverallIcon className={`w-4 h-4 ${overallCfg.color}`} />
              <span className={`text-sm font-medium ${overallCfg.color}`}>{overallCfg.label}</span>
            </div>
          </Tip>
          <button type="button" onClick={refresh} className="p-2 hover:bg-slate-800 rounded-lg transition-colors" title="Refresh" aria-label="Refresh">
            <RefreshCw className={`w-4 h-4 text-slate-400 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <Tip text="Total number of configured alert rules">
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-1"><Shield className="w-4 h-4 text-blue-400" /><span className="text-xs text-slate-400">Total Rules</span></div>
            <div className="text-2xl font-bold text-white">{data?.total_rules ?? 0}</div>
          </div>
        </Tip>
        <Tip text="Alert rules currently in firing state">
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-1"><Bell className="w-4 h-4 text-amber-400" /><span className="text-xs text-slate-400">Firing</span></div>
            <div className="text-2xl font-bold text-white">{data?.firing_count ?? 0}</div>
          </div>
        </Tip>
        <Tip text="Critical severity alerts currently firing">
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-1"><Zap className="w-4 h-4 text-rose-400" /><span className="text-xs text-slate-400">Critical</span></div>
            <div className="text-2xl font-bold text-white">{firingBySeverity.critical}</div>
          </div>
        </Tip>
        <Tip text="Warning severity alerts currently firing">
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-1"><AlertTriangle className="w-4 h-4 text-amber-400" /><span className="text-xs text-slate-400">Warnings</span></div>
            <div className="text-2xl font-bold text-white">{firingBySeverity.warning}</div>
          </div>
        </Tip>
        <Tip text="System uptime since last restart">
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-1"><Clock className="w-4 h-4 text-emerald-400" /><span className="text-xs text-slate-400">Uptime</span></div>
            <div className="text-2xl font-bold text-white">{formatUptime(data?.uptime_s ?? 0)}</div>
          </div>
        </Tip>
      </div>

      {/* Health sections */}
      {healthSections.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
            <HeartPulse className="w-4 h-4 text-emerald-400" /> Health Sections
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {healthSections.map(([name, section]) => (
              <HealthSectionCard key={name} name={name} section={section} />
            ))}
          </div>
        </div>
      )}

      {/* ── SLO Metrics & Error Budget ──────────────────────────── */}
      <div className="border-t border-slate-700/40 pt-6">
        <button type="button"
          onClick={() => setShowSLO((v) => !v)}
          className="flex items-center gap-2 text-sm font-semibold text-white mb-4 hover:text-blue-400 transition-colors"
        >
          {showSLO ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          <Gauge className="w-4 h-4 text-blue-400" />
          SLO Metrics &amp; Error Budget
          {sloData && (
            <span className="text-xs font-normal text-slate-500 ml-2">
              {sloData.subsystems.length} subsystems · {sloData.error_budget_pct}% budget remaining
            </span>
          )}
        </button>

        {showSLO && sloData && (
          <div className="space-y-5">
            {/* SLO Status Cards */}
            <SLOStatusCards
              subsystems={sloData.subsystems}
              overallOk={sloData.overall_ok}
              overallP95Ms={sloData.overall_p95_ms}
              overallThresholdMs={sloData.overall_threshold_ms}
              errorBudgetPct={sloData.error_budget_pct}
            />

            {/* Burn-down chart */}
            <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
              <h4 className="text-xs font-semibold text-white mb-3 flex items-center gap-2">
                <Timer className="w-3.5 h-3.5 text-amber-400" />
                Error Budget Burn-Down
              </h4>
              <SLOBurndownChart data={sloData.burn_history} height={220} />
            </div>

            {/* Sports SLO mini-card - hide in Kalshi-only mode */}
            {sportsSlo && !kalshiOnly && (
              <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
                <h4 className="text-xs font-semibold text-white mb-3 flex items-center gap-2">
                  <Zap className="w-3.5 h-3.5 text-emerald-400" />
                  Live Betting SLO
                </h4>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
                  <div>
                    <div className={`text-xl font-bold ${sportsSlo.p95_acceptance_latency_ms <= sportsSlo.slo_target_ms ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {sportsSlo.p95_acceptance_latency_ms}ms
                    </div>
                    <div className="text-[10px] text-slate-500">P95 Latency (target: {sportsSlo.slo_target_ms}ms)</div>
                  </div>
                  <div>
                    <div className="text-xl font-bold text-white">{(sportsSlo.acceptance_rate * 100).toFixed(1)}%</div>
                    <div className="text-[10px] text-slate-500">Acceptance Rate</div>
                  </div>
                  <div>
                    <div className="text-xl font-bold text-amber-400">{sportsSlo.slo_breaches}</div>
                    <div className="text-[10px] text-slate-500">SLO Breaches</div>
                  </div>
                  <div>
                    <div className={`text-xl font-bold ${sportsSlo.budget_remaining_pct >= 80 ? 'text-emerald-400' : sportsSlo.budget_remaining_pct >= 50 ? 'text-amber-400' : 'text-rose-400'}`}>
                      {sportsSlo.budget_remaining_pct}%
                    </div>
                    <div className="text-[10px] text-slate-500">Budget Remaining</div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Kalshi Agent Grid Health ───────────────────────────────── */}
      {kalshiOnly && kalshiHealth && (
        <div className="border-t border-slate-700/40 pt-6">
          <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
            <LayoutGrid className="w-4 h-4 text-orange-400" /> Kalshi Agent Grid
          </h3>
          
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className={`bg-slate-800/60 border rounded-xl p-4 ${
              kalshiHealth.status === 'healthy' ? 'border-emerald-500/30' :
              kalshiHealth.status === 'degraded' ? 'border-amber-500/30' :
              'border-red-500/30'
            }`}>
              <div className="flex items-center gap-2 mb-1">
                <Activity className={`w-4 h-4 ${
                  kalshiHealth.status === 'healthy' ? 'text-emerald-400' :
                  kalshiHealth.status === 'degraded' ? 'text-amber-400' :
                  'text-red-400'
                }`} />
                <span className="text-xs text-slate-400">Grid Status</span>
              </div>
              <div className={`text-2xl font-bold ${
                kalshiHealth.status === 'healthy' ? 'text-emerald-400' :
                kalshiHealth.status === 'degraded' ? 'text-amber-400' :
                'text-red-400'
              }`}>
                {kalshiHealth.status}
              </div>
              <div className="text-[10px] text-slate-500">
                {kalshiHealth.agents?.running || 0}/{kalshiHealth.agents?.total || 0} running
              </div>
            </div>

            <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-1">
                <BarChart3 className="w-4 h-4 text-blue-400" />
                <span className="text-xs text-slate-400">Total Cycles</span>
              </div>
              <div className="text-2xl font-bold text-white">
                {kalshiHealth.activity?.total_cycles || 0}
              </div>
              <div className="text-[10px] text-slate-500">
                Avg: {kalshiHealth.activity?.avg_cycles_per_agent || 0}/agent
              </div>
            </div>

            <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-1">
                <ClipboardList className="w-4 h-4 text-cyan-400" />
                <span className="text-xs text-slate-400">Orders Placed</span>
              </div>
              <div className="text-2xl font-bold text-white">
                {kalshiHealth.activity?.total_orders || 0}
              </div>
            </div>

            <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-1">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                <span className="text-xs text-slate-400">Issues</span>
              </div>
              <div className={`text-2xl font-bold ${
                (kalshiHealth.agents?.with_errors || 0) > 0 ? 'text-amber-400' : 'text-emerald-400'
              }`}>
                {kalshiHealth.agents?.with_errors || 0}
              </div>
              <div className="text-[10px] text-slate-500">
                {kalshiHealth.agents?.stale?.length || 0} stale
              </div>
            </div>
          </div>

          {kalshiHealth.agents?.stale?.length > 0 && (
            <div className="mt-4 bg-amber-900/20 border border-amber-500/30 rounded-xl p-4">
              <h4 className="text-xs font-semibold text-amber-400 mb-2">Stale Agents (no cycle in 5+ min)</h4>
              <div className="flex flex-wrap gap-2">
                {kalshiHealth.agents.stale.map((agent: string) => (
                  <span key={agent} className="px-2 py-1 bg-amber-500/10 text-amber-300 text-xs rounded">
                    {agent}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── LLM & Tools ──────────────────────────────────────────── */}
      {!kalshiOnly && (
        <div className="border-t border-slate-700/40 pt-6">
          <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
            <Bot className="w-4 h-4 text-emerald-400" /> LLM &amp; Tools
          </h3>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-1">
              <Cpu className="w-4 h-4 text-blue-400" />
              <span className="text-xs text-slate-400">Calls (24h)</span>
            </div>
            <div className="text-2xl font-bold text-white">
              {llmData?.tracesSummary.traces_window ?? 0}
            </div>
            <div className="text-[10px] text-slate-500">Total: {llmData?.tracesSummary.total_traces ?? 0}</div>
            {roleEntries.length > 0 && (
              <div className="mt-2 space-y-1 text-[10px] text-slate-500">
                {roleEntries.map(([role, count]) => (
                  <div key={role} className="flex justify-between">
                    <span className="capitalize">{role.replace(/_/g, ' ')}</span>
                    <span className="text-slate-300">{count}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-1">
              <Wrench className="w-4 h-4 text-amber-400" />
              <span className="text-xs text-slate-400">Error Rate</span>
            </div>
            <div className="text-2xl font-bold text-white">
              {((llmData?.tracesSummary.error_rate ?? 0) * 100).toFixed(1)}%
            </div>
            <div className="text-[10px] text-slate-500">Failed traces</div>
          </div>
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-1">
              <ShieldCheck className="w-4 h-4 text-rose-400" />
              <span className="text-xs text-slate-400">Avg Latency</span>
            </div>
            <div className="text-2xl font-bold text-white">
              {llmData?.tracesSummary.avg_latency_ms ?? 0}ms
            </div>
            <div className="text-[10px] text-slate-500">Per request</div>
          </div>
          <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-1">
              <Activity className="w-4 h-4 text-emerald-400" />
              <span className="text-xs text-slate-400">Tokens (24h)</span>
            </div>
            <div className="text-2xl font-bold text-white">
              {llmData?.tracesSummary.tokens_window ?? 0}
            </div>
            <div className="text-[10px] text-slate-500">Prompt + completion</div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
            <h4 className="text-xs font-semibold text-white mb-3">Top Tool Calls</h4>
            {toolEntries.length === 0 ? (
              <div className="text-xs text-slate-500">No tool calls recorded.</div>
            ) : (
              <div className="space-y-2">
                {toolEntries.map(([tool, count]) => (
                  <div key={tool} className="flex items-center justify-between text-xs">
                    <span className="text-slate-300 truncate">{tool}</span>
                    <span className="text-slate-100 font-semibold">{count}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
            <h4 className="text-xs font-semibold text-white mb-3">Guardrail Events</h4>
            {guardrailEntries.length === 0 ? (
              <div className="text-xs text-slate-500">No guardrail events recorded.</div>
            ) : (
              <div className="space-y-2">
                {guardrailEntries.map(([eventType, count]) => (
                  <div key={eventType} className="flex items-center justify-between text-xs">
                    <span className="text-slate-300 truncate">{eventType}</span>
                    <span className="text-slate-100 font-semibold">{count}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
        </div>
      )}

      {/* Alert rules */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-white flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-blue-400" /> Alert Rules ({filteredAlerts.length})
          </h3>
          <button type="button"
            onClick={() => setFilterFiring(!filterFiring)}
            className={`px-3 py-1 text-xs rounded-lg transition-colors ${
              filterFiring ? 'bg-amber-600 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
            }`}
          >
            {filterFiring ? 'Showing Firing Only' : 'Show All'}
          </button>
        </div>

        {filteredAlerts.length === 0 ? (
          <div className="text-center py-12 text-slate-500">
            <CheckCircle className="w-12 h-12 mx-auto mb-3 opacity-30" />
            <p>{filterFiring ? 'No alerts currently firing' : 'No alert rules configured'}</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {filteredAlerts.map((rule, i) => (
              <AlertRuleCard key={rule.name ?? i} rule={rule} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
