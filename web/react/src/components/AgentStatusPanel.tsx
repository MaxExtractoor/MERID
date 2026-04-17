import React from 'react';

const AgentStatusPanel: React.FC = () => (
  <div
    className="p-4 agent-status-panel"
    role="button"
    tabIndex={0}
    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') e.currentTarget.click(); }}
  >
    <h2 className="font-semibold mb-2">Agent Status</h2>
    <button type="button" title="Refresh agent status" className="px-3 py-1 bg-slate-700 text-white rounded text-sm">
      Refresh
    </button>
  </div>
);

export default AgentStatusPanel;
