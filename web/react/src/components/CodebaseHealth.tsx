import React from 'react';

const CodebaseHealth: React.FC = () => (
  <div className="p-4">
    <h2 className="font-semibold mb-2">Codebase Health</h2>
    <button type="button" title="Refresh health metrics" className="px-3 py-1 bg-blue-600 text-white rounded text-sm">
      Refresh
    </button>
  </div>
);

export default CodebaseHealth;
