/**
 * Calibration View — Agent Calibration and Consensus
 */

import { useEffect, useState } from 'react';
import { useKalshiStore, selectConnected } from '../store';
import { Target, Activity } from '../ui/icons';
import { Card, CardContent, CardHeader, CardTitle } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { API_BASE_URL } from '../config/constants';

interface AgentCalibration {
  name: string;
  asset: string;
  brier_score: number;
  rolling_brier: number;
  consensus_weight: number;
  calibration_history: { timestamp: string; brier_score: number }[];
}

const Calibration = () => {
  const refreshAll = useKalshiStore(state => state.refreshAll);
  const connected = useKalshiStore(selectConnected);
  const [calibrationData, setCalibrationData] = useState<AgentCalibration[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  useEffect(() => {
    const fetchCalibration = async () => {
      if (!connected) return;
      setLoading(true);
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/calibration/metrics`);
        if (!response.ok) throw new Error('Failed to fetch calibration data');
        const data = await response.json();
        setCalibrationData(data.agents || []);
      } catch (err) {
        console.error('Failed to fetch calibration data:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchCalibration();
  }, [connected]);

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
          <CardTitle>Agent Calibration Metrics</CardTitle>
        </CardHeader>
        <CardContent>
          {!connected ? (
            <div className="text-center py-4 text-slate-500">Waiting for backend connection...</div>
          ) : loading ? (
            <div className="text-center py-4 text-slate-500">Loading calibration data...</div>
          ) : calibrationData.length === 0 ? (
            <div className="text-center py-8 text-slate-400">
              <Activity className="w-12 h-12 mx-auto mb-4 text-slate-600" />
              <p>No calibration data available</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-500 text-xs uppercase">
                    <th className="text-left p-3">Agent</th>
                    <th className="text-left p-3">Asset</th>
                    <th className="text-right p-3">Brier Score</th>
                    <th className="text-right p-3">Rolling Brier</th>
                    <th className="text-right p-3">Consensus Weight</th>
                  </tr>
                </thead>
                <tbody>
                  {calibrationData.map((agent) => (
                    <tr key={agent.name} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                      <td className="p-3 font-medium text-white">{agent.name}</td>
                      <td className="p-3">
                        <Badge variant="success">{agent.asset}</Badge>
                      </td>
                      <td className="p-3 text-right font-mono">{agent.brier_score.toFixed(4)}</td>
                      <td className="p-3 text-right font-mono">{agent.rolling_brier.toFixed(4)}</td>
                      <td className="p-3 text-right font-mono">{(agent.consensus_weight * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default Calibration;
