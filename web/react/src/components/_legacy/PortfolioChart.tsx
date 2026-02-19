import React from 'react';
import { useEquityChart } from '../hooks/useEquityChart';
import ChartWrapper from './ChartWrapper';

interface PortfolioChartProps {
  data: { t: string; v: number }[];
}

function PortfolioChart({ data }: PortfolioChartProps) {
  useEquityChart(data);

  return (
    <ChartWrapper title="Portfolio Equity">
      <canvas id="equityChart" className="h-64 w-full"></canvas>
    </ChartWrapper>
  );
}

const MemoizedPortfolioChart = React.memo(PortfolioChart);
MemoizedPortfolioChart.displayName = 'PortfolioChart';
export default MemoizedPortfolioChart;
