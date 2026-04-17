import React from 'react';

const StatusIndicator: React.FC<{ status?: string }> = ({ status = 'unknown' }) => (
  <span className={`status-indicator status-${status}`}>{status}</span>
);

const MemoizedStatusIndicator = React.memo(StatusIndicator);
MemoizedStatusIndicator.displayName = 'StatusIndicator';
export default MemoizedStatusIndicator;
