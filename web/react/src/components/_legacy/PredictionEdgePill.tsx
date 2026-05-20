import React from 'react';

const PredictionEdgePill: React.FC<{ edge?: number }> = ({ edge = 0 }) => (
  <span className="prediction-edge-pill">{edge}</span>
);

const MemoizedPredictionEdgePill = React.memo(PredictionEdgePill);
MemoizedPredictionEdgePill.displayName = 'PredictionEdgePill';
export default MemoizedPredictionEdgePill;
