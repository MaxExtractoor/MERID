import { WifiOff, CloudOff, AlertTriangle } from '../ui/icons';
import { useNetworkStatus } from '../hooks/useNetworkStatus';
import './OfflineIndicator.css';

export function OfflineIndicator() {
  const { isOnline, wasOffline, lastOnline } = useNetworkStatus();

  if (isOnline) {
    // Show reconnection notice briefly
    if (wasOffline && lastOnline) {
      return (
        <div className="offline-indicator offline-indicator--reconnected">
          <WifiOff size={16} />
          <span>Connection restored</span>
        </div>
      );
    }
    return null;
  }

  return (
    <div className="offline-indicator offline-indicator--offline" role="alert" aria-live="assertive">
      <WifiOff size={18} />
      <div className="offline-indicator__content">
        <span className="offline-indicator__title">You are offline</span>
        <span className="offline-indicator__subtitle">Check your connection to resume trading</span>
      </div>
    </div>
  );
}

export function ConnectionStatusBadge({ isConnected }: { isConnected: boolean }) {
  return (
    <span
      className={`connection-badge ${isConnected ? 'connection-badge--online' : 'connection-badge--offline'}`}
      aria-label={isConnected ? 'Connection online' : 'Connection offline'}
    >
      {isConnected ? (
        <>
          <span className="connection-badge__dot connection-badge__dot--online" />
          <span>Online</span>
        </>
      ) : (
        <>
          <CloudOff size={12} />
          <span>Offline</span>
        </>
      )}
    </span>
  );
}

export function ApiHealthIndicator({ status }: { status: 'healthy' | 'degraded' | 'unavailable' }) {
  const config = {
    healthy: { icon: null, color: 'text-green-400', bg: 'bg-green-500/10', label: 'API Healthy' },
    degraded: { icon: AlertTriangle, color: 'text-yellow-400', bg: 'bg-yellow-500/10', label: 'API Degraded' },
    unavailable: { icon: CloudOff, color: 'text-red-400', bg: 'bg-red-500/10', label: 'API Unavailable' },
  };

  const { icon: Icon, color, bg, label } = config[status];

  return (
    <span className={`api-health-badge ${color} ${bg}`}>
      {Icon && <Icon size={12} />}
      <span>{label}</span>
    </span>
  );
}
