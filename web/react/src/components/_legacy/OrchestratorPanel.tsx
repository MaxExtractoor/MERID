import { useState } from 'react';
import { 
  GitBranch, Clock, CheckCircle, AlertCircle, Loader2, 
  RefreshCw 
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS} from '../config/constants';

interface PhaseResult {
  name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  agentCount: number;
  outputCount: number;
  durationMs: number;
  agents: AgentResult[];
}

interface AgentResult {
  name: string;
  status: 'success' | 'error' | 'skipped';
  outputSummary: string;
  durationMs: number;
}

interface CycleResult {
  cycleId: number;
  startedAt: string;
  completedAt: string;
  totalDurationMs: number;
  phases: PhaseResult[];
  proposalsGenerated: number;
  spikesDetected: number;
  verdictsIssued: number;
}

const PHASE_ORDER = ['RESEARCH', 'STRATEGY', 'RISK', 'COORDINATION', 'OPS'];

const PHASE_COLORS: Record<string, string> = {
  RESEARCH: 'bg-purple-500',
  STRATEGY: 'bg-blue-500',
  RISK: 'bg-red-500',
  COORDINATION: 'bg-amber-500',
  OPS: 'bg-green-500',
};

const STATUS_ICONS: Record<string, { icon: typeof CheckCircle; color: string }> = {
  pending: { icon: Clock, color: 'text-gray-400' },
  running: { icon: Loader2, color: 'text-blue-400' },
  completed: { icon: CheckCircle, color: 'text-green-400' },
  failed: { icon: AlertCircle, color: 'text-red-400' },
};

export default function OrchestratorPanel() {
  const [expandedPhase, setExpandedPhase] = useState<string | null>(null);

  const { data: rawData, loading, refetch } = useApiData<{ latest_cycle: CycleResult }>(
    API_ENDPOINTS.ORCHESTRATOR_SUMMARY,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );
  const cycle = rawData?.latest_cycle ?? null;

  if (loading && !cycle) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-2 text-gray-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span>Loading orchestrator status...</span>
        </div>
      </div>
    );
  }

  if (!cycle) return null;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <GitBranch className="w-5 h-5 text-purple-400" />
          <h3 className="text-lg font-bold text-white">Orchestrator</h3>
          <span className="text-sm text-gray-400">Cycle #{cycle.cycleId}</span>
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-400">
          <span>{cycle.totalDurationMs}ms total</span>
          <button type="button"
            onClick={() => refetch()}
            className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white transition-colors"
            title="Refresh orchestrator"
           aria-label="Refresh">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3 text-center">
          <p className="text-2xl font-bold text-white">{cycle.proposalsGenerated}</p>
          <p className="text-xs text-gray-400">Proposals</p>
        </div>
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3 text-center">
          <p className="text-2xl font-bold text-white">{cycle.spikesDetected}</p>
          <p className="text-xs text-gray-400">Spikes</p>
        </div>
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3 text-center">
          <p className="text-2xl font-bold text-white">{cycle.verdictsIssued}</p>
          <p className="text-xs text-gray-400">Verdicts</p>
        </div>
      </div>

      {/* Phase Pipeline */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
        {/* Pipeline Visualization */}
        <div className="flex items-center gap-1 mb-4">
          {cycle.phases.map((phase, i) => {
            const cfg = STATUS_ICONS[phase.status];
            const StatusIcon = cfg.icon;
            const barColor = PHASE_COLORS[phase.name] || 'bg-gray-500';

            return (
              <div key={phase.name} className="flex items-center flex-1">
                <div
                  className={`flex-1 relative cursor-pointer rounded ${
                    expandedPhase === phase.name ? 'ring-1 ring-white/30' : ''
                  }`}
                  onClick={() => setExpandedPhase(expandedPhase === phase.name ? null : phase.name)}
                 role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); (() => setExpandedPhase(expandedPhase === phase.name ? null : phase.name))(); } }}>
                  <div className={`h-8 ${barColor} rounded flex items-center justify-center gap-1.5 px-2`}>
                    <StatusIcon className={`w-3.5 h-3.5 text-white ${phase.status === 'running' ? 'animate-spin' : ''}`} />
                    <span className="text-xs font-medium text-white truncate">{phase.name}</span>
                  </div>
                  <div className="text-center mt-1">
                    <span className="text-[10px] text-gray-500">{phase.durationMs}ms</span>
                  </div>
                </div>
                {i < cycle.phases.length - 1 && (
                  <div className="w-4 h-0.5 bg-slate-600 mx-0.5 flex-shrink-0" />
                )}
              </div>
            );
          })}
        </div>

        {/* Expanded Phase Detail */}
        {expandedPhase && (
          <div className="border-t border-slate-700/50 pt-3 mt-2">
            {cycle.phases
              .filter(p => p.name === expandedPhase)
              .map(phase => (
                <div key={phase.name}>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium text-white">{phase.name} Phase</span>
                    <span className="text-xs text-gray-400">
                      {phase.agentCount} agents · {phase.outputCount} outputs · {phase.durationMs}ms
                    </span>
                  </div>
                  <div className="space-y-1">
                    {phase.agents.map(agent => (
                      <div
                        key={agent.name}
                        className="flex items-center justify-between px-3 py-1.5 bg-slate-900/50 rounded text-xs"
                      >
                        <div className="flex items-center gap-2">
                          {agent.status === 'success' ? (
                            <CheckCircle className="w-3 h-3 text-green-400" />
                          ) : agent.status === 'error' ? (
                            <AlertCircle className="w-3 h-3 text-red-400" />
                          ) : (
                            <Clock className="w-3 h-3 text-gray-400" />
                          )}
                          <span className="text-gray-300 font-mono">{agent.name}</span>
                        </div>
                        <div className="flex items-center gap-3">
                          <span className="text-gray-500">{agent.outputSummary}</span>
                          <span className="text-gray-400">{agent.durationMs}ms</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
          </div>
        )}
      </div>
    </div>
  );
}
