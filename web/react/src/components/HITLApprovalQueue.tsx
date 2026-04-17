import React from 'react';

const HITLApprovalQueue: React.FC = () => (
  <div className="p-4" role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.click(); }}>
    <h2 className="font-semibold mb-2">HITL Approval Queue</h2>
    <button type="button" title="Approve pending item" className="px-3 py-1 bg-green-700 text-white rounded text-sm mr-2">
      Approve
    </button>
    <button type="button" title="Reject pending item" className="px-3 py-1 bg-red-700 text-white rounded text-sm">
      Reject
    </button>
  </div>
);

export default HITLApprovalQueue;
