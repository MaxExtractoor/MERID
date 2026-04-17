import React from 'react';

function SharpeRatioTile() {
  return (
    <div className="p-4">
      <h2 className="font-semibold mb-2">Sharpe Ratio</h2>
      <button type="button" title="Refresh Sharpe ratio" className="px-3 py-1 bg-slate-700 text-white rounded text-sm">
        Refresh
      </button>
    </div>
  );
}

SharpeRatioTile.displayName = 'SharpeRatioTile';
export default React.memo(SharpeRatioTile);
