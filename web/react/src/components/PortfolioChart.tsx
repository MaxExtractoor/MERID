import React from 'react';

const PortfolioChart: React.FC = () => (
  <div className="portfolio-chart" />
);

const MemoizedPortfolioChart = React.memo(PortfolioChart);
MemoizedPortfolioChart.displayName = 'PortfolioChart';
export default MemoizedPortfolioChart;
