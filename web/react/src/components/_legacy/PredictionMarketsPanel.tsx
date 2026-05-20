import React from 'react';

const PredictionMarketsPanel: React.FC = () => (
  <div className="p-4">
    <h2 className="font-semibold mb-2">Prediction Markets</h2>
    <button type="button" title="Refresh prediction markets" className="px-3 py-1 bg-blue-600 text-white rounded text-sm">
      Refresh
    </button>
  </div>
);

export default PredictionMarketsPanel;
