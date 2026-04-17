import React from 'react';

const GovernanceDashboard: React.FC = () => (
  <div className="governance-dashboard" />
);

const MemoizedGovernanceDashboard = React.memo(GovernanceDashboard);
MemoizedGovernanceDashboard.displayName = 'GovernanceDashboard';
export default MemoizedGovernanceDashboard;
