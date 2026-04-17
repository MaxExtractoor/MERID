import React from 'react';

const StubBanner: React.FC<{ message?: string }> = ({ message = 'Stub mode active' }) => (
  <div className="stub-banner bg-yellow-900 text-yellow-100 px-4 py-2 text-sm">{message}</div>
);

const MemoizedStubBanner = React.memo(StubBanner);
MemoizedStubBanner.displayName = 'StubBanner';
export default MemoizedStubBanner;
