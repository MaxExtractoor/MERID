import { useState, useCallback } from 'react';
import { Shield, ShieldCheck, ShieldAlert, Wifi, Activity, Tag, ToggleLeft, ToggleRight } from '../ui/icons';
import { useApiQuery } from '../hooks/useTanStackQuery';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from '../config/constants';

interface ContractHealthData {
  api_v1_route_count: number;
  sse_endpoint_count: number;
  sse_endpoints: string[];
  profile: string;
  feature_flags: Record<string, boolean>;
  timestamp: number;
}

export default function ContractHealthPanel() {
  const { data, isLoading, error } = useApiQuery<ContractHealthData>(
    API_ENDPOINTS.SYSTEM_CONTRACT_HEALTH,
    { refetchInterval: DEFAULTS.POLLING_INTERVALS.SLOW }
  );

  const [flagOverrides, setFlagOverrides] = useState<Record<string, boolean>>({});
  const [toggling, setToggling] = useState<string | null>(null);

  const toggleFlag = useCallback(async (name: string, currentEnabled: boolean) => {
    const newEnabled = !currentEnabled;
    setToggling(name);
    setFlagOverrides(prev => ({ ...prev, [name]: newEnabled }));
    try {
      const resp = await fetch(`${API_BASE_URL}${API_ENDPOINTS.SYSTEM_FEATURE_FLAGS}/${name}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: newEnabled }),
      });
      if (!resp.ok) {
        setFlagOverrides(prev => { const n = { ...prev }; delete n[name]; return n; });
      }
    } catch {
      setFlagOverrides(prev => { const n = { ...prev }; delete n[name]; return n; });
    } finally {
      setToggling(null);
    }
  }, []);

  if (isLoading && !data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-4 animate-pulse">
        <div className="h-4 bg-slate-700 rounded w-1/3 mb-3" />
        <div className="h-16 bg-slate-800 rounded" />
      </div>
    );
  }

  const profileLabel = data?.profile === 'kalshi-only' || data?.profile === 'kalshi_only' || data?.profile === 'kalshi'
    ? 'kalshi-only'
    : data?.profile ?? 'unknown';

  const routeOk = (data?.api_v1_route_count ?? 0) > 50;
  const sseOk = (data?.sse_endpoint_count ?? 0) >= 2;
  const overallOk = routeOk && sseOk;

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Shield className="w-4 h-4 text-blue-400" />
        <h3 className="text-sm font-semibold text-slate-300">Contract Health</h3>
        {error && <span className="text-[10px] text-red-400 ml-auto">{error.message}</span>}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {/* UI↔API Contract */}
        <div className={`rounded-lg p-3 ${routeOk ? 'bg-emerald-950/30 border border-emerald-700/30' : 'bg-red-950/40 border border-red-700/40'}`}>
          <p className="text-[10px] text-slate-500 uppercase">UI↔API Contract</p>
          <div className="flex items-center gap-1.5 mt-1">
            {routeOk ? <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" /> : <ShieldAlert className="w-3.5 h-3.5 text-red-400" />}
            <span className={`text-sm font-bold ${routeOk ? 'text-emerald-400' : 'text-red-400'}`}>
              {routeOk ? 'OK' : 'DEGRADED'}
            </span>
          </div>
          <p className="text-[10px] text-slate-500 mt-0.5">{data?.api_v1_route_count ?? 0} routes</p>
        </div>

        {/* SSE Wiring */}
        <div className={`rounded-lg p-3 ${sseOk ? 'bg-emerald-950/30 border border-emerald-700/30' : 'bg-amber-950/30 border border-amber-700/30'}`}>
          <p className="text-[10px] text-slate-500 uppercase">SSE Wiring</p>
          <div className="flex items-center gap-1.5 mt-1">
            {sseOk ? <Wifi className="w-3.5 h-3.5 text-emerald-400" /> : <Activity className="w-3.5 h-3.5 text-amber-400" />}
            <span className={`text-sm font-bold ${sseOk ? 'text-emerald-400' : 'text-amber-400'}`}>
              {sseOk ? 'OK' : 'WARN'}
            </span>
          </div>
          <p className="text-[10px] text-slate-500 mt-0.5">{data?.sse_endpoint_count ?? 0} streams</p>
        </div>

        {/* Profile */}
        <div className="rounded-lg p-3 bg-slate-800">
          <p className="text-[10px] text-slate-500 uppercase">Profile</p>
          <div className="flex items-center gap-1.5 mt-1">
            <Tag className="w-3.5 h-3.5 text-blue-400" />
            <span className="text-sm font-bold text-white">{profileLabel}</span>
          </div>
        </div>

        {/* Overall */}
        <div className={`rounded-lg p-3 ${overallOk ? 'bg-emerald-950/30 border border-emerald-700/30' : 'bg-red-950/40 border border-red-700/40'}`}>
          <p className="text-[10px] text-slate-500 uppercase">Overall</p>
          <div className="flex items-center gap-1.5 mt-1">
            {overallOk ? <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" /> : <ShieldAlert className="w-3.5 h-3.5 text-red-400" />}
            <span className={`text-sm font-bold ${overallOk ? 'text-emerald-400' : 'text-red-400'}`}>
              {overallOk ? 'HEALTHY' : 'CHECK'}
            </span>
          </div>
        </div>
      </div>

      {/* Feature Flags */}
      {data?.feature_flags && Object.keys(data.feature_flags).length > 0 && (
        <div className="pt-2 border-t border-slate-800">
          <p className="text-[10px] text-slate-500 uppercase mb-2">Feature Flags</p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(data.feature_flags).map(([name, serverEnabled]) => {
              const enabled = name in flagOverrides ? flagOverrides[name] : serverEnabled;
              const isToggling = toggling === name;
              return (
                <button
                  key={name}
                  onClick={() => toggleFlag(name, enabled as boolean)}
                  disabled={isToggling}
                  className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-xs cursor-pointer transition-opacity ${
                    isToggling ? 'opacity-50' : 'hover:opacity-80'
                  } ${
                    enabled
                      ? 'bg-emerald-950/30 text-emerald-400 border border-emerald-700/30'
                      : 'bg-slate-800 text-slate-500 border border-slate-700'
                  }`}
                  title={`Click to ${enabled ? 'disable' : 'enable'} ${name}`}
                >
                  {enabled ? <ToggleRight className="w-3 h-3" /> : <ToggleLeft className="w-3 h-3" />}
                  <span className="font-mono">{name.replace(/_/g, '-')}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
