import React, { useEffect, useState, useCallback } from 'react';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS, AUTH_TOKEN_KEY } from '../config/constants';

const authHeaders = (): HeadersInit => {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  return { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}) };
};

interface CorrelationPair {
  asset_a: string;
  asset_b: string;
  correlation: number;
  sample_count: number;
}

interface ClusterInfo {
  cluster_name: string;
  members: string[];
  pairs: {
    asset_a: string;
    asset_b: string;
    correlation: number;
    reduction_factor: number;
  }[];
}

interface MatrixData {
  assets: string[];
  pairs: CorrelationPair[];
}

export const CorrelationRiskPanel: React.FC = () => {
  const [matrix, setMatrix] = useState<MatrixData | null>(null);
  const [clusters, setClusters] = useState<ClusterInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setError(null);
    try {
      const opts = { headers: authHeaders() };
      const [matrixRes, clusterRes] = await Promise.all([
        fetch(`${API_BASE_URL}${API_ENDPOINTS.CORRELATION_MATRIX}`, opts),
        fetch(`${API_BASE_URL}${API_ENDPOINTS.CORRELATION_CLUSTERS}`, opts),
      ]);
      if (matrixRes.ok) {
        const matrixJson = await matrixRes.json();
        setMatrix(matrixJson.matrix || null);
      }
      if (clusterRes.ok) {
        const clusterJson = await clusterRes.json();
        setClusters(clusterJson.clusters || []);
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load correlation data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, DEFAULTS.POLLING_INTERVALS.SLOW);
    return () => clearInterval(interval);
  }, [fetchData]);

  const corrColor = (corr: number): string => {
    const abs = Math.abs(corr);
    if (abs >= 0.8) return 'text-red-400';
    if (abs >= 0.5) return 'text-amber-400';
    if (abs >= 0.3) return 'text-yellow-300';
    return 'text-emerald-400';
  };

  const corrBg = (corr: number): string => {
    const abs = Math.abs(corr);
    if (abs >= 0.8) return 'bg-red-500/20';
    if (abs >= 0.5) return 'bg-amber-500/15';
    if (abs >= 0.3) return 'bg-yellow-500/10';
    return 'bg-emerald-500/10';
  };

  const factorBadge = (factor: number): { label: string; className: string } => {
    if (factor >= 0.99) return { label: 'No reduction', className: 'bg-emerald-500/20 text-emerald-400' };
    if (factor >= 0.7) return { label: 'Mild', className: 'bg-yellow-500/20 text-yellow-300' };
    if (factor >= 0.5) return { label: 'Moderate', className: 'bg-amber-500/20 text-amber-400' };
    return { label: 'Severe', className: 'bg-red-500/20 text-red-400' };
  };

  if (loading) {
    return (
      <div className="bg-[#1a1a2e] border border-gray-700/50 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-300 mb-3">Correlation Risk</h3>
        <div className="animate-pulse space-y-2">
          <div className="h-4 bg-gray-700 rounded w-3/4" />
          <div className="h-4 bg-gray-700 rounded w-1/2" />
        </div>
      </div>
    );
  }

  return (
    <div className="bg-[#1a1a2e] border border-gray-700/50 rounded-lg p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-300">
          Correlation Risk Matrix
        </h3>
        {matrix && (
          <span className="text-xs text-gray-500">
            {matrix.assets.length} assets tracked
          </span>
        )}
      </div>

      {error && (
        <div className="text-xs text-red-400 bg-red-500/10 rounded px-2 py-1">
          {error}
        </div>
      )}

      {/* Correlation Matrix Grid */}
      {matrix && matrix.pairs.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-gray-700/50">
                <th className="text-left text-gray-500 py-1 px-2">Pair</th>
                <th className="text-right text-gray-500 py-1 px-2">ρ</th>
                <th className="text-right text-gray-500 py-1 px-2">Samples</th>
                <th className="text-center text-gray-500 py-1 px-2">Level</th>
              </tr>
            </thead>
            <tbody>
              {matrix.pairs.map((pair) => (
                <tr
                  key={`${pair.asset_a}-${pair.asset_b}`}
                  className="border-b border-gray-800/30 hover:bg-gray-800/20"
                >
                  <td className="py-1.5 px-2 text-gray-300 font-mono">
                    {pair.asset_a}/{pair.asset_b}
                  </td>
                  <td className={`py-1.5 px-2 text-right font-mono font-semibold ${corrColor(pair.correlation)}`}>
                    {(pair.correlation ?? 0).toFixed(3)}
                  </td>
                  <td className="py-1.5 px-2 text-right text-gray-500">
                    {pair.sample_count}
                  </td>
                  <td className="py-1.5 px-2 text-center">
                    <span className={`inline-block w-16 rounded px-1.5 py-0.5 text-center text-[10px] font-medium ${corrBg(pair.correlation)} ${corrColor(pair.correlation)}`}>
                      {Math.abs(pair.correlation) >= 0.8 ? 'HIGH' :
                       Math.abs(pair.correlation) >= 0.5 ? 'MED' :
                       Math.abs(pair.correlation) >= 0.3 ? 'LOW' : 'NONE'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {matrix && matrix.pairs.length === 0 && (
        <div className="text-xs text-gray-500 text-center py-4">
          No correlation data yet — returns will be recorded as agents trade
        </div>
      )}

      {/* Cluster Exposure Adjustments */}
      {clusters.length > 0 && (
        <div className="space-y-2">
          <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
            Cluster Caps
          </h4>
          {clusters.map((cluster) => (
            <div
              key={cluster.cluster_name}
              className="bg-gray-800/30 rounded p-2.5 space-y-1.5"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-mono text-gray-300">
                  {cluster.cluster_name}
                </span>
                <span className="text-[10px] text-gray-500">
                  {cluster.members.join(' + ')}
                </span>
              </div>
              {cluster.pairs.map((p) => {
                const badge = factorBadge(p.reduction_factor);
                return (
                  <div
                    key={`${p.asset_a}-${p.asset_b}`}
                    className="flex items-center justify-between text-[11px]"
                  >
                    <span className="text-gray-400">
                      {p.asset_a}/{p.asset_b}: ρ={(p.correlation ?? 0).toFixed(3)}
                    </span>
                    <span className={`rounded px-1.5 py-0.5 ${badge.className}`}>
                      Cap ×{(p.reduction_factor ?? 0).toFixed(2)} — {badge.label}
                    </span>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default CorrelationRiskPanel;
