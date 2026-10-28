/**
 * Grid View — Agent Management and Deployment
 *
 * Data: /api/v1/kalshi-grid/summary + /api/v1/kalshi-grid/agents (via store).
 *
 * NOTE: The backend exposes no grid or per-agent start/stop mutation routes
 * (verified in web/api/kalshi_agent_grid_api.py — only summary/edge/scheduler
 * reads exist). Controls are therefore rendered disabled with honest tooltips
 * rather than wired to dead endpoints.
 */

import { useEffect } from 'react';
import { useKalshiStore, selectGrid, selectConnected } from '../store';
import { LayoutGrid, Play, Square } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { Button } from '../ui';

const NO_MUTATION_TOOLTIP =
  'No start/stop endpoint exists on the backend — agent lifecycle is controlled by the trading process, not this dashboard.';

const formatAge = (ageS?: number): string => {
  if (ageS == null) return '—';
  if (ageS < 60) return `${ageS}s ago`;
  if (ageS < 3600) return `${Math.round(ageS / 60)}m ago`;
  return `${Math.round(ageS / 3600)}h ago`;
};

const Grid = () => {
  const refreshAll = useKalshiStore(state => state.refreshAll);
  const grid = useKalshiStore(selectGrid);
  const connected = useKalshiStore(selectConnected);

  useEffect(() => {
    refreshAll();
    const interval = setInterval(() => { void refreshAll(); }, 30000);
    return () => clearInterval(interval);
  }, [refreshAll]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <LayoutGrid className="w-8 h-8 text-orange-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Grid</h1>
            <p className="text-sm text-slate-400">Agent management and deployment</p>
          </div>
        </div>
        <Badge variant={connected ? 'success' : 'danger'}>
          {connected ? 'Connected' : 'Disconnected'}
        </Badge>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Agent Grid Status</CardTitle>
        </CardHeader>
        <CardContent>
          {!connected ? (
            <div className="text-center py-4 text-slate-500">Waiting for backend connection...</div>
          ) : (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Status</span>
                <Badge variant={grid.running ? 'success' : 'danger'}>
                  {grid.running ? 'Running' : 'Stopped'}
                </Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Mode</span>
                <span className="text-white">{grid.deployment.mode}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Agents</span>
                <span className="text-white">
                  {grid.agents.filter(a => a.running).length}/{grid.agents.length} running
                </span>
              </div>
              {/* Disabled: backend exposes no grid start/stop routes. */}
              <div className="flex gap-2 mt-4">
                <Button variant="outline" size="sm" disabled title={NO_MUTATION_TOOLTIP}>
                  <Play className="w-4 h-4 mr-2" />
                  Start Grid
                </Button>
                <Button variant="danger" size="sm" disabled title={NO_MUTATION_TOOLTIP}>
                  <Square className="w-4 h-4 mr-2" />
                  Stop Grid
                </Button>
              </div>
              <div className="text-xs text-slate-500">
                Start/stop is unavailable — the backend exposes no grid control endpoint.
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Agents</CardTitle>
        </CardHeader>
        <CardContent>
          {!connected ? (
            <div className="text-center py-4 text-slate-500">Waiting for backend connection...</div>
          ) : grid.agents.length === 0 ? (
            <div className="text-center py-4 text-slate-500">No agents configured</div>
          ) : (
            <div className="space-y-2">
              {grid.agents.map((agent) => (
                <div key={agent.name} className="p-3 rounded-lg border border-slate-700">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-white font-medium">{agent.name}</div>
                      <div className="text-sm text-slate-400">{agent.asset} • {agent.timeframe}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      {agent.enabled === false && (
                        <Badge variant="warning">disabled</Badge>
                      )}
                      <Badge variant={agent.running ? 'success' : 'danger'}>
                        {agent.state ?? (agent.running ? 'Running' : 'Stopped')}
                      </Badge>
                      {/* Disabled: no per-agent start/stop endpoint on the backend. */}
                      <Button
                        variant="outline"
                        size="sm"
                        disabled
                        title={NO_MUTATION_TOOLTIP}
                        aria-label={`${agent.running ? 'Stop' : 'Start'} ${agent.asset} agent (unavailable)`}
                      >
                        {agent.running ? <Square className="w-3 h-3" /> : <Play className="w-3 h-3" />}
                      </Button>
                    </div>
                  </div>
                  <div className="mt-2 grid grid-cols-2 md:grid-cols-4 gap-2 text-xs text-slate-400">
                    <span>Positions: {agent.position_count ?? '—'}</span>
                    <span>Last signal: {formatAge(agent.last_signal_age_s)}</span>
                    <span>Fills (24h): {agent.fills}</span>
                    <span>Cycles: {agent.cycles}</span>
                  </div>
                  {agent.rejected_reason && (
                    <div className="mt-2 text-xs text-amber-400/90">
                      Rejected: {agent.rejected_reason}
                    </div>
                  )}
                  {agent.current_task && (
                    <div className="mt-1 text-xs text-slate-500">{agent.current_task}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default Grid;
