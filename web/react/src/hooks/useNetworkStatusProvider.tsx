/**
 * Global Network Status Provider for Kalshi UI components.
 * 
 * Provides centralized network monitoring, status broadcasting,
 * and connection quality assessment across all components.
 */

import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';

interface NetworkStatus {
  isOnline: boolean;
  networkSpeed: 'fast' | 'slow' | 'unknown';
  lastConnected: number;
  connectionType: string;
  effectiveType: string;
  downlink: number;
  rtt: number;
  saveData: boolean;
}

interface NetworkContextValue {
  status: NetworkStatus;
  isOnline: boolean;
  networkSpeed: 'fast' | 'slow' | 'unknown';
  isSlow: boolean;
  isOffline: boolean;
  timeSinceLastConnection: number;
  getConnectionQuality: () => 'excellent' | 'good' | 'poor' | 'unknown';
  subscribe: (callback: (status: NetworkStatus) => void) => () => void;
  forceRecheck: () => void;
}

const NetworkContext = createContext<NetworkContextValue | null>(null);

// Network connection detection utilities
const detectConnectionType = (): string => {
  const connection = (navigator as any).connection;
  if (!connection) return 'unknown';
  
  return connection.type || connection.effectiveType || 'unknown';
};

const detectEffectiveType = (): string => {
  const connection = (navigator as any).connection;
  if (!connection) return 'unknown';
  
  return connection.effectiveType || 'unknown';
};

const assessNetworkSpeed = (effectiveType: string, rtt?: number): 'fast' | 'slow' | 'unknown' => {
  if (effectiveType === 'slow-2g' || effectiveType === '2g') {
    return 'slow';
  } else if (effectiveType === '4g') {
    return 'fast';
  } else if (effectiveType === '3g') {
    return rtt && rtt < 300 ? 'fast' : 'slow';
  }
  
  return 'unknown';
};

// Network monitoring hook
export const useNetworkProvider = (): NetworkContextValue => {
  const [status, setStatus] = useState<NetworkStatus>({
    isOnline: navigator.onLine,
    networkSpeed: 'unknown',
    lastConnected: Date.now(),
    connectionType: 'unknown',
    effectiveType: 'unknown',
    downlink: 0,
    rtt: 0,
    saveData: false,
  });

  const [subscribers, setSubscribers] = useState<Set<(status: NetworkStatus) => void>>(new Set());

  // Update network status
  const updateStatus = useCallback(() => {
    const connection = (navigator as any).connection;
    const effectiveType = detectEffectiveType();
    const networkSpeed = assessNetworkSpeed(effectiveType, connection?.rtt);
    
    const newStatus: NetworkStatus = {
      isOnline: navigator.onLine,
      networkSpeed,
      lastConnected: navigator.onLine ? Date.now() : status.lastConnected,
      connectionType: detectConnectionType(),
      effectiveType,
      downlink: connection?.downlink || 0,
      rtt: connection?.rtt || 0,
      saveData: connection?.saveData || false,
    };

    setStatus(newStatus);
    
    // Notify subscribers
    subscribers.forEach(callback => {
      try {
        callback(newStatus);
      } catch (error) {
        console.error('Network status subscriber error:', error);
      }
    });
  }, [status.lastConnected, subscribers]);

  // Handle online/offline events
  useEffect(() => {
    const handleOnline = () => updateStatus();
    const handleOffline = () => updateStatus();
    const handleConnectionChange = () => updateStatus();

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    
    // Listen for connection changes
    const connection = (navigator as any).connection;
    if (connection) {
      connection.addEventListener('change', handleConnectionChange);
    }

    // Initial status check
    updateStatus();

    // Periodic status recheck (every 30 seconds)
    const recheckInterval = setInterval(updateStatus, 30000);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
      
      if (connection) {
        connection.removeEventListener('change', handleConnectionChange);
      }
      
      clearInterval(recheckInterval);
    };
  }, [updateStatus]);

  // Subscribe to status changes
  const subscribe = useCallback((callback: (status: NetworkStatus) => void) => {
    setSubscribers(prev => new Set(prev).add(callback));
    
    // Return unsubscribe function
    return () => {
      setSubscribers(prev => {
        const newSet = new Set(prev);
        newSet.delete(callback);
        return newSet;
      });
    };
  }, []);

  // Force recheck
  const forceRecheck = useCallback(() => {
    updateStatus();
  }, [updateStatus]);

  // Derived values
  const isSlow = status.networkSpeed === 'slow';
  const isOffline = !status.isOnline;
  const timeSinceLastConnection = Date.now() - status.lastConnected;

  // Get connection quality
  const getConnectionQuality = useCallback((): 'excellent' | 'good' | 'poor' | 'unknown' => {
    if (!status.isOnline) return 'unknown';
    
    if (status.networkSpeed === 'fast' && status.rtt < 200) {
      return 'excellent';
    } else if (status.networkSpeed === 'fast' || status.rtt < 500) {
      return 'good';
    } else if (status.networkSpeed === 'slow' || status.rtt > 1000) {
      return 'poor';
    }
    
    return 'unknown';
  }, [status]);

  return {
    status,
    isOnline: status.isOnline,
    networkSpeed: status.networkSpeed,
    isSlow,
    isOffline,
    timeSinceLastConnection,
    getConnectionQuality,
    subscribe,
    forceRecheck,
  };
};

// Context provider component
export const NetworkProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const networkValue = useNetworkProvider();
  
  return (
    <NetworkContext.Provider value={networkValue}>
      {children}
    </NetworkContext.Provider>
  );
};

// Hook for consuming network context
export const useNetworkStatus = (): NetworkContextValue => {
  const context = useContext(NetworkContext);
  
  if (!context) {
    throw new Error('useNetworkStatus must be used within a NetworkProvider');
  }
  
  return context;
};

// Higher-order component for network-aware components
export const withNetworkStatus = <P extends object>(
  Component: React.ComponentType<P>
): React.FC<P & { networkStatus: NetworkContextValue }> => {
  return (props) => {
    const networkStatus = useNetworkStatus();
    return <Component {...props} networkStatus={networkStatus} />;
  };
};
