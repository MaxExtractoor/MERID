/**
 * BackendStatusIndicator — Shows backend connectivity state and gates UI when offline.
 * 
 * Usage: Place in App.tsx or layout to show global backend status.
 * When backend is offline, shows a banner and prevents API spam.
 */

import React, { useEffect, useState } from 'react';
import { WifiOff, AlertTriangle, RefreshCw } from 'lucide-react';
import { checkBackendHealth, resetHealthState } from '../utils/resilientFetch';

interface BackendStatusIndicatorProps {
  /** Optional: called when health status changes */
  onHealthChange?: (healthy: boolean) => void;
  /** Position: 'top' | 'bottom' */
  position?: 'top' | 'bottom';
}

export const BackendStatusIndicator: React.FC<BackendStatusIndicatorProps> = ({
  onHealthChange,
  position = 'top',
}) => {
  const [healthy, setHealthy] = useState<boolean>(true);
  const [checking, setChecking] = useState<boolean>(false);
  const [lastCheck, setLastCheck] = useState<Date | null>(null);

  // Check health periodically
  useEffect(() => {
    let mounted = true;
    
    const check = async () => {
      if (!mounted) return;
      const isHealthy = await checkBackendHealth();
      if (!mounted) return;
      
      setHealthy(isHealthy);
      setLastCheck(new Date());
      onHealthChange?.(isHealthy);
    };

    // Initial check
    check();

    // Periodic checks every 10s
    const interval = setInterval(check, 10000);

    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [onHealthChange]);

  const handleManualCheck = async () => {
    setChecking(true);
    resetHealthState();
    const isHealthy = await checkBackendHealth();
    setHealthy(isHealthy);
    setLastCheck(new Date());
    setChecking(false);
    onHealthChange?.(isHealthy);
  };

  // Don't show banner when healthy
  if (healthy) return null;

  const positionClasses = position === 'top' 
    ? 'top-0 border-b' 
    : 'bottom-0 border-t';

  return (
    <div 
      className={`fixed left-0 right-0 z-50 bg-red-900/90 border-red-700 text-white px-4 py-2 ${positionClasses}`}
      role="alert"
      aria-live="polite"
    >
      <div className="max-w-7xl mx-auto flex items-center justify-between">
        <div className="flex items-center gap-2">
          <WifiOff className="w-4 h-4 text-red-300" />
          <span className="font-medium text-sm">
            Backend Offline
          </span>
          <span className="text-red-200 text-xs hidden sm:inline">
            — API requests are paused until connection is restored
          </span>
        </div>
        
        <div className="flex items-center gap-3">
          {lastCheck && (
            <span className="text-xs text-red-200 hidden md:inline">
              Last check: {lastCheck.toLocaleTimeString()}
            </span>
          )}
          
          <button
            onClick={handleManualCheck}
            disabled={checking}
            className="flex items-center gap-1 px-3 py-1 bg-red-800 hover:bg-red-700 disabled:opacity-50 rounded text-xs font-medium transition-colors"
          >
            <RefreshCw className={`w-3 h-3 ${checking ? 'animate-spin' : ''}`} />
            {checking ? 'Checking...' : 'Retry'}
          </button>
        </div>
      </div>
    </div>
  );
};

/**
 * BackendGuard — Wraps children and shows fallback when backend is offline.
 */
interface BackendGuardProps {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

export const BackendGuard: React.FC<BackendGuardProps> = ({ 
  children, 
  fallback = <OfflineFallback />
}) => {
  const [healthy, setHealthy] = useState<boolean>(true);

  useEffect(() => {
    let mounted = true;
    
    const check = async () => {
      const isHealthy = await checkBackendHealth();
      if (mounted) setHealthy(isHealthy);
    };

    check();
    const interval = setInterval(check, 10000);

    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  if (!healthy) {
    return <>{fallback}</>;
  }

  return <>{children}</>;
};

/**
 * OfflineFallback — Full-page fallback when backend is completely unavailable.
 */
const OfflineFallback: React.FC = () => (
  <div className="min-h-screen bg-slate-950 flex items-center justify-center p-4">
    <div className="max-w-md w-full bg-slate-900/80 rounded-xl border border-slate-800 p-8 text-center space-y-4">
      <div className="w-16 h-16 bg-red-500/10 rounded-full flex items-center justify-center mx-auto">
        <WifiOff className="w-8 h-8 text-red-400" />
      </div>
      
      <h2 className="text-xl font-semibold text-white">
        Backend Unavailable
      </h2>
      
      <p className="text-slate-400 text-sm">
        The MERID backend at <code className="bg-slate-800 px-1 py-0.5 rounded">localhost:8011</code> is not responding. 
        Please ensure the server is running.
      </p>
      
      <div className="bg-slate-800/50 rounded-lg p-4 text-left text-xs text-slate-400 space-y-2">
        <p className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-400" />
          <span>Start the backend:</span>
        </p>
        <code className="block bg-slate-950 p-2 rounded font-mono">
          py web/main.py
        </code>
        <p>Or check that port 8011 is not blocked by another process.</p>
      </div>
      
      <button
        onClick={() => window.location.reload()}
        className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-white font-medium transition-colors"
      >
        <RefreshCw className="w-4 h-4" />
        Reload Page
      </button>
    </div>
  </div>
);

export default BackendStatusIndicator;
