import React from 'react';
import { API_ENDPOINTS, DEFAULTS, CHART_COLORS } from '../config/constants';
import { useApiData } from '../hooks/useApiData';

interface DomainPnLChartProps {
  venue: string;
}

const DomainPnLChart = React.memo(function DomainPnLChart({ venue }: DomainPnLChartProps) {
  const { loading, error } = useApiData<unknown>(API_ENDPOINTS.PIPELINE_PNL(venue), {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD,
  });
  if (loading) return <div className="text-slate-400 text-sm">Loading...</div>;
  if (error) return <div className="text-red-400 text-sm">Error loading PnL data.</div>;
  return (
    <div>
      <div style={{ color: CHART_COLORS.GREEN }}>Domain PnL Chart</div>
    </div>
  );
});

DomainPnLChart.displayName = 'DomainPnLChart';
export default DomainPnLChart;
