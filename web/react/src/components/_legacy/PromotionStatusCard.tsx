import { useState } from 'react';
import { RefreshCw, Shield, ShieldCheck, ShieldAlert, ChevronDown, ChevronUp, History } from 'lucide-react';
import type { PromotionReport, RingResult, DomainDetail, AgentDetail } from '../hooks/usePromotionReport';
import type { PromotionEvent } from '../hooks/usePromotionLog';

interface PromotionStatusCardProps {
  report: PromotionReport | null;
  loading: boolean;
  onRefresh: () => Promise<void>;
  lastUpdated: Date | null;
  logEvents?: PromotionEvent[];
  syncStale?: boolean;
  syncAgeS?: number | null;
}

function RingBadge({ ring }: { ring: RingResult }) {
  const bg = ring.passed
    ? 'bg-green-900/30 border-green-700/40 text-green-400'
    : 'bg-red-900/30 border-red-700/40 text-red-400';
  return (
    <div className={`flex items-center justify-between rounded-lg border px-3 py-2 ${bg}`}>
      <div className="flex items-center gap-2">
        <div className={`w-2 h-2 rounded-full ${ring.passed ? 'bg-green-400' : 'bg-red-400'}`} />
        <span className="text-xs font-medium capitalize">{ring.name.replace('_', ' ')}</span>
      </div>
      <span className="text-xs font-mono">{ring.checks_passed}/{ring.checks_total}</span>
    </div>
  );
}

function DomainRow({ domain }: { domain: DomainDetail }) {
  return (
    <div className="flex items-center justify-between text-xs py-1">
      <div className="flex items-center gap-2">
        <div className={`w-1.5 h-1.5 rounded-full ${domain.eligible ? 'bg-green-400' : 'bg-red-400'}`} />
        <span className="text-slate-300 capitalize">{domain.domain}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-slate-500">{domain.instruments} inst</span>
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
          domain.eligible
            ? 'bg-green-900/40 text-green-400'
            : 'bg-slate-800 text-slate-500'
        }`}>
          {domain.eligible ? 'ELIGIBLE' : domain.mode.toUpperCase()}
        </span>
      </div>
    </div>
  );
}

function AgentRow({ agent }: { agent: AgentDetail }) {
  return (
    <div className="flex items-center justify-between text-xs py-1">
      <div className="flex items-center gap-2">
        <div className={`w-1.5 h-1.5 rounded-full ${agent.promoted ? 'bg-green-400' : 'bg-red-400'}`} />
        <span className="text-slate-300 truncate max-w-[160px]">{agent.agent_id}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-slate-500">{agent.category}</span>
        <span className={`font-mono ${
          agent.slo_pass_rate >= 1.0 ? 'text-green-400' : 'text-amber-400'
        }`}>
          {(agent.slo_pass_rate * 100).toFixed(0)}%
        </span>
      </div>
    </div>
  );
}

const SOURCE_STYLES: Record<string, string> = {
  automation: 'bg-blue-900/40 text-blue-400',
  operator: 'bg-purple-900/40 text-purple-400',
  system: 'bg-slate-800 text-slate-500',
};

function ChangeLogRow({ event }: { event: PromotionEvent }) {
  const isPromotion = event.new_status === 'eligible';
  const color = isPromotion ? 'text-green-400' : 'text-red-400';
  const ts = new Date(event.timestamp * 1000);
  const timeStr = ts.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
    + ' ' + ts.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  const srcStyle = SOURCE_STYLES[event.source] || SOURCE_STYLES.system;

  return (
    <div className="flex items-start gap-2 text-[10px] py-1">
      <span className="text-slate-600 shrink-0 w-[90px]">{timeStr}</span>
      <span className={`shrink-0 ${color}`}>
        {event.entity_type === 'domain' ? '◆' : '●'}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="text-slate-300 capitalize">{event.entity_id}</span>
          <span className="text-slate-600">→</span>
          <span className={color}>{event.new_status.toUpperCase()}</span>
          <span className={`px-1 py-px rounded text-[8px] font-medium ${srcStyle}`}>
            {event.source.toUpperCase()}
          </span>
        </div>
        {event.reason && (
          <div className="text-slate-600 truncate" title={event.reason}>
            {event.reason}
          </div>
        )}
      </div>
    </div>
  );
}

export default function PromotionStatusCard({
  report,
  loading,
  onRefresh,
  lastUpdated,
  logEvents,
  syncStale,
  syncAgeS,
}: PromotionStatusCardProps) {
  const [expanded, setExpanded] = useState(false);

  const overallColor = report?.overall_eligible
    ? 'text-green-400'
    : report?.all_rings_pass
      ? 'text-amber-400'
      : 'text-red-400';

  const OverallIcon = report?.overall_eligible
    ? ShieldCheck
    : report?.all_rings_pass
      ? Shield
      : ShieldAlert;

  const overallLabel = report?.overall_eligible
    ? 'Eligible for Live'
    : report?.all_rings_pass
      ? 'Rings Pass — Agents Pending'
      : 'Not Eligible';

  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-slate-300">Promotion Status</h3>
        <div className="flex items-center gap-2">
          {lastUpdated && (
            <span className="text-[10px] text-slate-600">
              {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button type="button"
            onClick={onRefresh}
            disabled={loading}
            title="Refresh promotion report"
            className="p-1 rounded hover:bg-slate-800 transition-colors disabled:opacity-50"
           aria-label="Refresh">
            <RefreshCw className={`w-3.5 h-3.5 text-slate-500 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Overall Status */}
      {report ? (
        <>
          <div className="flex items-center gap-3 mb-4">
            <OverallIcon className={`w-8 h-8 ${overallColor}`} />
            <div>
              <div className={`text-sm font-bold ${overallColor}`}>{overallLabel}</div>
              <div className="text-[10px] text-slate-500">
                {report.domains.eligible.length}/{report.domains.detail.length} domains
                {' | '}
                {report.agents.promoted.length}/{report.agents.detail.length} agents
                {' | '}
                {report.elapsed_s.toFixed(1)}s
              </div>
            </div>
          </div>

          {/* Rings */}
          <div className="grid grid-cols-3 gap-2 mb-4">
            {report.rings.map((ring) => (
              <RingBadge key={ring.name} ring={ring} />
            ))}
          </div>

          {/* Guard Enforcement Indicator */}
          <div className="flex items-center justify-between text-[10px] px-1 mb-3">
            <span className="text-slate-500">Guard Enforcement</span>
            <span className={`px-1.5 py-0.5 rounded font-medium ${
              report.overall_eligible
                ? 'bg-green-900/40 text-green-400'
                : 'bg-amber-900/40 text-amber-400'
            }`}>
              {report.overall_eligible ? 'LIVE ALLOWED' : 'LIVE BLOCKED'}
            </span>
          </div>

          {/* Stale Sync Warning */}
          {syncStale && (
            <div className="flex items-center justify-between text-[10px] px-2 py-1.5 mb-3 rounded bg-amber-900/20 border border-amber-800/30">
              <span className="text-amber-400 font-medium">⚠ Guard sync stale</span>
              <span className="text-amber-500">
                {syncAgeS != null ? `${Math.round(syncAgeS / 60)}m ago` : 'never synced'}
              </span>
            </div>
          )}

          {/* Expand/Collapse */}
          <button type="button"
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 transition-colors w-full justify-center py-1"
          >
            {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            {expanded ? 'Less detail' : 'More detail'}
          </button>

          {expanded && (
            <div className="mt-3 space-y-4">
              {/* Domain Eligibility */}
              <div>
                <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">Domains</div>
                <div className="space-y-0.5">
                  {report.domains.detail.map((d) => (
                    <DomainRow key={d.domain} domain={d} />
                  ))}
                </div>
              </div>

              {/* Agent Promotion */}
              <div>
                <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">Agents</div>
                <div className="space-y-0.5">
                  {report.agents.detail.map((a) => (
                    <AgentRow key={a.agent_id} agent={a} />
                  ))}
                </div>
              </div>

              {/* Ring Failures */}
              {report.rings.some(r => r.failures.length > 0) && (
                <div>
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">Blockers</div>
                  {report.rings
                    .filter(r => r.failures.length > 0)
                    .map(r => (
                      <div key={r.name} className="mb-1">
                        {r.failures.map((f, i) => (
                          <div key={i} className="text-[10px] text-red-400 pl-2">
                            {r.name}: {f}
                          </div>
                        ))}
                      </div>
                    ))}
                </div>
              )}

              {/* Change Log */}
              {logEvents && logEvents.length > 0 && (
                <div>
                  <div className="flex items-center gap-1.5 mb-2">
                    <History className="w-3 h-3 text-slate-500" />
                    <span className="text-[10px] text-slate-500 uppercase tracking-wider">Change Log</span>
                    <span className="text-[10px] text-slate-600">({logEvents.length})</span>
                  </div>
                  <div className="space-y-0 max-h-[160px] overflow-y-auto pr-1">
                    {[...logEvents].reverse().slice(0, 20).map((evt, i) => (
                      <ChangeLogRow key={`${evt.timestamp}-${evt.entity_id}-${i}`} event={evt} />
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      ) : loading ? (
        <div className="flex items-center justify-center py-8">
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500" />
        </div>
      ) : (
        <div className="text-sm text-slate-500 text-center py-4">
          No promotion report available
        </div>
      )}
    </div>
  );
}
