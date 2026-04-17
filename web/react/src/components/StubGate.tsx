import React from 'react';

interface StubGateProps {
  children?: React.ReactNode;
  enabled?: boolean;
}

const StubGate: React.FC<StubGateProps> = ({ children, enabled = true }) => {
  if (!enabled) return null;
  return (
    <div className="stub-gate">
      <button type="button" title="Toggle stub" className="stub-gate-toggle text-xs text-yellow-400">
        STUB
      </button>
      {children}
    </div>
  );
};

const MemoizedStubGate = React.memo(StubGate);
MemoizedStubGate.displayName = 'StubGate';
export default MemoizedStubGate;
