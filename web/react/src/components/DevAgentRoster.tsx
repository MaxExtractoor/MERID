import React from 'react';

const DevAgentRoster: React.FC = () => (
  <div className="dev-agent-roster" />
);

const MemoizedDevAgentRoster = React.memo(DevAgentRoster);
MemoizedDevAgentRoster.displayName = 'DevAgentRoster';
export default MemoizedDevAgentRoster;
