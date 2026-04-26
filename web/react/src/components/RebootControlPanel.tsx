/**
 * RebootControlPanel — Pre-flight checks and grid start/stop controls.
 *
 * Home view: OperatorDashboard (moved from Overview in Phase 2 refactor).
 * Shows kill switch status, grid status, catalog count, and action buttons.
 */

import { RefreshCw, Play, Square, Database, ShieldAlert, ShieldCheck } from '../ui/icons';

interface OperatorKillSwitchState {
  global_kill?: boolean;
  active?: boolean;
  can_trade?: boolean;
  kill_reason?: string | null;
  reason?: string | null;
}

interface GridStatusLite {
  running?: boolean;
  agent_count?: number;
  session?: { trading_allowed?: boolean; block_reason?: string | null };
}

export interface RebootControlPanelProps {
  killSwitch: OperatorKillSwitchState | null;
  gridStatus: GridStatusLite | null;
  catalogCount: number | null;
  busyAction: string | null;
  message: string | null;
  error: string | null;
  gridStartMode: 'paper' | 'live';
  onGridStartModeChange: (mode: 'paper' | 'live') => void;
  onRefreshCatalog: () => void;
  onStartGrid: () => void;
  onStopGrid: () => void;
  onRefreshSignals: () => void;
}

export default function RebootControlPanel({
  killSwitch,
  gridStatus,
  catalogCount,
  busyAction,
  message,
  error,
  gridStartMode,
  onGridStartModeChange,
  onRefreshCatalog,
  onStartGrid,
  onStopGrid,
  onRefreshSignals,
}: RebootControlPanelProps) {
  const killActive = Boolean(killSwitch?.global_kill ?? killSwitch?.active ?? false);
  const canTrade = killSwitch?.can_trade ?? !killActive;
  const killReason = killSwitch?.kill_reason ?? killSwitch?.reason;
  const gridRunning = Boolean(gridStatus?.running);

  return (
    <section className="bg-slate-900/70 rounded-2xl border border-slate-800 p-4 space-y-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">Reboot Sequence</h3>
          <p className="text-xs text-slate-500">Pre-flight checks and controls for live Kalshi restart.</p>
        </div>
        <button
          type="button"
          onClick={onRefreshSignals}
          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs border border-slate-700 text-slate-300 hover:bg-slate-800"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className={`rounded-xl border p-3 ${killActive ? 'bg-red-950/40 border-red-500/40' : 'bg-emerald-950/30 border-emerald-500/30'}`}>
          <p className="text-[10px] uppercase text-slate-500 mb-1">Kill Switch</p>
          <div className={`flex items-center gap-1.5 text-sm font-semibold ${killActive ? 'text-red-400' : 'text-emerald-400'}`}>
            {killActive ? <ShieldAlert className="w-4 h-4" /> : <ShieldCheck className="w-4 h-4" />}
            {killActive ? 'HALTED' : 'CLEAR'}
          </div>
          <p className="text-[10px] text-slate-500 mt-1">{canTrade ? 'Trading permitted' : 'Trading blocked'}</p>
          {killReason && <p className="text-[10px] text-red-300 mt-1 truncate" title={killReason}>{killReason}</p>}
        </div>

        <div className={`rounded-xl border p-3 ${gridRunning ? 'bg-blue-950/30 border-blue-500/30' : 'bg-slate-800/70 border-slate-700/40'}`}>
          <p className="text-[10px] uppercase text-slate-500 mb-1">Agent Grid</p>
          <p className={`text-sm font-semibold ${gridRunning ? 'text-blue-300' : 'text-slate-300'}`}>
            {gridRunning ? 'RUNNING' : 'STOPPED'}
          </p>
          <p className="text-[10px] text-slate-500 mt-1">{gridStatus?.agent_count ?? 0} agents</p>
          {gridStatus?.session && (
            <p className="text-[10px] text-slate-500 mt-0.5">
              Session: {gridStatus.session.trading_allowed ? 'Open' : (gridStatus.session.block_reason ?? 'Closed')}
            </p>
          )}
        </div>

        <div className="rounded-xl border p-3 bg-slate-800/70 border-slate-700/40">
          <p className="text-[10px] uppercase text-slate-500 mb-1">Catalog</p>
          <div className="flex items-center gap-1.5 text-sm font-semibold text-slate-200">
            <Database className="w-4 h-4 text-orange-400" />
            {catalogCount != null ? `${catalogCount} markets` : 'Unknown size'}
          </div>
          <p className="text-[10px] text-slate-500 mt-1">Refresh before enabling live agents</p>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <button
          type="button"
          onClick={onRefreshCatalog}
          disabled={busyAction !== null}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-orange-500/15 text-orange-300 border border-orange-500/30 hover:bg-orange-500/20 disabled:opacity-50"
        >
          <Database className="w-3.5 h-3.5" />
          {busyAction === 'catalog' ? 'Refreshing…' : 'Refresh Catalog'}
        </button>

        {!gridRunning ? (
          <>
            {/* Mode toggle */}
            <div className="flex items-center rounded-lg overflow-hidden border border-slate-700">
              <button
                type="button"
                onClick={() => onGridStartModeChange('paper')}
                className={`px-2.5 py-1.5 text-xs font-medium transition-colors ${
                  gridStartMode === 'paper' ? 'bg-amber-600 text-white' : 'bg-slate-800 text-gray-400 hover:text-white'
                }`}
              >
                Paper
              </button>
              <button
                type="button"
                onClick={() => onGridStartModeChange('live')}
                className={`px-2.5 py-1.5 text-xs font-medium transition-colors ${
                  gridStartMode === 'live' ? 'bg-red-600 text-white' : 'bg-slate-800 text-gray-400 hover:text-red-400'
                }`}
              >
                Live
              </button>
            </div>
            <button
              type="button"
              onClick={onStartGrid}
              disabled={busyAction !== null || killActive}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border disabled:opacity-50 ${
                gridStartMode === 'live'
                  ? 'bg-red-500/15 text-red-300 border-red-500/30 hover:bg-red-500/20'
                  : 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30 hover:bg-emerald-500/20'
              }`}
            >
              <Play className="w-3.5 h-3.5" />
              {busyAction === 'grid-start' ? 'Starting…' : `Start Grid${gridStartMode === 'live' ? ' (LIVE)' : ''}`}
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={onStopGrid}
            disabled={busyAction !== null}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-red-500/15 text-red-300 border border-red-500/30 hover:bg-red-500/20 disabled:opacity-50"
          >
            <Square className="w-3.5 h-3.5" />
            {busyAction === 'grid-stop' ? 'Stopping…' : 'Stop Grid'}
          </button>
        )}

        {killActive && (
          <span className="text-[11px] text-red-300">Grid start disabled while kill switch is active.</span>
        )}
        {gridStartMode === 'live' && !gridRunning && !killActive && (
          <span className="text-[11px] text-red-300 font-semibold">⚠ LIVE mode — real money at risk</span>
        )}
      </div>

      {message && <p className="text-xs text-emerald-300">{message}</p>}
      {error && <p className="text-xs text-red-300">{error}</p>}
    </section>
  );
}
