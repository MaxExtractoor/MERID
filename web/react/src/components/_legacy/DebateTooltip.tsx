/**
 * DebateTooltip - Enhanced tooltip with comprehensive debate context
 */

import { useState } from 'react';
import { useDebateContext } from '../hooks/useDebateContext';
import { Icon } from '../ui/icons';

interface DebateTooltipProps {
  children: React.ReactNode;
  show?: boolean;
  className?: string;
}

export default function DebateTooltip({ children, show = true, className = '' }: DebateTooltipProps) {
  const { debateContext, loading } = useDebateContext();
  const [isVisible, setIsVisible] = useState(false);

  if (!show || loading || !debateContext) {
    return <>{children}</>;
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'healthy': return 'text-green-400';
      case 'degraded': return 'text-yellow-400';
      case 'critical': return 'text-red-400';
      default: return 'text-gray-400';
    }
  };

  const getStatusBg = (status: string) => {
    switch (status) {
      case 'healthy': return 'bg-green-400/10';
      case 'degraded': return 'bg-yellow-400/10';
      case 'critical': return 'bg-red-400/10';
      default: return 'bg-gray-400/10';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'healthy': return 'checkCircle';
      case 'degraded': return 'xCircle';
      case 'critical': return 'xCircle';
      default: return 'helpCircle';
    }
  };

  const statusColor = getStatusColor(debateContext.status);
  const statusBg = getStatusBg(debateContext.status);
  const statusIcon = getStatusIcon(debateContext.status);

  return (
    <div 
      className={`relative inline-block group ${className}`}
      onMouseEnter={() => setIsVisible(true)}
      onMouseLeave={() => setIsVisible(false)}
    >
      {children}
      
      {isVisible && (
        <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 w-80 p-4 bg-slate-900 border border-slate-700 rounded-lg shadow-xl z-50">
          {/* Arrow */}
          <div className="absolute top-full left-1/2 transform -translate-x-1/2 -mt-1">
            <div className="w-0 h-0 border-l-8 border-l-transparent border-r-8 border-r-transparent border-t-8 border-t-slate-700"></div>
          </div>
          
          {/* Header */}
          <div className="flex items-center gap-2 mb-3 pb-2 border-b border-slate-700">
            <Icon name={statusIcon} size={16} className={`w-4 h-4 ${statusColor}`} />
            <span className="font-semibold text-white">Debate System Status</span>
            <span className={`ml-auto text-xs px-2 py-1 rounded ${statusBg} ${statusColor} font-medium`}>
              {debateContext.status.toUpperCase()}
            </span>
          </div>
          
          {/* Alert Summary */}
          <div className="space-y-2 mb-3">
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="bg-slate-800 rounded p-2">
                <div className="text-lg font-bold text-red-400">{debateContext.alerts_24h.critical}</div>
                <div className="text-xs text-gray-400">Critical</div>
              </div>
              <div className="bg-slate-800 rounded p-2">
                <div className="text-lg font-bold text-yellow-400">{debateContext.alerts_24h.warnings}</div>
                <div className="text-xs text-gray-400">Warnings</div>
              </div>
              <div className="bg-slate-800 rounded p-2">
                <div className="text-lg font-bold text-white">{debateContext.alerts_24h.total}</div>
                <div className="text-xs text-gray-400">Total</div>
              </div>
            </div>
          </div>
          
          {/* Recent Alerts */}
          {debateContext.top_alerts.length > 0 && (
            <div className="mb-3">
              <h4 className="text-xs font-semibold text-gray-300 mb-2">Recent Alerts</h4>
              <div className="space-y-1 max-h-24 overflow-y-auto">
                {debateContext.top_alerts.slice(0, 3).map((alert, index) => (
                  <div key={index} className="text-xs bg-slate-800 rounded p-2">
                    <div className="flex items-center gap-1 mb-1">
                      <span className={`w-2 h-2 rounded-full ${
                        alert.severity === 'critical' ? 'bg-red-400' : 'bg-yellow-400'
                      }`}></span>
                      <span className="font-mono text-gray-300">{alert.agent_id}</span>
                      <span className="ml-auto text-gray-500">
                        {new Date(alert.triggered_at).toLocaleTimeString()}
                      </span>
                    </div>
                    <div className="text-gray-400 line-clamp-2">{alert.message}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
          
          {/* Top Teams */}
          {debateContext.top_teams.length > 0 && (
            <div className="mb-3">
              <h4 className="text-xs font-semibold text-gray-300 mb-2">Top Performing Teams</h4>
              <div className="space-y-1">
                {debateContext.top_teams.slice(0, 2).map((team, index) => (
                  <div key={index} className="flex items-center justify-between text-xs bg-slate-800 rounded p-2">
                    <span className="text-gray-300">{team.team_label}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-emerald-400 font-medium">
                        +{(team.contribution_pct * 100).toFixed(1)}%
                      </span>
                      {team.sharpe_delta !== 0 && (
                        <span className={`text-xs ${
                          team.sharpe_delta > 0 ? 'text-green-400' : 'text-red-400'
                        }`}>
                          {team.sharpe_delta > 0 ? '+' : ''}{team.sharpe_delta.toFixed(2)}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          
          {/* Footer */}
          <div className="pt-2 border-t border-slate-700 text-xs text-gray-500 flex items-center justify-between">
            <span>Last updated</span>
            <span>{new Date(debateContext.last_updated).toLocaleTimeString()}</span>
          </div>
        </div>
      )}
    </div>
  );
}
