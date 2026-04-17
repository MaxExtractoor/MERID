import { useEffect, useState, useCallback } from 'react';
import { Bell, X, CheckCircle, AlertCircle, Info, TrendingUp } from 'lucide-react';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS, AUTH_TOKEN_KEY } from '../config/constants';
import type { RawNotification } from '../types/api';

function authHeaders(headers?: HeadersInit): HeadersInit {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
    ...(headers ?? {}),
  };
}

interface LiveNotification {
  id: string;
  type: 'success' | 'warning' | 'info' | 'trade';
  title: string;
  message: string;
  timestamp: number;
  read: boolean;
}

export default function LiveNotifications() {
  const [notifications, setNotifications] = useState<LiveNotification[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [isConnected, setIsConnected] = useState(false);

  const normalizeNotification = useCallback((note: RawNotification): LiveNotification => {
    const baseType = note.type ?? 'info';
    const severity = note.severity ?? 'info';
    const type = baseType === 'trade'
      ? 'trade'
      : (baseType === 'success'
        ? 'success'
        : (severity === 'warning' || severity === 'error' || severity === 'critical')
          ? 'warning'
          : 'info');
    const timestampRaw = note.timestamp ?? new Date().toISOString();
    const timestamp = Number.isNaN(Date.parse(timestampRaw)) ? Date.now() : Date.parse(timestampRaw);

    return {
      id: note.id ?? `temp-${timestamp}`,
      type,
      title: note.title ?? 'Notification',
      message: note.message ?? '',
      timestamp,
      read: Boolean(note.read),
    };
  }, []);

  const fetchNotifications = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.NOTIFICATIONS}`, {
        headers: authHeaders(),
      });
      if (!response.ok) {
        setIsConnected(false);
        return;
      }
      const data = await response.json();
      const normalized = Array.isArray(data.notifications)
        ? data.notifications.map((note: RawNotification) => normalizeNotification(note))
        : [];
      setNotifications(normalized);
      setIsConnected(true);
    } catch {
      setIsConnected(false);
    }
  }, [normalizeNotification]);

  useEffect(() => {
    fetchNotifications();
    const interval = setInterval(fetchNotifications, DEFAULTS.POLLING_INTERVALS.BACKGROUND);
    return () => clearInterval(interval);
  }, [fetchNotifications]);

  useEffect(() => {
    const count = notifications.filter(n => !n.read).length;
    setUnreadCount(count);
  }, [notifications]);

  const markAsRead = async (id: string) => {
    setNotifications(prev =>
      prev.map(n => n.id === id ? { ...n, read: true } : n)
    );
    try {
      await fetch(`${API_BASE_URL}${API_ENDPOINTS.NOTIFICATION_READ(id)}`, {
        method: 'POST',
        headers: authHeaders(),
      });
    } catch {
      // keep optimistic state
    }
  };

  const markAllAsRead = async () => {
    setNotifications(prev => prev.map(n => ({ ...n, read: true })));
    try {
      await fetch(`${API_BASE_URL}${API_ENDPOINTS.NOTIFICATIONS_READ_ALL}`, {
        method: 'POST',
        headers: authHeaders(),
      });
    } catch {
      // keep optimistic state
    }
  };

  const removeNotification = (id: string) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
  };

  const getIcon = (type: string) => {
    switch (type) {
      case 'success': return <CheckCircle className="w-5 h-5 text-green-400" />;
      case 'warning': return <AlertCircle className="w-5 h-5 text-yellow-400" />;
      case 'trade': return <TrendingUp className="w-5 h-5 text-blue-400" />;
      default: return <Info className="w-5 h-5 text-gray-400" />;
    }
  };

  const getTimeAgo = (timestamp: number) => {
    const seconds = Math.floor((Date.now() - timestamp) / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  };

  return (
    <div className="relative">
      <button type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="relative p-2 hover:bg-slate-700 rounded-lg transition-colors"
        title="Notifications"
      >
        <Bell className="w-5 h-5 text-gray-400" />
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-5 h-5 flex items-center justify-center">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
        {isConnected && (
          <span className="absolute bottom-0 right-0 w-2 h-2 bg-green-500 rounded-full animate-pulse" />
        )}
      </button>

      {isOpen && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setIsOpen(false)}
            role="button" tabIndex={0} aria-label="Close" onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setIsOpen(false); } }}
          />
          <div className="absolute right-0 mt-2 w-96 bg-slate-800 rounded-lg border border-slate-700 shadow-xl z-50 max-h-[600px] flex flex-col">
            <div className="p-4 border-b border-slate-700 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <h3 className="text-lg font-bold text-white">Notifications</h3>
                <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500 animate-pulse' : 'bg-gray-500'}`} />
              </div>
              {unreadCount > 0 && (
                <button type="button"
                  onClick={markAllAsRead}
                  className="text-xs text-blue-400 hover:text-blue-300"
                 title="Mark all read">
                  Mark all read
                </button>
              )}
            </div>

            <div className="overflow-y-auto flex-1">
              {notifications.length === 0 ? (
                <div className="p-8 text-center text-gray-400">
                  <Bell className="w-12 h-12 mx-auto mb-2 opacity-50" />
                  <p>No notifications yet</p>
                  <p className="text-xs mt-1">
                    {isConnected ? 'Listening for updates...' : 'Connecting...'}
                  </p>
                </div>
              ) : (
                <div className="divide-y divide-slate-700">
                  {notifications.map(notification => (
                    <div
                      key={notification.id}
                      className={`p-4 hover:bg-slate-700/50 transition-colors flex items-start gap-3 ${
                        !notification.read ? 'bg-slate-700/30' : ''
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => markAsRead(notification.id)}
                        className="flex items-start gap-3 flex-1 min-w-0 text-left"
                        title="Mark as read"
                      >
                        <div className="flex-shrink-0 mt-1">
                          {getIcon(notification.type)}
                        </div>
                        <div className="flex-1 min-w-0">
                          <h4 className="text-sm font-medium text-white">
                            {notification.title}
                          </h4>
                          <p className="text-sm text-gray-400 mt-1">
                            {notification.message}
                          </p>
                          <p className="text-xs text-gray-500 mt-2">
                            {getTimeAgo(notification.timestamp)}
                          </p>
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={() => removeNotification(notification.id)}
                        className="text-gray-400 hover:text-white"
                        title="Remove notification"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
