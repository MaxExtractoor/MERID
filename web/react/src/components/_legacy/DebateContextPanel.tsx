/**
 * DebateContextPanel - Compact panel showing debate context in summary section
 */

import { useState, useEffect } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { WS_URL } from '../config/constants';
import { Icon } from '../ui/icons';
import DebateAlertActions from './DebateAlertActions';

interface DebateContext {
  status: 'healthy' | 'degraded' | 'critical' | 'unknown';
  alerts_24h: {
    critical: number;
    warnings: number;
    total: number;
  };
  top_alerts: Array<{
    agent_id: string;
    severity: string;
    message: string;
    triggered_at: string;
  }>;
  top_teams: Array<{
    team_id: string;
    team_label: string;
    contribution_pct: number;
    sharpe_delta: number;
  }>;
  last_updated: string;
}

interface PredictionData {
  markets: any[];
  meta: {
    total: number;
    open: number;
    totalVolume: number;
    totalPnl: number;
    debate?: DebateContext;
  };
  timestamp: number;
}

function getDebateStatusColor(status: string) {
  switch (status) {
    case 'healthy':
      return 'text-green-400';
    case 'degraded':
      return 'text-yellow-400';
    case 'critical':
      return 'text-red-400';
    default:
      return 'text-gray-400';
  }
}

function getDebateStatusBg(status: string) {
  switch (status) {
    case 'healthy':
      return 'bg-green-400/10';
    case 'degraded':
      return 'bg-yellow-400/10';
    case 'critical':
      return 'bg-red-400/10';
    default:
      return 'bg-gray-400/10';
  }
}

function getDebateStatusIcon(status: string) {
  switch (status) {
    case 'healthy':
      return 'checkCircle';
    case 'degraded':
      return 'xCircle';
    case 'critical':
      return 'xCircle';
    default:
      return 'helpCircle';
  }
}

export default function DebateContextPanel() {
  const [debateContext, setDebateContext] = useState<DebateContext | null>(null);
  
  // Use WebSocket to get prediction data with debate context
  const { lastMessage } = useWebSocket<PredictionData>({
    url: WS_URL.replace('/ws/trades', '/ws/prediction'),
    autoConnect: true,
    heartbeatMs: 30000,
  });

  useEffect(() => {
    if (lastMessage && lastMessage.meta?.debate) {
      setDebateContext(lastMessage.meta.debate);
    }
  }, [lastMessage]);

  const statusColor = getDebateStatusColor(debateContext?.status || 'unknown');
  const statusBg = getDebateStatusBg(debateContext?.status || 'unknown');
  const statusIcon = getDebateStatusIcon(debateContext?.status || 'unknown');

  return (
    <div className={`rounded-xl p-3 border ${statusBg} border-current/20`}>
      <div className="flex items-center gap-1.5 mb-2">
        <Icon name={statusIcon} size={14} className={`w-3.5 h-3.5 ${statusColor}`} />
        <span className="text-[10px] text-gray-500 uppercase tracking-wider">Debate</span>
        {debateContext && (
          <span className={`text-[8px] px-1.5 py-0.5 rounded ${statusBg} ${statusColor} font-medium`}>
            {debateContext.status.toUpperCase()}
          </span>
        )}
      </div>
      
      {debateContext ? (
        <div className="space-y-1">
          {/* Row 1: Debate alerts (24h) */}
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-gray-400">Alerts (24h):</span>
            <div className="flex items-center gap-1">
              {debateContext.alerts_24h.critical > 0 && (
                <span className="text-[10px] text-red-400 font-medium">
                  {debateContext.alerts_24h.critical}C
                </span>
              )}
              {debateContext.alerts_24h.warnings > 0 && (
                <span className="text-[10px] text-yellow-400 font-medium">
                  {debateContext.alerts_24h.warnings}W
                </span>
              )}
              <span className="text-[10px] text-white font-medium">
                {debateContext.alerts_24h.total}T
              </span>
            </div>
          </div>
          
          {/* Row 2: Top teams by debate contribution */}
          {debateContext.top_teams.length > 0 && (
            <div className="space-y-1">
              <div className="text-[10px] text-gray-400">Top Teams:</div>
              <div className="space-y-0.5">
                {debateContext.top_teams.slice(0, 2).map((team, index) => (
                  <div key={index} className="flex items-center justify-between">
                    <span className="text-[9px] text-gray-300 truncate flex-1 mr-1">
                      {team.team_label.length > 12 
                        ? `${team.team_label.substring(0, 12)}...`
                        : team.team_label
                      }
                    </span>
                    <span className="text-[9px] text-emerald-400 font-medium">
                      +{(team.contribution_pct * 100).toFixed(1)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
          
          {/* Last updated */}
          <div className="text-[8px] text-gray-500 pt-1 border-t border-gray-700">
            {new Date(debateContext.last_updated).toLocaleTimeString()}
          </div>
          
          {/* Alert Actions */}
          <div className="pt-2 border-t border-gray-700">
            <DebateAlertActions 
              debateStatus={debateContext.status}
              alertCount={debateContext.alerts_24h.total}
              onActionComplete={(action) => {
                console.log(`Debate action completed: ${action}`);
              }}
              className="flex-col gap-1"
            />
          </div>
        </div>
      ) : (
        <div className="space-y-1">
          <div className="text-lg font-bold text-gray-400">—</div>
          <p className="text-[10px] text-gray-600">Loading debate context...</p>
        </div>
      )}
    </div>
  );
}
