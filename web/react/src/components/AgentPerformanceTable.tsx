import React from 'react';

function AgentPerformanceTable() {
  return (
    <div className="p-4">
      <h2 className="font-semibold mb-2">Agent Performance</h2>
      <button type="button" title="Export performance data" className="px-3 py-1 bg-slate-700 text-white rounded text-sm">
        Export
      </button>
    </div>
  );
}

AgentPerformanceTable.displayName = 'AgentPerformanceTable';
export default React.memo(AgentPerformanceTable);
