import React from 'react';

export interface ConsensusPanelStatus {
  consensus_id: string;
  agreement_pct: number;
  participants: number;
  status: 'pending' | 'reached' | 'failed';
}

const ConsensusPanel: React.FC = () => (
  <div className="p-4">
    <h2 className="font-semibold mb-2">Consensus</h2>
    <button type="button" title="Refresh consensus status" className="px-3 py-1 bg-slate-700 text-white rounded text-sm">
      Refresh
    </button>
  </div>
);

export default ConsensusPanel;
