import React from 'react';
import { AlertTriangle, X, Zap, Shield, RotateCcw } from '../ui/icons';
import { WsRiskAlert, RiskAlertType } from '../hooks/useKalshiRiskStream';

interface RiskAlertFeedProps {
  alerts: WsRiskAlert[];
  maxVisible?: number;
  onDismiss?: (alertId: string) => void;
}

const ALERT_ICONS: Record<RiskAlertType, React.ComponentType<{ className?: string }>> = {
  kill_switch: Shield,
  portfolio_breach: AlertTriangle,
  agent_rollback: RotateCcw,
  general: AlertTriangle,
};

const ALERT_COLORS: Record<'info' | 'warning' | 'error' | 'critical', string> = {
  info: 'text-blue-400 bg-blue-400/10 border-blue-400/20',
  warning: 'text-yellow-400 bg-yellow-400/10 border-yellow-400/20',
  error: 'text-red-400 bg-red-400/10 border-red-400/20',
  critical: 'text-red-500 bg-red-500/10 border-red-500/20',
};

export const RiskAlertFeed: React.FC<RiskAlertFeedProps> = ({
  alerts,
  maxVisible = 5,
  onDismiss,
}) => {
  const visibleAlerts = alerts.slice(0, maxVisible);

  if (visibleAlerts.length === 0) {
    return (
      <div className="text-center py-4 text-gray-500 text-sm">
        <Zap className="w-4 h-4 mx-auto mb-1 opacity-50" />
        No recent risk alerts
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {visibleAlerts.map((alert) => {
        const Icon = ALERT_ICONS[alert.type];
        const colorClass = ALERT_COLORS[alert.level];

        return (
          <div
            key={alert.id}
            className={`flex items-start gap-3 p-3 rounded-lg border ${colorClass} text-sm`}
          >
            <Icon className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="font-medium text-white">
                {alert.type === 'kill_switch' && '🚫 Kill Switch Activated'}
                {alert.type === 'portfolio_breach' && '⚠️ Portfolio Breach'}
                {alert.type === 'agent_rollback' && '🔄 Agent Rollback'}
                {alert.type === 'general' && '⚠️ Risk Alert'}
              </div>
              <div className="text-gray-300 mt-1">{alert.message}</div>
              {alert.source_agent_id && (
                <div className="text-xs text-gray-500 mt-1">
                  Agent: {alert.source_agent_id}
                </div>
              )}
              {alert.market_id && (
                <div className="text-xs text-gray-500">
                  Market: {alert.market_id}
                </div>
              )}
              <div className="text-xs text-gray-500 mt-1">
                {new Date(alert.ts).toLocaleTimeString([], {
                  hour: '2-digit',
                  minute: '2-digit',
                  second: '2-digit'
                })}
              </div>
            </div>
            {onDismiss && (
              <button
                type="button"
                onClick={() => onDismiss(alert.id)}
                className="flex-shrink-0 p-1 rounded hover:bg-white/10 transition-colors"
                title="Dismiss alert"
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </div>
        );
      })}
      {alerts.length > maxVisible && (
        <div className="text-center text-xs text-gray-500 py-2">
          +{alerts.length - maxVisible} more alerts
        </div>
      )}
    </div>
  );
};

export default RiskAlertFeed;
