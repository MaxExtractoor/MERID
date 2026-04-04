import { useState } from 'react';
import {
  Settings, Shield, AlertTriangle,
  RefreshCw, Play, Pause, Zap
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import ErrorBar from './ErrorBar';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS} from '../config/constants';

function authHeaders(headers?: HeadersInit): HeadersInit {
  const token = localStorage.getItem('merid-access');
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(headers ?? {}),
  };
}

interface VenueMode {
  venue: string;
  domain: string;
  mode: 'SIM' | 'PAPER' | 'LIVE';
  enabled: boolean;
  lastModeChange: string | null;
}

const MODE_COLORS: Record<string, { bg: string; text: string; ring: string }> = {
  SIM: { bg: 'bg-gray-500/20', text: 'text-gray-300', ring: 'ring-gray-500' },
  PAPER: { bg: 'bg-amber-500/20', text: 'text-amber-400', ring: 'ring-amber-500' },
  LIVE: { bg: 'bg-red-500/20', text: 'text-red-400', ring: 'ring-red-500' },
};

const DOMAIN_COLORS: Record<string, string> = {
  prediction: 'border-l-orange-400',
  crypto: 'border-l-blue-400',
  equity: 'border-l-green-400',
};

export default function ModeControlPanel() {
  const [confirmAction, setConfirmAction] = useState<{ venue: string; mode: string } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  const { data: rawData, loading, error: fetchError, refetch } = useApiData<{ venues: VenueMode[] }>(
    API_ENDPOINTS.PIPELINE_VENUES,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.MEDIUM },
  );

  if (fetchError && !rawData) {
    return <ErrorBar label="Mode control" error={fetchError} onRetry={refetch} />;
  }
  const venues = rawData?.venues ?? [];

  const changeMode = async (venue: string, newMode: string) => {
    if (newMode === 'LIVE') {
      setConfirmAction({ venue, mode: newMode });
      return;
    }
    await doChangeMode(venue, newMode);
  };

  const doChangeMode = async (venue: string, newMode: string) => {
    setActionLoading(true);
    setActionError(null);
    try {
      const modeRes = await fetch(`${API_BASE_URL}${API_ENDPOINTS.PIPELINE_VENUE_MODE}`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ venue, mode: newMode.toLowerCase() }),
      });
      if (!modeRes.ok) throw new Error(`HTTP ${modeRes.status}`);
    } catch (err) {
      setActionError(`Mode change failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
    refetch();
    setConfirmAction(null);
    setActionLoading(false);
  };

  const toggleEnabled = async (venue: string, enabled: boolean) => {
    setActionLoading(true);
    setActionError(null);
    const endpoint = enabled
      ? API_ENDPOINTS.PIPELINE_VENUE_TOGGLE('enable')
      : API_ENDPOINTS.PIPELINE_VENUE_TOGGLE('disable');
    try {
      const toggleRes = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ venue }),
      });
      if (!toggleRes.ok) throw new Error(`HTTP ${toggleRes.status}`);
    } catch (err) {
      setActionError(`Toggle failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
    refetch();
    setActionLoading(false);
  };

  const formatTimeAgo = (ts: string) => {
    if (!ts) return 'unknown';
    const ms = Date.now() - new Date(ts).getTime();
    if (Number.isNaN(ms) || ms < 0) return 'unknown';
    if (ms < 3600000) return `${Math.floor(ms / 60000)}m ago`;
    if (ms < 86400000) return `${Math.floor(ms / 3600000)}h ago`;
    return `${Math.floor(ms / 86400000)}d ago`;
  };

  const modes: Array<'SIM' | 'PAPER' | 'LIVE'> = ['SIM', 'PAPER', 'LIVE'];

  const simCount = venues.filter(v => v.mode === 'SIM').length;
  const paperCount = venues.filter(v => v.mode === 'PAPER').length;
  const liveCount = venues.filter(v => v.mode === 'LIVE').length;

  if (loading) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-2 text-gray-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span>Loading venue modes...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {actionError && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span className="truncate">{actionError}</span>
          <button type="button" onClick={() => setActionError(null)} className="ml-auto shrink-0 text-slate-400 hover:text-white" aria-label="Dismiss error">&times;</button>
        </div>
      )}
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Settings className="w-5 h-5 text-blue-400" />
          <h3 className="text-lg font-bold text-white">Mode Control</h3>
          <div className="flex items-center gap-1 ml-2">
            <span className="text-xs px-2 py-0.5 rounded bg-gray-500/20 text-gray-300">{simCount} SIM</span>
            <span className="text-xs px-2 py-0.5 rounded bg-amber-500/20 text-amber-400">{paperCount} PAPER</span>
            <span className="text-xs px-2 py-0.5 rounded bg-red-500/20 text-red-400">{liveCount} LIVE</span>
          </div>
        </div>
        <button type="button"
          onClick={() => refetch()}
          className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white transition-colors"
          title="Refresh venue modes"
         aria-label="Refresh">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Venue Cards */}
      <div className="space-y-3">
        {venues.map(v => {
          const domainColor = DOMAIN_COLORS[v.domain] || 'border-l-gray-400';

          return (
            <div
              key={v.venue}
              className={`bg-slate-800/50 rounded-lg border border-slate-700/50 border-l-4 ${domainColor} p-4 ${
                !v.enabled ? 'opacity-50' : ''
              }`}
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-3">
                  <span className="font-semibold text-white capitalize">{v.venue}</span>
                  <span className="text-xs text-gray-500 uppercase">{v.domain}</span>
                  {!v.enabled && (
                    <span className="text-xs px-1.5 py-0.5 rounded bg-gray-500/20 text-gray-400">disabled</span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                   <span className="text-xs text-gray-500">{formatTimeAgo(v.lastModeChange ?? '')}</span>
                  <button type="button"
                    onClick={() => toggleEnabled(v.venue, !v.enabled)}
                    disabled={actionLoading}
                    className={`p-1 rounded transition-colors disabled:opacity-50 ${
                      v.enabled
                        ? 'text-green-400 hover:bg-green-500/20'
                        : 'text-gray-500 hover:bg-gray-500/20'
                    }`}
                    title={v.enabled ? 'Disable venue' : 'Enable venue'}
                  >
                    {v.enabled ? <Play className="w-4 h-4" /> : <Pause className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              {/* Mode Selector */}
              <div className="flex gap-2">
                {modes.map(mode => {
                  const isActive = v.mode === mode;
                  const cfg = MODE_COLORS[mode];
                  return (
                    <button type="button"
                      key={mode}
                      onClick={() => v.enabled && changeMode(v.venue, mode)}
                      disabled={!v.enabled || actionLoading}
                      className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-all ${
                        isActive
                          ? `${cfg.bg} ${cfg.text} ring-1 ${cfg.ring}`
                          : 'bg-slate-900/50 text-gray-500 hover:text-gray-300 hover:bg-slate-700/50'
                      } ${!v.enabled ? 'cursor-not-allowed' : 'cursor-pointer'}`}
                    >
                      <div className="flex items-center justify-center gap-1.5">
                        {mode === 'LIVE' && <Zap className="w-3.5 h-3.5" />}
                        {mode === 'PAPER' && <Shield className="w-3.5 h-3.5" />}
                        {mode}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {/* Confirmation Dialog */}
      {confirmAction && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-slate-800 rounded-lg border border-red-500/50 p-6 max-w-md mx-4 space-y-4">
            <div className="flex items-center gap-2 text-red-400">
              <AlertTriangle className="w-5 h-5" />
              <h4 className="text-lg font-bold">Enable LIVE Trading</h4>
            </div>
            <p className="text-sm text-gray-300">
              You are about to switch <strong className="text-white">{confirmAction.venue}</strong> to{' '}
              <strong className="text-red-400">LIVE</strong> mode. This will execute real trades with real money.
            </p>
            <p className="text-xs text-gray-500">
              Ensure all risk limits are configured and the venue adapter is properly connected.
            </p>
            <div className="flex gap-3">
              <button type="button"
                onClick={() => setConfirmAction(null)}
                className="flex-1 py-2 px-4 rounded-lg bg-slate-700 text-gray-300 hover:bg-slate-600 transition-colors"
              >
                Cancel
              </button>
              <button type="button"
                onClick={() => doChangeMode(confirmAction.venue, confirmAction.mode)}
                className="flex-1 py-2 px-4 rounded-lg bg-red-600 text-white hover:bg-red-500 transition-colors font-medium"
              >
                Confirm LIVE
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
