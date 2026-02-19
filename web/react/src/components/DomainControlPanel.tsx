import { useState } from 'react';
import { 
  Power, Pause, Play, AlertTriangle, ShieldAlert, 
  TrendingUp, Bitcoin, BarChart3, RefreshCw 
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import ErrorBar from './ErrorBar';
import { API_ENDPOINTS, DEFAULTS} from '../config/constants';

interface DomainState {
  name: string;
  key: string;
  icon: 'prediction' | 'crypto' | 'equity';
  mode: 'SIM' | 'PAPER' | 'LIVE';
  enabled: boolean;
  halted: boolean;
  pnlToday: number;
  exposure: number;
  dailyLoss: number;
  dailyLossLimit: number;
  allocationPct: number;
  maxNotional: number;
  currentNotional: number;
  positionCount: number;
}

interface DomainControlPanelProps {
  compact?: boolean;
}

const DOMAIN_ICONS = {
  prediction: TrendingUp,
  crypto: Bitcoin,
  equity: BarChart3,
};

const MODE_COLORS: Record<string, string> = {
  SIM: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  PAPER: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  LIVE: 'bg-green-500/20 text-green-400 border-green-500/30',
};

export default function DomainControlPanel({ compact = false }: DomainControlPanelProps) {
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<{ domain: string; action: string } | null>(null);

  const { data: rawData, loading, error: fetchError, refetch } = useApiData<{ domains: DomainState[] }>(
    API_ENDPOINTS.PIPELINE_SUMMARY,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );

  if (fetchError && !rawData) {
    return <ErrorBar label="Domain control" error={fetchError} onRetry={refetch} />;
  }
  const domains = rawData?.domains ?? [];

  const executeAction = async (domainKey: string, action: string) => {
    setActionInProgress(`${domainKey}-${action}`);
    try {
      const endpoint = action === 'kill_switch'
        ? `/api/v1/prediction-markets/kill-switch`
        : `/api/v1/pipeline/domain/${action}`;

      await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain: domainKey }),
      });
      refetch();
    } catch {
      // Operation failed — UI state unchanged
    } finally {
      setActionInProgress(null);
      setConfirmAction(null);
    }
  };

  const handleAction = (domainKey: string, action: string) => {
    if (action === 'halt' || action === 'kill_switch' || action === 'disable') {
      setConfirmAction({ domain: domainKey, action });
    } else {
      executeAction(domainKey, action);
    }
  };

  const getDailyLossPercent = (d: DomainState) => {
    if (d.dailyLossLimit === 0) return 0;
    return Math.min(100, (d.dailyLoss / d.dailyLossLimit) * 100);
  };

  const getDailyLossColor = (pct: number) => {
    if (pct >= 80) return 'bg-red-500';
    if (pct >= 50) return 'bg-amber-500';
    return 'bg-green-500';
  };

  const getStatusBadge = (d: DomainState) => {
    if (d.halted) return { text: 'HALTED', color: 'bg-red-500/20 text-red-400 border-red-500/30' };
    if (!d.enabled) return { text: 'DISABLED', color: 'bg-gray-500/20 text-gray-400 border-gray-500/30' };
    return { text: 'ACTIVE', color: 'bg-green-500/20 text-green-400 border-green-500/30' };
  };

  if (loading) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-2 text-gray-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span>Loading domain controls...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldAlert className="w-5 h-5 text-orange-400" />
          <h3 className="text-lg font-bold text-white">Domain Control</h3>
        </div>
        <button type="button"
          onClick={() => refetch()}
          className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white transition-colors"
          title="Refresh domain status"
         aria-label="Refresh">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Domain Cards */}
      <div className={compact ? 'space-y-3' : 'grid grid-cols-1 lg:grid-cols-3 gap-4'}>
        {domains.map((domain) => {
          const Icon = DOMAIN_ICONS[domain.icon];
          const status = getStatusBadge(domain);
          const lossPercent = getDailyLossPercent(domain);
          const lossColor = getDailyLossColor(lossPercent);

          return (
            <div
              key={domain.key}
              className={`bg-slate-800/50 rounded-lg border p-4 ${
                domain.halted
                  ? 'border-red-500/50'
                  : !domain.enabled
                  ? 'border-gray-600/50'
                  : 'border-slate-700/50'
              }`}
            >
              {/* Domain Header */}
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Icon className="w-5 h-5 text-slate-300" />
                  <span className="font-semibold text-white">{domain.name}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`px-2 py-0.5 text-xs font-medium rounded border ${MODE_COLORS[domain.mode]}`}>
                    {domain.mode}
                  </span>
                  <span className={`px-2 py-0.5 text-xs font-medium rounded border ${status.color}`}>
                    {status.text}
                  </span>
                </div>
              </div>

              {/* Metrics */}
              <div className="grid grid-cols-2 gap-2 mb-3 text-sm">
                <div>
                  <span className="text-gray-400">PnL Today</span>
                  <p className={`font-medium ${domain.pnlToday >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    ${domain.pnlToday.toLocaleString()}
                  </p>
                </div>
                <div>
                  <span className="text-gray-400">Exposure</span>
                  <p className="font-medium text-white">${domain.currentNotional.toLocaleString()}</p>
                </div>
                <div>
                  <span className="text-gray-400">Positions</span>
                  <p className="font-medium text-white">{domain.positionCount}</p>
                </div>
                <div>
                  <span className="text-gray-400">Allocation</span>
                  <p className="font-medium text-white">{domain.allocationPct}%</p>
                </div>
              </div>

              {/* Daily Loss Bar */}
              <div className="mb-3">
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-gray-400">Daily Loss vs Limit</span>
                  <span className={`font-medium ${lossPercent >= 80 ? 'text-red-400' : 'text-gray-300'}`}>
                    ${domain.dailyLoss.toLocaleString()} / ${domain.dailyLossLimit.toLocaleString()}
                  </span>
                </div>
                <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full ${lossColor} rounded-full transition-all duration-500`}
                    style={{ width: `${lossPercent}%` }}
                  />
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex gap-2">
                {domain.halted ? (
                  <button type="button"
                    onClick={() => handleAction(domain.key, 'resume')}
                    disabled={actionInProgress !== null}
                    className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white text-sm rounded transition-colors"
                  >
                    <Play className="w-3.5 h-3.5" />
                    Resume
                  </button>
                ) : (
                  <>
                    <button type="button"
                      onClick={() => handleAction(domain.key, 'halt')}
                      disabled={actionInProgress !== null}
                      className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white text-sm rounded transition-colors"
                    >
                      <Pause className="w-3.5 h-3.5" />
                      Pause
                    </button>
                    <button type="button"
                      onClick={() => handleAction(domain.key, 'kill_switch')}
                      disabled={actionInProgress !== null}
                      className="flex items-center justify-center gap-1.5 px-3 py-1.5 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-sm rounded transition-colors"
                    >
                      <Power className="w-3.5 h-3.5" />
                      Kill
                    </button>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Confirmation Dialog */}
      {confirmAction && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center">
          <div className="bg-slate-800 border border-slate-600 rounded-lg p-6 max-w-md mx-4 shadow-2xl">
            <div className="flex items-center gap-3 mb-4">
              <AlertTriangle className="w-6 h-6 text-amber-400" />
              <h4 className="text-lg font-bold text-white">Confirm Action</h4>
            </div>
            <p className="text-gray-300 mb-6">
              Are you sure you want to <strong className="text-white">{confirmAction.action}</strong> the{' '}
              <strong className="text-white">{confirmAction.domain}</strong> domain?
              {confirmAction.action === 'kill_switch' && (
                <span className="block mt-2 text-red-400 text-sm">
                  This will immediately halt all trading and unwind positions.
                </span>
              )}
            </p>
            <div className="flex gap-3 justify-end">
              <button type="button"
                onClick={() => setConfirmAction(null)}
                className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded transition-colors"
              >
                Cancel
              </button>
              <button type="button"
                onClick={() => executeAction(confirmAction.domain, confirmAction.action)}
                disabled={actionInProgress !== null}
                className={`px-4 py-2 text-white rounded transition-colors ${
                  confirmAction.action === 'kill_switch'
                    ? 'bg-red-600 hover:bg-red-700'
                    : 'bg-amber-600 hover:bg-amber-700'
                } disabled:opacity-50`}
              >
                {actionInProgress ? 'Processing...' : `Confirm ${confirmAction.action}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
