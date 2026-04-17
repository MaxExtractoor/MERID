import React from 'react';

const SwarmPanel: React.FC = () => (
  <div
    className="p-4 swarm-panel"
    role="button"
    tabIndex={0}
    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') e.currentTarget.click(); }}
  >
    <h2 className="font-semibold mb-2">Swarm</h2>
    <button type="button" title="Refresh swarm status" className="px-3 py-1 bg-slate-700 text-white rounded text-sm">
      Refresh
    </button>
  </div>
);

export default SwarmPanel;
