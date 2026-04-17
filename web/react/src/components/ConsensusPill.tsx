import React from 'react';

const ConsensusPill: React.FC<{ label?: string }> = ({ label = '' }) => (
  <span className="consensus-pill">{label}</span>
);

const MemoizedConsensusPill = React.memo(ConsensusPill);
MemoizedConsensusPill.displayName = 'ConsensusPill';
export default MemoizedConsensusPill;
