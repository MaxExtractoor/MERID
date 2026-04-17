import React from 'react';

export interface ExplainabilityDecision {
  decision_id: string;
  rationale: string;
  confidence: number;
  timestamp: string;
}

const ExplainabilityPanel: React.FC = () => (
  <div
    className="p-4 explainability-panel"
    role="button"
    tabIndex={0}
    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') e.currentTarget.click(); }}
  >
    <h2 className="font-semibold mb-2">Explainability</h2>
    <button type="button" title="View explanation details" className="px-3 py-1 bg-blue-600 text-white rounded text-sm">
      Details
    </button>
  </div>
);

export default ExplainabilityPanel;
