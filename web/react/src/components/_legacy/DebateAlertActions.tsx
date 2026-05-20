/**
 * DebateAlertActions - Quick action buttons for debate alert responses
 */

import { useState } from 'react';
import { Icon } from '../ui/icons';
import { API_BASE_URL, API_ENDPOINTS } from '../config/constants';

interface DebateAlertActionsProps {
  debateStatus: string;
  alertCount: number;
  onActionComplete?: (action: string) => void;
  className?: string;
}

export default function DebateAlertActions({ 
  debateStatus, 
  alertCount, 
  onActionComplete,
  className = '' 
}: DebateAlertActionsProps) {
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const handleQuickAction = async (action: string) => {
    setActionLoading(action);
    setActionError(null);
    
    try {
      let endpoint = '';
      let method = 'POST';
      
      switch (action) {
        case 'pause-agents':
          endpoint = '/api/v1/orchestrator/pause';
          break;
        case 'reduce-risk':
          endpoint = API_ENDPOINTS.KALSHI_RISK_DOWNSIZE;
          break;
        case 'refresh-debates':
          endpoint = '/api/v1/debates/refresh';
          break;
        case 'view-details':
          // Navigate to debate details page
          window.open('/debates', '_blank');
          onActionComplete?.(action);
          return;
        default:
          throw new Error(`Unknown action: ${action}`);
      }
      
      const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        method,
        headers: {
          'Content-Type': 'application/json',
        },
        body: action === 'reduce-risk' ? JSON.stringify({ asset: 'all' }) : undefined,
      });
      
      if (!response.ok) {
        throw new Error(`Action failed: ${response.statusText}`);
      }
      
      onActionComplete?.(action);
      
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Action failed');
    } finally {
      setActionLoading(null);
    }
  };

  if (alertCount === 0) {
    return null;
  }

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      {actionError && (
        <div className="flex items-center gap-1 px-2 py-1 bg-red-500/10 border border-red-500/30 rounded text-xs text-red-400">
          <Icon name="xCircle" size={10} className="w-2.5 h-2.5" />
          <span>{actionError}</span>
          <button
            type="button"
            onClick={() => setActionError(null)}
            className="ml-1 text-red-400 hover:text-red-300"
          >
            <Icon name="close" size={10} className="w-2.5 h-2.5" />
          </button>
        </div>
      )}
      
      {debateStatus === 'critical' && (
        <>
          <button
            type="button"
            onClick={() => handleQuickAction('pause-agents')}
            disabled={actionLoading === 'pause-agents'}
            className="flex items-center gap-1 px-2 py-1 bg-red-600 hover:bg-red-500 disabled:bg-red-700 disabled:opacity-50 rounded text-xs text-white transition-colors"
            title="Pause all trading agents"
          >
            {actionLoading === 'pause-agents' ? (
              <Icon name="loading" size={10} className="w-2.5 h-2.5 animate-spin" />
            ) : (
              <Icon name="pause" size={10} className="w-2.5 h-2.5" />
            )}
            Pause Agents
          </button>
          
          <button
            type="button"
            onClick={() => handleQuickAction('reduce-risk')}
            disabled={actionLoading === 'reduce-risk'}
            className="flex items-center gap-1 px-2 py-1 bg-orange-600 hover:bg-orange-500 disabled:bg-orange-700 disabled:opacity-50 rounded text-xs text-white transition-colors"
            title="Reduce position sizes by 50%"
          >
            {actionLoading === 'reduce-risk' ? (
              <Icon name="loading" size={10} className="w-2.5 h-2.5 animate-spin" />
            ) : (
              <Icon name="trendingDown" size={10} className="w-2.5 h-2.5" />
            )}
            Reduce Risk
          </button>
        </>
      )}
      
      {debateStatus === 'degraded' && (
        <>
          <button
            type="button"
            onClick={() => handleQuickAction('reduce-risk')}
            disabled={actionLoading === 'reduce-risk'}
            className="flex items-center gap-1 px-2 py-1 bg-yellow-600 hover:bg-yellow-500 disabled:bg-yellow-700 disabled:opacity-50 rounded text-xs text-white transition-colors"
            title="Reduce position sizes by 25%"
          >
            {actionLoading === 'reduce-risk' ? (
              <Icon name="loading" size={10} className="w-2.5 h-2.5 animate-spin" />
            ) : (
              <Icon name="trendingDown" size={10} className="w-2.5 h-2.5" />
            )}
            Reduce Risk
          </button>
          
          <button
            type="button"
            onClick={() => handleQuickAction('refresh-debates')}
            disabled={actionLoading === 'refresh-debates'}
            className="flex items-center gap-1 px-2 py-1 bg-blue-600 hover:bg-blue-500 disabled:bg-blue-700 disabled:opacity-50 rounded text-xs text-white transition-colors"
            title="Refresh debate data"
          >
            {actionLoading === 'refresh-debates' ? (
              <Icon name="loading" size={10} className="w-2.5 h-2.5 animate-spin" />
            ) : (
              <Icon name="refresh" size={10} className="w-2.5 h-2.5" />
            )}
            Refresh
          </button>
        </>
      )}
      
      <button
        type="button"
        onClick={() => handleQuickAction('view-details')}
        className="flex items-center gap-1 px-2 py-1 bg-slate-700 hover:bg-slate-600 rounded text-xs text-gray-300 transition-colors"
        title="View detailed debate information"
      >
        <Icon name="link" size={10} className="w-2.5 h-2.5" />
        Details
      </button>
    </div>
  );
}
