/**
 * Settings View — Live System State (read-only)
 *
 * The backend exposes no config-mutation endpoints for this dashboard
 * (/api/v1/{agents,trading,risk,user,notifications}/config do not exist).
 * This panel therefore renders authoritative live state only — no fake
 * Save button, no dead POSTs.
 *
 * Data:
 * - Mode/kill switch/live runtime state: store (live-runtime-state + kill-switch)
 * - Venue readiness: GET /api/health/kalshi-readiness
 * - Category trading modes: GET /api/v1/kalshi/categories
 */

import { useEffect } from 'react';
import { useKalshiStore, selectRisk, selectSystem, selectConnected } from '../store';
import { Settings as SettingsIcon, Shield, Sliders, Activity } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { apiUrl } from '../config/apiBase';
import { useApiQuery } from '../hooks/useTanStackQuery';

interface ReadinessResponse {
  status?: string;
  error?: string;
  reasons?: string[];
  checks?: Record<string, unknown>;
  [key: string]: unknown;
}

interface CategoriesResponse {
  categories?: Record<string, string>;
  known?: string[];
}

const readinessVariant = (status?: string): 'success' | 'warning' | 'danger' => {
  const s = (status ?? '').toLowerCase();
  if (s === 'healthy' || s === 'ready' || s === 'ok') return 'success';
  if (s === 'degraded' || s === 'partial') return 'warning';
  return 'danger';
};

const categoryVariant = (mode: string): 'success' | 'warning' | 'danger' => {
  if (mode === 'live') return 'success';
  if (mode === 'read-only') return 'warning';
  return 'danger';
};

const Settings = () => {
  const refreshAll = useKalshiStore(state => state.refreshAll);
  const risk = useKalshiStore(selectRisk);
  const system = useKalshiStore(selectSystem);
  const connected = useKalshiStore(selectConnected);

  useEffect(() => {
    refreshAll();
    const interval = setInterval(() => { void refreshAll(); }, 30000);
    return () => clearInterval(interval);
  }, [refreshAll]);

  const readiness = useApiQuery<ReadinessResponse>(
    apiUrl('/api/health/kalshi-readiness'),
    { refetchInterval: 30_000, staleTime: 10_000 }
  );
  const categories = useApiQuery<CategoriesResponse>(
    apiUrl('/api/v1/kalshi/categories'),
    { refetchInterval: 60_000, staleTime: 30_000 }
  );

  const readinessData = readiness.data;
  const readinessStatus = readinessData?.status ?? (readiness.isLoading ? 'loading' : 'unavailable');
  const categoryEntries = Object.entries(
    categories.data?.categories ?? {} as Record<string, string>
  ) as Array<[string, string]>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <SettingsIcon className="w-8 h-8 text-slate-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Settings</h1>
            <p className="text-sm text-slate-400">
              Live system state — read-only. Runtime changes go through the
              trading process, not this dashboard.
            </p>
          </div>
        </div>
        <Badge variant={connected ? 'success' : 'danger'}>
          {connected ? 'Connected' : 'Disconnected'}
        </Badge>
      </div>

      {/* Live runtime state */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="w-5 h-5 text-blue-400" />
            Runtime State
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Order mode</span>
              <Badge variant={system.mode === 'live' ? 'success' : 'info'}>
                {system.mode.toUpperCase()}
              </Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Live runtime state</span>
              <Badge variant={system.live?.entry_halted ? 'warning' : 'success'}>
                {system.live?.state ?? 'UNKNOWN'}
              </Badge>
            </div>
            {system.live?.reason && (
              <div className="text-xs text-slate-500">Reason: {system.live.reason}</div>
            )}
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Kill switch</span>
              <Badge variant={risk.kill_switch_active ? 'danger' : 'success'}>
                {risk.kill_switch_active ? 'ACTIVE' : 'INACTIVE'}
              </Badge>
            </div>
            {risk.kill_switch_reason && (
              <div className="text-xs text-slate-500">{risk.kill_switch_reason}</div>
            )}
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Backend startup</span>
              <span className="text-white">{system.startup_completed ? 'completed' : 'in progress / unknown'}</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Venue readiness */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Shield className="w-5 h-5 text-emerald-400" />
            Venue Readiness
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Kalshi readiness</span>
              <Badge variant={readinessVariant(readinessStatus)}>
                {readinessStatus.toUpperCase()}
              </Badge>
            </div>
            {readinessData?.error && (
              <div className="text-xs text-red-400">{readinessData.error}</div>
            )}
            {Array.isArray(readinessData?.reasons) && readinessData.reasons.length > 0 && (
              <ul className="text-xs text-slate-400 space-y-1 list-disc list-inside">
                {readinessData.reasons.slice(0, 8).map((r: string, i: number) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            )}
            {readiness.error && (
              <div className="text-xs text-red-400">
                Readiness check failed: {String(readiness.error)}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Category trading modes */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sliders className="w-5 h-5 text-purple-400" />
            Category Trading Modes
          </CardTitle>
        </CardHeader>
        <CardContent>
          {categories.error ? (
            <div className="text-xs text-red-400">
              Failed to load categories: {String(categories.error)}
            </div>
          ) : categoryEntries.length === 0 ? (
            <div className="text-center py-4 text-slate-500">
              {categories.isLoading ? 'Loading categories...' : 'No category modes reported'}
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {categoryEntries.map(([cat, mode]) => (
                <div key={cat} className="flex items-center justify-between p-2 rounded border border-slate-700/60">
                  <span className="text-sm text-slate-300">{cat}</span>
                  <Badge variant={categoryVariant(mode)}>{mode}</Badge>
                </div>
              ))}
            </div>
          )}
          <p className="text-xs text-slate-500 mt-3">
            Category modes are managed on the backend; this view is read-only.
          </p>
        </CardContent>
      </Card>
    </div>
  );
};

export default Settings;
