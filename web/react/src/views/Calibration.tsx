/**
 * Calibration View — Agent Calibration and Consensus
 */

import { useEffect } from 'react';
import { useKalshiStore, selectConnected } from '../store';
import { Target, Activity } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import { Badge } from '../ui/Badge';

const Calibration = () => {
  const refreshAll = useKalshiStore(state => state.refreshAll);
  const connected = useKalshiStore(selectConnected);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Target className="w-8 h-8 text-rose-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Calibration</h1>
            <p className="text-sm text-slate-400">Agent calibration and consensus</p>
          </div>
        </div>
        <Badge variant={connected ? 'success' : 'danger'}>
          {connected ? 'Connected' : 'Disconnected'}
        </Badge>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Calibration Status</CardTitle>
        </CardHeader>
        <CardContent>
          {!connected ? (
            <div className="text-center py-4 text-slate-500">Waiting for backend connection...</div>
          ) : (
            <div className="text-center py-8 text-slate-400">
              <Activity className="w-12 h-12 mx-auto mb-4 text-slate-600" />
              <p>Calibration view coming soon</p>
              <p className="text-sm mt-2">This view will display agent calibration metrics and consensus data.</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default Calibration;
