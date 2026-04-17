import React from 'react';

const OrchestratorPanel: React.FC = () => (
  <div
    className="p-4 orchestrator-panel"
    role="button"
    tabIndex={0}
    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') e.currentTarget.click(); }}
  >
    <h2 className="font-semibold mb-2">Orchestrator</h2>
    <button type="button" title="Refresh orchestrator status" className="px-3 py-1 bg-slate-700 text-white rounded text-sm">
      Refresh
    </button>
  </div>
);

export default OrchestratorPanel;
