import React from 'react';

function DomainControlPanel() {
  return (
    <div className="p-4">
      <h2 className="font-semibold mb-2">Domain Control</h2>
      <button type="button" title="Refresh domain status" className="px-3 py-1 bg-slate-700 text-white rounded text-sm">
        Refresh
      </button>
    </div>
  );
}

DomainControlPanel.displayName = 'DomainControlPanel';
export default React.memo(DomainControlPanel);
