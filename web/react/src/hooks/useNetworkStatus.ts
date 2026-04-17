import { useState, useEffect, useCallback } from 'react';

export interface NetworkStatus {
  isOnline: boolean;
  wasOffline: boolean;
  lastOnline: Date | null;
  lastOffline: Date | null;
}

export function useNetworkStatus(): NetworkStatus {
  const [status, setStatus] = useState<NetworkStatus>({
    isOnline: navigator.onLine,
    wasOffline: false,
    lastOnline: navigator.onLine ? new Date() : null,
    lastOffline: navigator.onLine ? null : new Date(),
  });

  const handleOnline = useCallback(() => {
    setStatus(prev => ({
      isOnline: true,
      wasOffline: !prev.isOnline,
      lastOnline: new Date(),
      lastOffline: prev.lastOffline,
    }));
  }, []);

  const handleOffline = useCallback(() => {
    setStatus(prev => ({
      isOnline: false,
      wasOffline: prev.isOnline,
      lastOnline: prev.lastOnline,
      lastOffline: new Date(),
    }));
  }, []);

  useEffect(() => {
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, [handleOnline, handleOffline]);

  return status;
}

