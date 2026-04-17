import React from 'react';

const ChartCard: React.FC<{ children?: React.ReactNode }> = ({ children }) => (
  <div className="chart-card">{children}</div>
);

const MemoizedChartCard = React.memo(ChartCard);
MemoizedChartCard.displayName = 'ChartCard';
export default MemoizedChartCard;
