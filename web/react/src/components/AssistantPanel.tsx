import React, { useState } from 'react';

const AssistantPanel: React.FC = () => {
  const [query, setQuery] = useState('');

  return (
    <div className="p-4">
      <h2 className="font-semibold mb-3">Assistant</h2>
      <div className="flex gap-2 mb-3">
        <input
          type="text"
          aria-label="Assistant query"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask the assistant..."
          className="flex-1 bg-slate-700 border border-slate-600 rounded px-3 py-2 text-sm text-white"
        />
        <button type="button" title="Send query to assistant" className="px-4 py-2 bg-blue-600 text-white rounded text-sm">
          Send
        </button>
      </div>
      <div className="flex gap-2">
        <button type="button" title="Clear assistant conversation" className="px-3 py-1 bg-slate-700 text-white rounded text-sm">
          Clear
        </button>
        <button type="button" title="Copy assistant response" className="px-3 py-1 bg-slate-700 text-white rounded text-sm">
          Copy
        </button>
      </div>
    </div>
  );
};

export default AssistantPanel;
