import React from 'react';

const DevSwarmTaskList: React.FC = () => (
  <div className="p-4" role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.click(); }}>
    <h2 className="font-semibold mb-2">Swarm Task List</h2>
    <button type="button" title="Refresh task list" className="px-3 py-1 bg-slate-700 text-white rounded text-sm">
      Refresh
    </button>
  </div>
);

export default DevSwarmTaskList;
