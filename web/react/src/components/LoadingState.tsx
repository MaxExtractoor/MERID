import React from 'react';

const LoadingState: React.FC<{ message?: string }> = ({ message = 'Loading...' }) => (
  <div className="loading-state">{message}</div>
);

const MemoizedLoadingState = React.memo(LoadingState);
MemoizedLoadingState.displayName = 'LoadingState';
export default MemoizedLoadingState;
