/**
 * CodeQualityPanel — Visualizes code quality events from Dev Swarm proposals.
 *
 * Shows:
 *   - Test coverage trends per proposal
 *   - Regression/guardrail block events
 *   - Code quality metrics (coverage delta, lint issues, type errors)
 */

import React, { useMemo } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip as RechartsTooltip,
  ResponsiveContainer, Cell,
} from 'recharts';
import { Bug, CheckCircle, XCircle, AlertTriangle, Shield, TrendingUp } from 'lucide-react';
import { CHART_COLORS } from "../config/constants";

/* ── Types ──────────────────────────────────────────────────── */

interface CodeQualityEvent {
  proposal_id: string;
  event_type: 'test_pass' | 'test_fail' | 'regression' | 'guardrail_block' | 'coverage_change' | 'lint_issue';
  severity: 'info' | 'warning' | 'critical';
  message: string;
  timestamp: number;
  metadata?: Record<string, unknown>;
}

interface ProposalMetrics {
  proposal_id: string;
  title: string;
  test_pass_count: number;
  test_fail_count: number;
  coverage_delta: number;
  regressions: number;
  guardrail_blocks: number;
}

interface ProposalMetricEntry {
  metric_name: string;
  baseline_value: number;
  expected_value: number;
  actual_value: number | null;
  unit: string;
  improved: boolean | null;
}

interface CodeQualityPanelProps {
  proposals: Array<{
    id: string;
    title: string;
    risk_tier?: string;
    status?: string;
    metrics: ProposalMetricEntry[];
  }>;
  auditLog: Array<{
    id: string;
    event_type: string;
    actor_id: string;
    actor_type: string;
    proposal_id?: string;
    timestamp: number;
    details?: Record<string, unknown>;
  }>;
}

/* ── Helpers ────────────────────────────────────────────────── */

function severityColor(sev: string): string {
  switch (sev) {
    case 'critical': return 'text-red-400 bg-red-900/30';
    case 'warning': return 'text-amber-400 bg-amber-900/30';
    default: return 'text-blue-400 bg-blue-900/30';
  }
}

function eventIcon(type: string) {
  switch (type) {
    case 'test_pass': return <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />;
    case 'test_fail': return <XCircle className="w-3.5 h-3.5 text-red-400" />;
    case 'regression': return <Bug className="w-3.5 h-3.5 text-red-400" />;
    case 'guardrail_block': return <Shield className="w-3.5 h-3.5 text-amber-400" />;
    case 'coverage_change': return <TrendingUp className="w-3.5 h-3.5 text-blue-400" />;
    default: return <AlertTriangle className="w-3.5 h-3.5 text-slate-400" />;
  }
}

function formatTime(ts: number): string {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/* ── Component ──────────────────────────────────────────────── */

function CodeQualityPanel({ proposals, auditLog }: CodeQualityPanelProps) {
  // Derive code quality events from proposals and audit log
  const qualityEvents = useMemo<CodeQualityEvent[]>(() => {
    const events: CodeQualityEvent[] = [];

    // Extract from audit log
    for (const evt of auditLog) {
      if (evt.event_type.includes('test') || evt.event_type.includes('regression') ||
          evt.event_type.includes('coverage') || evt.event_type.includes('guardrail') ||
          evt.event_type.includes('lint') || evt.event_type.includes('quality')) {
        const severity = evt.event_type.includes('regression') || evt.event_type.includes('fail')
          ? 'critical'
          : evt.event_type.includes('guardrail') || evt.event_type.includes('lint')
            ? 'warning'
            : 'info';
        const detailStr = typeof evt.details === 'string'
          ? evt.details
          : evt.details?.message ?? `${evt.event_type} by ${evt.actor_id}`;
        events.push({
          proposal_id: evt.proposal_id ?? '',
          event_type: evt.event_type.includes('pass') ? 'test_pass'
            : evt.event_type.includes('fail') ? 'test_fail'
            : evt.event_type.includes('regression') ? 'regression'
            : evt.event_type.includes('guardrail') ? 'guardrail_block'
            : evt.event_type.includes('coverage') ? 'coverage_change'
            : 'lint_issue',
          severity,
          message: detailStr,
          timestamp: evt.timestamp,
        });
      }
    }

    // Extract from proposal metrics array
    for (const p of proposals) {
      if (!p.metrics || p.metrics.length === 0) continue;
      for (const m of p.metrics) {
        if (m.metric_name.includes('regression') && m.actual_value !== null && m.actual_value > 0) {
          events.push({
            proposal_id: p.id,
            event_type: 'regression',
            severity: 'critical',
            message: `${m.actual_value} regression(s) in "${p.title}"`,
            timestamp: Date.now() / 1000,
          });
        }
        if (m.metric_name.includes('test') && m.improved === false && m.actual_value !== null) {
          events.push({
            proposal_id: p.id,
            event_type: 'test_fail',
            severity: 'critical',
            message: `${m.metric_name}: ${m.actual_value}${m.unit} (expected ${m.expected_value}${m.unit}) in "${p.title}"`,
            timestamp: Date.now() / 1000,
          });
        }
        if (m.metric_name.includes('coverage') && m.actual_value !== null) {
          events.push({
            proposal_id: p.id,
            event_type: 'coverage_change',
            severity: m.improved ? 'info' : 'warning',
            message: `Coverage ${m.improved ? 'improved' : 'decreased'}: ${m.baseline_value}${m.unit} → ${m.actual_value}${m.unit} in "${p.title}"`,
            timestamp: Date.now() / 1000,
          });
        }
      }
    }

    return events.sort((a, b) => b.timestamp - a.timestamp).slice(0, 50);
  }, [proposals, auditLog]);

  // Derive per-proposal quality metrics from the metrics array
  const proposalMetrics = useMemo<ProposalMetrics[]>(() => {
    return proposals
      .filter(p => p.metrics && p.metrics.length > 0)
      .map(p => {
        const ms = p.metrics;
        const testPass = ms.find(m => m.metric_name.includes('pass'));
        const testFail = ms.find(m => m.metric_name.includes('fail'));
        const coverage = ms.find(m => m.metric_name.includes('coverage'));
        const regression = ms.find(m => m.metric_name.includes('regression'));
        const guardrail = ms.find(m => m.metric_name.includes('guardrail'));
        return {
          proposal_id: p.id,
          title: p.title.length > 25 ? p.title.slice(0, 25) + '…' : p.title,
          test_pass_count: testPass?.actual_value ?? 0,
          test_fail_count: testFail?.actual_value ?? 0,
          coverage_delta: coverage ? (coverage.actual_value ?? 0) - coverage.baseline_value : 0,
          regressions: regression?.actual_value ?? 0,
          guardrail_blocks: guardrail?.actual_value ?? 0,
        };
      })
      .slice(0, 10);
  }, [proposals]);

  // Summary stats
  const stats = useMemo(() => {
    const totalTests = proposalMetrics.reduce((s, p) => s + p.test_pass_count + p.test_fail_count, 0);
    const totalPassed = proposalMetrics.reduce((s, p) => s + p.test_pass_count, 0);
    const totalRegressions = proposalMetrics.reduce((s, p) => s + p.regressions, 0);
    const totalBlocks = proposalMetrics.reduce((s, p) => s + p.guardrail_blocks, 0);
    const avgCovDelta = proposalMetrics.length > 0
      ? proposalMetrics.reduce((s, p) => s + p.coverage_delta, 0) / proposalMetrics.length
      : 0;
    return { totalTests, totalPassed, totalRegressions, totalBlocks, avgCovDelta };
  }, [proposalMetrics]);

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <div className="bg-gray-800 border border-gray-700 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-1">
            <CheckCircle className="w-4 h-4 text-emerald-400" />
            <span className="text-xs text-gray-400">Tests Run</span>
          </div>
          <p className="text-xl font-bold text-white">{stats.totalTests}</p>
          <p className="text-xs text-emerald-400 mt-1">{stats.totalPassed} passed</p>
        </div>
        <div className="bg-gray-800 border border-gray-700 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-1">
            <Bug className="w-4 h-4 text-red-400" />
            <span className="text-xs text-gray-400">Regressions</span>
          </div>
          <p className={`text-xl font-bold ${stats.totalRegressions > 0 ? 'text-red-400' : 'text-white'}`}>
            {stats.totalRegressions}
          </p>
        </div>
        <div className="bg-gray-800 border border-gray-700 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-1">
            <Shield className="w-4 h-4 text-amber-400" />
            <span className="text-xs text-gray-400">Guardrail Blocks</span>
          </div>
          <p className={`text-xl font-bold ${stats.totalBlocks > 0 ? 'text-amber-400' : 'text-white'}`}>
            {stats.totalBlocks}
          </p>
        </div>
        <div className="bg-gray-800 border border-gray-700 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-1">
            <TrendingUp className="w-4 h-4 text-blue-400" />
            <span className="text-xs text-gray-400">Avg Coverage Δ</span>
          </div>
          <p className={`text-xl font-bold ${stats.avgCovDelta >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {stats.avgCovDelta >= 0 ? '+' : ''}{stats.avgCovDelta.toFixed(1)}%
          </p>
        </div>
        <div className="bg-gray-800 border border-gray-700 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-1">
            <AlertTriangle className="w-4 h-4 text-purple-400" />
            <span className="text-xs text-gray-400">Quality Events</span>
          </div>
          <p className="text-xl font-bold text-white">{qualityEvents.length}</p>
        </div>
      </div>

      {/* Test results per proposal chart */}
      {proposalMetrics.length > 0 && (
        <div className="bg-gray-800 border border-gray-700 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-gray-300 mb-4 flex items-center gap-2">
            <CheckCircle className="w-4 h-4 text-emerald-400" /> Test Results by Proposal
          </h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={proposalMetrics} margin={{ left: 10, right: 10 }}>
              <XAxis dataKey="title" tick={{ fill: CHART_COLORS.AXIS_TICK, fontSize: 10 }} interval={0} angle={-15} textAnchor="end" height={60} />
              <YAxis tick={{ fill: CHART_COLORS.AXIS_TICK, fontSize: 11 }} />
              <RechartsTooltip
                contentStyle={{ backgroundColor: CHART_COLORS.TOOLTIP_BG, border: '1px solid #334155', borderRadius: 8 }}
                labelStyle={{ color: CHART_COLORS.AXIS_TICK }}
              />
              <Bar dataKey="test_pass_count" name="Passed" fill={CHART_COLORS.GREEN} stackId="tests" radius={[0, 0, 0, 0]} barSize={20} />
              <Bar dataKey="test_fail_count" name="Failed" fill={CHART_COLORS.RED} stackId="tests" radius={[4, 4, 0, 0]} barSize={20} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Coverage delta chart */}
      {proposalMetrics.length > 0 && (
        <div className="bg-gray-800 border border-gray-700 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-gray-300 mb-4 flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-blue-400" /> Coverage Delta by Proposal
          </h3>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={proposalMetrics} margin={{ left: 10, right: 10 }}>
              <XAxis dataKey="title" tick={{ fill: CHART_COLORS.AXIS_TICK, fontSize: 10 }} interval={0} angle={-15} textAnchor="end" height={60} />
              <YAxis tick={{ fill: CHART_COLORS.AXIS_TICK, fontSize: 11 }} />
              <RechartsTooltip
                contentStyle={{ backgroundColor: CHART_COLORS.TOOLTIP_BG, border: '1px solid #334155', borderRadius: 8 }}
                formatter={(value: number) => [`${value >= 0 ? '+' : ''}${value.toFixed(1)}%`, 'Coverage Δ']}
              />
              <Bar dataKey="coverage_delta" name="Coverage Δ" radius={[4, 4, 0, 0]} barSize={20}>
                {proposalMetrics.map((entry, idx) => (
                  <Cell key={idx} fill={entry.coverage_delta >= 0 ? CHART_COLORS.GREEN : CHART_COLORS.RED} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Quality event timeline */}
      <div className="bg-gray-800 border border-gray-700 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-400" /> Code Quality Event Timeline
          </h3>
          <span className="text-xs text-gray-500">{qualityEvents.length} events</span>
        </div>
        {qualityEvents.length === 0 ? (
          <div className="text-center text-gray-500 text-sm py-8">
            <CheckCircle className="w-8 h-8 text-gray-600 mx-auto mb-2" />
            No code quality events recorded — all clear
          </div>
        ) : (
          <div className="space-y-1 max-h-[300px] overflow-y-auto">
            {qualityEvents.map((evt, i) => (
              <div
                key={`${evt.proposal_id}-${evt.event_type}-${i}`}
                className="flex items-center gap-3 px-3 py-2 rounded-lg bg-gray-900/50 hover:bg-gray-700/30 transition-colors"
              >
                {eventIcon(evt.event_type)}
                <span className={`text-xs px-2 py-0.5 rounded font-medium ${severityColor(evt.severity)}`}>
                  {evt.event_type.replace('_', ' ')}
                </span>
                <span className="text-sm text-gray-300 flex-1 truncate">{evt.message}</span>
                {evt.proposal_id && (
                  <span className="text-xs text-gray-500 font-mono">{evt.proposal_id.slice(0, 8)}</span>
                )}
                <span className="text-xs text-gray-500 shrink-0">{formatTime(evt.timestamp)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

const MemoizedCodeQualityPanel = React.memo(CodeQualityPanel);
MemoizedCodeQualityPanel.displayName = 'CodeQualityPanel';
export default MemoizedCodeQualityPanel;
