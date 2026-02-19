/**
 * StubGate — safety gate that disables interactive controls when the
 * backend is serving stub data.
 *
 * Usage:
 *   <StubGate data={apiResponse}>
 *     <button type="button" onClick={placeOrder} title="BUY">BUY</button>
 *   </StubGate>
 *
 * When `isStub(data)` is true:
 *  - Children are rendered with pointer-events disabled and reduced opacity.
 *  - A small "Simulation Only" overlay appears.
 *  - An optional `onBlocked` callback fires if a user tries to click.
 *
 * When `isStub(data)` is false the children render normally with zero overhead.
 */

import React from 'react';
import { isStub, stubMessage } from '../utils/stub';
import { AlertTriangle } from 'lucide-react';

interface StubGateProps {
  /** Raw API response (or any object that may contain `_stub`). */
  data: unknown;
  /** Rendered inside the gate. */
  children: React.ReactNode;
  /** Optional callback when a blocked click is attempted. */
  onBlocked?: () => void;
  /** Override the default overlay label. */
  label?: string;
  /** If true, hide children entirely instead of greying them out. */
  hide?: boolean;
}

function StubGate({ data, children, onBlocked, label, hide }: StubGateProps) {
  if (!isStub(data)) {
    return <>{children}</>;
  }

  if (hide) {
    return null;
  }

  const msg = label || stubMessage(data);

  return (
    <div
      className="relative"
      onClick={(e) => {
        e.stopPropagation();
        e.preventDefault();
        onBlocked?.();
      }}
      role="presentation"
    >
      {/* Disabled children */}
      <div className="pointer-events-none opacity-40 select-none" aria-disabled="true">
        {children}
      </div>

      {/* Overlay badge */}
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="flex items-center gap-2 px-3 py-1.5 bg-amber-500/20 border border-amber-500/40 rounded-lg backdrop-blur-sm">
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
          <span className="text-amber-300 text-xs font-medium">{msg}</span>
        </div>
      </div>
    </div>
  );
}

const MemoizedStubGate = React.memo(StubGate);
MemoizedStubGate.displayName = 'StubGate';
export default MemoizedStubGate;
