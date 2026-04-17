/**
 * CryptoLanesGrid — Grid view for crypto trading lanes.
 *
 * Shows:
 *   - Live and paper crypto lanes (BTC, ETH, SOL, XRP)
 *   - Lane status, positions, and performance metrics
 *   - Controls for starting/stopping individual lanes
 *   - Fear & Greed integration and edge metrics
 */

import { useState, useMemo } from 'react';
import { useApiData } from '../hooks/useApiData';
import { logUiError } from '../utils/logger';
import { API_BASE_URL } from '../config/constants';
import { authHeaders } from '../api/auth';
import {
  Play, Square, RefreshCw,
  Activity, Clock, DollarSign, Target, Zap,
  CheckCircle
} from '../ui/icons';

// Types
type CryptoLaneStatus = {
  lane_id: string;
  symbol: "BTC" | "ETH" | "SOL" | "XRP";
  enabled: boolean;
  running: boolean;
  open_positions: number;
  max_positions: number;
  markets_live: number;
  max_markets_live: number;
  last_edge_bps: number;
  last_p_model: number;
  last_fg_contrarian: number;
  last_updated: number;
  paper?: boolean;
};

type ApiResponse = {
  lanes?: CryptoLaneStatus[];
  total_lanes?: number;
  running_lanes?: number;
  timestamp?: number;
};

export function CryptoLanesGrid() {
  const [, setRefreshKey] = useState(0);
  const [toggling, setToggling] = useState<Record<string, boolean>>({});

  // Fetch lane data
  const { data: apiData, loading, error } = useApiData<ApiResponse>(
    `${API_BASE_URL}/api/v1/lanes/crypto/status`,
    { }
  );

  // Filter crypto lanes
  const cryptoLanes = useMemo(() => {
    if (!apiData?.lanes) return [];
    
    return apiData.lanes.filter(lane =>
      lane.lane_id.endsWith("_15M") || lane.lane_id.endsWith("_15M_PAPER")
    );
  }, [apiData]);

  // Toggle lane state
  const toggleLane = async (laneId: string, enabled: boolean) => {
    setToggling(prev => ({ ...prev, [laneId]: true }));
    
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/lanes/${laneId}/toggle`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ enabled }),
      });

      if (!response.ok) {
        throw new Error(`Failed to toggle lane: ${response.statusText}`);
      }

      // Refresh data after successful toggle
      setRefreshKey(prev => prev + 1);
    } catch (error) {
      logUiError('CryptoLanesGrid', 'Failed to toggle lane', error, { laneId, enabled });
    } finally {
      setToggling(prev => ({ ...prev, [laneId]: false }));
    }
  };

  // Format timestamp
  const formatTime = (timestamp: number) => {
    return new Date(timestamp * 1000).toLocaleTimeString();
  };

  // Format edge with color
  const formatEdge = (edgeBps: number) => {
    const color = edgeBps > 0 ? 'text-green-600' : edgeBps < 0 ? 'text-red-600' : 'text-gray-600';
    const sign = edgeBps > 0 ? '+' : '';
    return <span className={color}>{sign}{edgeBps.toFixed(1)}</span>;
  };

  // Get status badge
  const getStatusBadge = (lane: CryptoLaneStatus) => {
    if (!lane.enabled) {
      return <span className="pill pill-disabled">DISABLED</span>;
    }
    
    if (lane.running) {
      return <span className="pill pill-live">RUNNING</span>;
    }
    
    return <span className="pill pill-idle">IDLE</span>;
  };

  // Get mode badge
  const getModeBadge = (lane: CryptoLaneStatus) => {
    const isPaper = lane.lane_id.endsWith("_PAPER");
    return (
      <span className={`pill ${isPaper ? 'pill-paper' : 'pill-live-mode'}`}>
        {isPaper ? 'PAPER' : 'LIVE'}
      </span>
    );
  };

  if (loading) {
    return (
      <div className="card">
        <div className="card-header">
          <h3 className="card-title">Crypto Trading Lanes</h3>
        </div>
        <div className="card-body">
          <div className="loading-state">Loading crypto lanes...</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card">
        <div className="card-header">
          <h3 className="card-title">Crypto Trading Lanes</h3>
        </div>
        <div className="card-body">
          <div className="error-state">Failed to load crypto lanes</div>
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="card-header">
        <div className="flex items-center justify-between">
          <h3 className="card-title">Crypto Trading Lanes</h3>
          <div className="flex items-center gap-2">
            <div className="text-sm text-gray-600">
              {apiData?.running_lanes || 0} / {apiData?.total_lanes || 0} running
            </div>
            <button
              onClick={() => setRefreshKey(prev => prev + 1)}
              className="btn btn-secondary btn-sm"
              disabled={loading}
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      </div>
      
      <div className="card-body">
        {cryptoLanes.length === 0 ? (
          <div className="empty-state">
            <Target className="w-12 h-12 mx-auto mb-4 text-gray-400" />
            <h4 className="text-lg font-medium mb-2">No Crypto Lanes Found</h4>
            <p className="text-gray-600">Configure crypto trading lanes to see them here.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Lane</th>
                  <th>Mode</th>
                  <th>Status</th>
                  <th>Positions</th>
                  <th>Markets</th>
                  <th>Last Edge (bps)</th>
                  <th>P(model)</th>
                  <th>FG Contrarian</th>
                  <th>Last Updated</th>
                  <th>Controls</th>
                </tr>
              </thead>
              <tbody>
                {cryptoLanes.map(lane => {
                  const isToggling = toggling[lane.lane_id];
                  
                  return (
                    <tr key={lane.lane_id}>
                      <td>
                        <div className="flex items-center gap-2">
                          <DollarSign className="w-4 h-4 text-blue-600" />
                          <span className="font-medium">{lane.symbol}</span>
                        </div>
                      </td>
                      <td className="font-mono text-sm">{lane.lane_id}</td>
                      <td>{getModeBadge(lane)}</td>
                      <td>{getStatusBadge(lane)}</td>
                      <td>
                        <div className="flex items-center gap-2">
                          <span>{lane.open_positions}/{lane.max_positions}</span>
                          {lane.open_positions > 0 && (
                            <Activity className="w-3 h-3 text-green-500" />
                          )}
                        </div>
                      </td>
                      <td>
                        <div className="flex items-center gap-2">
                          <span>{lane.markets_live}/{lane.max_markets_live}</span>
                          {lane.markets_live > 0 && (
                            <CheckCircle className="w-3 h-3 text-green-500" />
                          )}
                        </div>
                      </td>
                      <td>{formatEdge(lane.last_edge_bps)}</td>
                      <td>{(lane.last_p_model * 100).toFixed(1)}%</td>
                      <td>
                        <div className="flex items-center gap-1">
                          {formatEdge(lane.last_fg_contrarian * 100)}
                          {Math.abs(lane.last_fg_contrarian) > 0.0001 && (
                            <Zap className="w-3 h-3 text-yellow-500" />
                          )}
                        </div>
                      </td>
                      <td>
                        <div className="flex items-center gap-1 text-sm text-gray-600">
                          <Clock className="w-3 h-3" />
                          {formatTime(lane.last_updated)}
                        </div>
                      </td>
                      <td>
                        <button
                          onClick={() => toggleLane(lane.lane_id, !lane.enabled)}
                          disabled={isToggling}
                          className={`btn btn-sm ${
                            lane.enabled 
                              ? 'btn-danger' 
                              : 'btn-primary'
                          }`}
                        >
                          {isToggling ? (
                            <RefreshCw className="w-3 h-3 animate-spin" />
                          ) : lane.enabled ? (
                            <Square className="w-3 h-3" />
                          ) : (
                            <Play className="w-3 h-3" />
                          )}
                          {lane.enabled ? 'Stop' : 'Start'}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        
        {/* Summary Stats */}
        {cryptoLanes.length > 0 && (
          <div className="mt-6 pt-6 border-t border-gray-200">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="text-center">
                <div className="text-2xl font-bold text-blue-600">
                  {cryptoLanes.filter(l => !l.lane_id.endsWith("_PAPER")).length}
                </div>
                <div className="text-sm text-gray-600">Live Lanes</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-green-600">
                  {cryptoLanes.filter(l => l.lane_id.endsWith("_PAPER")).length}
                </div>
                <div className="text-sm text-gray-600">Paper Lanes</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-green-600">
                  {cryptoLanes.filter(l => l.running).length}
                </div>
                <div className="text-sm text-gray-600">Running</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-purple-600">
                  {cryptoLanes.reduce((sum, l) => sum + l.open_positions, 0)}
                </div>
                <div className="text-sm text-gray-600">Total Positions</div>
              </div>
            </div>
          </div>
        )}
      </div>
      
      <style>{`
        .pill {
          display: inline-block;
          padding: 0.25rem 0.5rem;
          border-radius: 0.25rem;
          font-size: 0.75rem;
          font-weight: 600;
          text-transform: uppercase;
        }
        
        .pill-live {
          background-color: #10b981;
          color: white;
        }
        
        .pill-live-mode {
          background-color: #3b82f6;
          color: white;
        }
        
        .pill-paper {
          background-color: #8b5cf6;
          color: white;
        }
        
        .pill-idle {
          background-color: #6b7280;
          color: white;
        }
        
        .pill-disabled {
          background-color: #ef4444;
          color: white;
        }
        
        .data-table {
          width: 100%;
          border-collapse: collapse;
        }
        
        .data-table th,
        .data-table td {
          padding: 0.75rem;
          text-align: left;
          border-bottom: 1px solid #e5e7eb;
        }
        
        .data-table th {
          font-weight: 600;
          color: #374151;
          background-color: #f9fafb;
        }
        
        .loading-state,
        .error-state,
        .empty-state {
          text-align: center;
          padding: 3rem 1rem;
          color: #6b7280;
        }
      `}</style>
    </div>
  );
}
