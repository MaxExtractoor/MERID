/**
 * DebateStatusBadge - Shows debate system health status in header
 */

import { useState, useEffect } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { WS_URL } from '../config/constants';
import { Icon } from '../ui/icons';
import DebateTooltip from './DebateTooltip';

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
      return 'xCircle'; // Use xCircle as warning indicator
    case 'critical':
      return 'xCircle';
    default:
      return 'helpCircle';
  }
}

export default function DebateStatusBadge() {
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

  if (!debateContext) {
    return (
      <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800">
        <Icon name="helpCircle" size={14} className="w-3.5 h-3.5 text-gray-400" />
        <span className="text-xs font-medium text-gray-400">DEBATE</span>
      </div>
    );
  }

  const statusColor = getDebateStatusColor(debateContext.status);
  getDebateStatusBg(debateContext.status); // called for side effects
  const statusIcon = getDebateStatusIcon(debateContext.status);

  return (
    <DebateTooltip>
      <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-800">
        <Icon name={statusIcon} size={14} className={`w-3.5 h-3.5 ${statusColor}`} />
        <span className={`text-xs font-medium ${statusColor}`}>
          DEBATE {debateContext.status.toUpperCase()}
        </span>
        {debateContext.alerts_24h.total > 0 && (
          <span className={`text-[10px] ${statusColor}`}>
            ({debateContext.alerts_24h.total})
          </span>
        )}
      </div>
    </DebateTooltip>
  );
}
