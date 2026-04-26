import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { CheckCircle, XCircle, Zap, Settings, Target, BarChart3 } from '../ui/icons';

interface LaneStatus {
  lane?: {
    mode?: string;
    lane_live?: boolean;
    lifecycle_state?: string;
  };
  kill_switch?: {
    can_trade?: boolean;
    state?: string;
  };
  trade_mode?: string;
}

interface GridStatus {
  agent_count?: number;
  running?: boolean;
  use_demo?: boolean;
}

interface ExecutionStatus {
  enable_execution?: boolean;
  kill_switch_active?: boolean;
  domain_modes?: Record<string, string>;
}

export default function ContextStrip() {
  const { data: laneStatus, lastUpdated: laneLastUpdated } = useApiData<LaneStatus>(
    API_ENDPOINTS.LANE_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH }
  );

  const { data: gridStatus, lastUpdated: gridLastUpdated } = useApiData<GridStatus>(
    API_ENDPOINTS.KALSHI_GRID_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );

  const { data: execStatus, lastUpdated: execLastUpdated } = useApiData<ExecutionStatus>(
    API_ENDPOINTS.LOOP_EXECUTION_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH }
  );

  // Show loading state if all are loading
  const isLoading = !laneStatus && !gridStatus && !execStatus;

  if (isLoading) {
    return (
      <div className="border-b px-4 py-2 flex items-center justify-between bg-slate-900/60 border-slate-700">
        <div className="flex items-center gap-3">
          <div className="animate-pulse flex items-center gap-3">
            <div data-testid="skeleton" className="w-16 h-4 bg-slate-700 rounded"></div>
            <div data-testid="skeleton" className="w-12 h-4 bg-slate-700 rounded"></div>
            <div data-testid="skeleton" className="w-14 h-4 bg-slate-700 rounded"></div>
            <div data-testid="skeleton" className="w-20 h-4 bg-slate-700 rounded"></div>
          </div>
        </div>
        <div className="animate-pulse w-16 h-4 bg-slate-700 rounded"></div>
      </div>
    );
  }

  // Extract context values
  const venue = 'Kalshi'; // Currently fixed
  const lane = laneStatus?.lane?.mode || 'Unknown';
  const profile = laneStatus?.trade_mode || 'Unknown';
  const executionEnabled = execStatus?.enable_execution ?? false;
  const killSwitchActive = execStatus?.kill_switch_active ?? false;
  const agentsRunning = gridStatus?.running ?? false;

  // Determine mode based on execution and kill switch
  let mode = 'Idle';
  if (killSwitchActive) {
    mode = 'Halted';
  } else if (executionEnabled) {
    mode = profile === 'live' ? 'Live Trading' : 'Paper Trading';
  } else {
    mode = 'Ready';
  }

  // Check for unsupported combinations and generate warnings
  const warnings: string[] = [];
  if (profile === 'live' && !executionEnabled) {
    warnings.push('Live profile with execution disabled');
  }
  if (profile === 'live' && killSwitchActive) {
    warnings.push('Live profile with kill switch active');
  }
  if (executionEnabled && !agentsRunning) {
    warnings.push('Execution enabled but agents not running');
  }
  if (lane === 'Unknown') {
    warnings.push('Lane status unknown');
  }

  const hasWarnings = warnings.length > 0;

  // Get the most recent update time
  const lastUpdates = [laneLastUpdated, gridLastUpdated, execLastUpdated]
    .filter((d): d is Date => d != null)
    .map(d => d.getTime());
  const mostRecentUpdate = lastUpdates.length > 0 ? Math.max(...lastUpdates) : null;

  return (
    <div className={`border-b px-4 py-2 flex items-center justify-between text-xs ${
      hasWarnings
        ? 'bg-amber-950/20 border-amber-600/40'
        : 'bg-slate-900/60 border-slate-700'
    }`}>
      {/* Context Badges */}
      <div className="flex items-center gap-3">
        {/* Venue */}
        <div className="flex items-center gap-1.5">
          <Target className="w-3 h-3 text-blue-400" />
          <span className="font-medium text-slate-300">Venue:</span>
          <span className="px-2 py-0.5 bg-blue-500/20 text-blue-300 rounded text-[10px] font-mono">
            {venue}
          </span>
        </div>

        {/* Lane */}
        <div className="flex items-center gap-1.5">
          <BarChart3 className="w-3 h-3 text-purple-400" />
          <span className="font-medium text-slate-300">Lane:</span>
          <span className="px-2 py-0.5 bg-purple-500/20 text-purple-300 rounded text-[10px] font-mono">
            {lane}
          </span>
        </div>

        {/* Profile */}
        <div className="flex items-center gap-1.5">
          <Settings className="w-3 h-3 text-green-400" />
          <span className="font-medium text-slate-300">Profile:</span>
          <span className={`px-2 py-0.5 rounded text-[10px] font-mono ${
            profile === 'live'
              ? 'bg-red-500/20 text-red-300'
              : profile === 'paper'
              ? 'bg-green-500/20 text-green-300'
              : 'bg-slate-500/20 text-slate-300'
          }`}>
            {profile.toUpperCase()}
          </span>
        </div>

        {/* Mode */}
        <div className="flex items-center gap-1.5">
          <Zap className="w-3 h-3 text-yellow-400" />
          <span className="font-medium text-slate-300">Mode:</span>
          <span className={`px-2 py-0.5 rounded text-[10px] font-mono ${
            mode === 'Live Trading'
              ? 'bg-red-500/20 text-red-300'
              : mode === 'Paper Trading'
              ? 'bg-blue-500/20 text-blue-300'
              : mode === 'Halted'
              ? 'bg-red-600/20 text-red-300'
              : 'bg-slate-500/20 text-slate-300'
          }`}>
            {mode}
          </span>
        </div>
      </div>

      {/* Warnings and Freshness */}
      <div className="flex items-center gap-3">
        {/* Warnings */}
        {hasWarnings && (
          <div className="flex gap-1">
            {warnings.map((warning, index) => (
              <span key={index} className="px-2 py-0.5 bg-amber-500/20 text-amber-300 rounded text-[10px]">
                {warning}
              </span>
            ))}
          </div>
        )}

        {/* Freshness Badge */}
        {mostRecentUpdate && (
          <div className="text-slate-500 text-[10px]">
            {new Intl.DateTimeFormat('en-US', {
              hour: '2-digit',
              minute: '2-digit',
              second: '2-digit',
              hour12: true,
              timeZone: 'UTC',
            }).format(new Date(mostRecentUpdate))}
          </div>
        )}

        {/* Status Indicator */}
        <div className="flex items-center gap-1.5">
          {killSwitchActive ? (
            <XCircle className="w-3 h-3 text-red-400" />
          ) : executionEnabled ? (
            <CheckCircle className="w-3 h-3 text-green-400" />
          ) : (
            <div className="w-3 h-3 rounded-full bg-slate-600" />
          )}
          <span className={`text-[10px] font-medium ${
            killSwitchActive ? 'text-red-400' :
            executionEnabled ? 'text-green-400' : 'text-slate-400'
          }`}>
            {killSwitchActive ? 'HALTED' :
             executionEnabled ? 'ACTIVE' : 'STANDBY'}
          </span>
        </div>
      </div>
    </div>
  );
}
