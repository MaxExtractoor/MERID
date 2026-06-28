/**
 * Grid View — Agent Management and Deployment
 */

import { useEffect } from 'react';
import { useKalshiStore, selectGrid, selectConnected } from '../store';
import { LayoutGrid, Activity, Play, Square } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { Button } from '../ui';

const Grid = () => {
  const refreshAll = useKalshiStore(state => state.refreshAll);
  const grid = useKalshiStore(selectGrid);
  const connected = useKalshiStore(selectConnected);

  useEffect(() => {
    refreshAll();
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
                <span className="text-white">{grid.agents.length}</span>
              </div>
              <div className="flex gap-2 mt-4">
                <Button variant="outline" size="sm">
                  <Play className="w-4 h-4 mr-2" />
                  Start Grid
                </Button>
                <Button variant="danger" size="sm">
                  <Square className="w-4 h-4 mr-2" />
                  Stop Grid
                </Button>
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
                    <Badge variant={agent.running ? 'success' : 'danger'}>
                      {agent.running ? 'Running' : 'Stopped'}
                    </Badge>
                  </div>
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
