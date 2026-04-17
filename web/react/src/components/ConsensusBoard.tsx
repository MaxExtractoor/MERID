import React from 'react';

function ConsensusBoard() {
  return (
    <div className="p-4">
      <h2 className="font-semibold mb-2">Consensus Board</h2>
      <button type="button" title="Refresh consensus board" className="px-3 py-1 bg-slate-700 text-white rounded text-sm">
        Refresh
      </button>
    </div>
  );
}

ConsensusBoard.displayName = 'ConsensusBoard';
export default React.memo(ConsensusBoard);
