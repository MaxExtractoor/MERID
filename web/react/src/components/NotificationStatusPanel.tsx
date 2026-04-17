/**
 * NotificationStatusPanel - Shows recent Telegram/X notifications and channel status
 */

import { useState } from 'react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS } from '../config/constants';
import { Bell, BellOff, AlertTriangle, CheckCircle, Clock } from 'lucide-react';

interface NotificationStatus {
  channel: string;
  enabled: boolean;
  configured: boolean;
  last_sent: string | null;
  rate_limit_status: {
    messages_per_hour: number;
    current_count: number;
    reset_time: string;
  } | {
    tweets_per_day: number;
    current_count: number;
    reset_date: string;
  };
}

interface NotificationStatusResponse {
  worker_running: boolean;
  last_poll: string | null;
  last_daily_summary: string | null;
  channels: NotificationStatus[];
}

interface RecentAlert {
  agent_id: string;
  severity: string;
  message: string;
  triggered_at: string;
  channel: string;
}

interface RecentAlertsResponse {
  alerts: RecentAlert[];
  total: number;
  hours: number;
  timestamp: string;
}

function fmtRelativeTime(dateStr: string | null): string {
  if (!dateStr) return 'Never';
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  
  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
  return `${Math.floor(diffMins / 1440)}d ago`;
}

export default function NotificationStatusPanel() {
  const [showAlerts, setShowAlerts] = useState(false);
  
  const { data: statusData, loading: statusLoading, error: statusError } = useApiData<NotificationStatusResponse>(
    API_ENDPOINTS.NOTIFICATION_STATUS,
    { pollingInterval: 30000 } // Poll every 30 seconds
  );
  
  const { data: recentAlertsData, loading: alertsLoading } = useApiData<RecentAlertsResponse>(
    API_ENDPOINTS.NOTIFICATION_RECENT_ALERTS + '?hours=2',
    { pollingInterval: 60000 } // Poll every minute
  );

  const getStatusIcon = (channel: NotificationStatus) => {
    if (!channel.configured) return <BellOff className="w-4 h-4 text-slate-500" />;
    if (!channel.enabled) return <BellOff className="w-4 h-4 text-slate-400" />;
    return <Bell className="w-4 h-4 text-green-500" />;
  };

  const getChannelName = (channel: string) => {
    return channel === 'telegram' ? 'Telegram' : 'X/Twitter';
  };

  const getRateLimitText = (channel: NotificationStatus) => {
    const status = channel.rate_limit_status;
    if ('messages_per_hour' in status) {
      return `${status.current_count}/${status.messages_per_hour} msgs/hr`;
    } else {
      return `${status.current_count}/${status.tweets_per_day} tweets/day`;
    }
  };

  const getSeverityIcon = (severity: string) => {
    return severity === 'critical' 
      ? <AlertTriangle className="w-3 h-3 text-red-500" />
      : <AlertTriangle className="w-3 h-3 text-yellow-500" />;
  };

  if (statusError) {
    return (
      <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
        <div className="flex items-center gap-2 text-slate-400">
          <BellOff className="w-4 h-4" />
          <span className="text-sm">Notification system unavailable</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Bell className="w-5 h-5 text-slate-300" />
          <h3 className="text-sm font-semibold text-slate-200">Notifications</h3>
        </div>
        
        <div className="flex items-center gap-2">
          {/* Worker Status */}
          <div className="flex items-center gap-1">
            {statusData?.worker_running ? (
              <CheckCircle className="w-4 h-4 text-green-500" />
            ) : (
              <Clock className="w-4 h-4 text-yellow-500" />
            )}
            <span className="text-xs text-slate-400">
              {statusData?.worker_running ? 'Active' : 'Inactive'}
            </span>
          </div>
          
          {/* Recent Alerts Toggle */}
          <button
            onClick={() => setShowAlerts(!showAlerts)}
            className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
          >
            {showAlerts ? 'Hide' : 'Show'} Recent
          </button>
        </div>
      </div>

      {/* Channel Status */}
      {statusLoading ? (
        <div className="space-y-2">
          {[...Array(2)].map((_, i) => (
            <div key={i} className="bg-slate-700/50 rounded h-8 animate-pulse" />
          ))}
        </div>
      ) : statusData?.channels ? (
        <div className="space-y-2">
          {statusData.channels.map((channel) => (
            <div key={channel.channel} className="flex items-center justify-between text-xs">
              <div className="flex items-center gap-2">
                {getStatusIcon(channel)}
                <span className="text-slate-300">{getChannelName(channel.channel)}</span>
              </div>
              
              <div className="flex items-center gap-3 text-slate-400">
                <span>{getRateLimitText(channel)}</span>
                <span>{fmtRelativeTime(channel.last_sent)}</span>
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {/* Recent Alerts */}
      {showAlerts && (
        <div className="mt-4 pt-4 border-t border-slate-700">
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-xs font-semibold text-slate-300">Recent Alerts (2h)</h4>
            {recentAlertsData && (
              <span className="text-xs text-slate-400">
                {recentAlertsData.total} total
              </span>
            )}
          </div>
          
          {alertsLoading ? (
            <div className="space-y-1">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="bg-slate-700/30 rounded h-6 animate-pulse" />
              ))}
            </div>
          ) : recentAlertsData?.alerts && recentAlertsData.alerts.length > 0 ? (
            <div className="space-y-1 max-h-32 overflow-y-auto">
              {recentAlertsData.alerts.slice(0, 10).map((alert, index) => (
                <div key={index} className="flex items-center gap-2 text-xs text-slate-300 py-1">
                  {getSeverityIcon(alert.severity)}
                  <span className="font-mono truncate flex-1">{alert.agent_id}</span>
                  <span className="truncate flex-2">{alert.message}</span>
                  <span className="text-slate-500">{fmtRelativeTime(alert.triggered_at)}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-xs text-slate-500 text-center py-2">
              No recent alerts
            </div>
          )}
        </div>
      )}
    </div>
  );
}
