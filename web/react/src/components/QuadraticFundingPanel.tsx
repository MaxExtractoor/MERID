import React from 'react';

export interface FundingProposal {
  proposal_id: string;
  title: string;
  funding_amount: number;
  votes: number;
  status: 'open' | 'funded' | 'rejected';
}

const QuadraticFundingPanel: React.FC = () => (
  <div className="p-4">
    <h2 className="font-semibold mb-2">Quadratic Funding</h2>
    <button type="button" title="Submit funding proposal" className="px-3 py-1 bg-blue-600 text-white rounded text-sm">
      Submit Proposal
    </button>
  </div>
);

export default QuadraticFundingPanel;
