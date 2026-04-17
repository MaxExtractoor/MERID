import React from 'react';

function AgentReasoningPanel() {
  return (
    <div className="p-4">
      <h2 className="font-semibold mb-2">Agent Reasoning</h2>
      <button type="button" title="Refresh reasoning trace" className="px-3 py-1 bg-slate-700 text-white rounded text-sm">
        Refresh
      </button>
    </div>
  );
}

AgentReasoningPanel.displayName = 'AgentReasoningPanel';
export default React.memo(AgentReasoningPanel);
