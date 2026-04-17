import React from 'react';

const ChartWrapper: React.FC<{ children?: React.ReactNode }> = ({ children }) => (
  <div className="chart-wrapper">{children}</div>
);

const MemoizedChartWrapper = React.memo(ChartWrapper);
MemoizedChartWrapper.displayName = 'ChartWrapper';
export default MemoizedChartWrapper;
