/* eslint-disable react-refresh/only-export-components */
import React from 'react';

interface DataGuardProps {
  /** The API response object — checks for _stub flag */
  data: unknown;
  /** Label shown when data is a stub */
  label?: string;
  /** Whether to still render children behind the overlay (greyed out) */
  showSkeleton?: boolean;
  children: React.ReactNode;
}

/**
 * DataGuard wraps a view section and checks if the API response
 * is a stub (has _stub === true). If so, it renders a clear
 * "OFFLINE / No Live Data" overlay instead of fake numbers.
 *
 * Usage:
 *   <DataGuard data={apiResponse} label="Treasury">
 *     <TreasuryChart data={apiResponse} />
 *   </DataGuard>
 */
export function DataGuard({ data, label, showSkeleton = true, children }: DataGuardProps) {
  const stubData = typeof data === 'object' && data !== null
    ? (data as { _stub?: boolean; _stub_message?: string; _implementation_status?: string })
    : ({} as { _stub?: boolean; _stub_message?: string; _implementation_status?: string });
  const isStub = stubData._stub === true;
  const stubMessage = stubData._stub_message || 'No live data available';

  if (!isStub) {
    return <>{children}</>;
  }

  return (
    <div className="relative">
      {showSkeleton && (
        <div className="opacity-10 pointer-events-none select-none filter grayscale">
          {children}
        </div>
      )}
      <div className={`${showSkeleton ? 'absolute inset-0' : ''} flex items-center justify-center`}>
        <div className="bg-zinc-900/95 border border-yellow-600/40 rounded-lg px-6 py-4 text-center max-w-md">
          <div className="flex items-center justify-center gap-2 mb-2">
            <div className="w-2 h-2 rounded-full bg-yellow-500 animate-pulse" />
            <span className="text-yellow-500 font-semibold text-sm uppercase tracking-wide">
              {label ? `${label} — Offline` : 'Offline'}
            </span>
          </div>
          <p className="text-zinc-400 text-xs">{stubMessage}</p>
          <p className="text-zinc-600 text-[10px] mt-1">
            This section uses stub data. Connect live feeds to see real metrics.
          </p>
        </div>
      </div>
    </div>
  );
}

/**
 * Inline stub badge — for use in table cells, card headers, etc.
 * Shows a small "STUB" pill when data is from a stub endpoint.
 */
export function StubBadge({ data, className = '' }: { data: unknown; className?: string }) {
  const stubData = typeof data === 'object' && data !== null
    ? (data as { _stub?: boolean })
    : ({} as { _stub?: boolean });
  if (!stubData._stub) return null;
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-yellow-900/40 text-yellow-500 border border-yellow-700/30 ${className}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-yellow-500" />
      STUB
    </span>
  );
}

/**
 * Hook to check if any API response contains stub data.
 * Returns { isStub, message, dataMode }
 */
export function useDataMode(data: unknown) {
  const stubData = typeof data === 'object' && data !== null
    ? (data as { _stub?: boolean; _stub_message?: string; _implementation_status?: string })
    : ({} as { _stub?: boolean; _stub_message?: string; _implementation_status?: string });
  return {
    isStub: stubData._stub === true,
    message: stubData._stub_message || '',
    dataMode: stubData._stub ? 'offline' as const : 'live' as const,
    implementationStatus: stubData._implementation_status || 'LIVE',
  };
}

export default DataGuard;
