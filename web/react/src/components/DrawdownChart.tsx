import React from 'react';
import { API_ENDPOINTS, DEFAULTS, CHART_COLORS } from '../config/constants';
import { useApiData } from '../hooks/useApiData';

interface DrawdownChartProps {
  agentId: string;
}

const DrawdownChart = React.memo(function DrawdownChart({ agentId }: DrawdownChartProps) {
  const { loading, error } = useApiData<unknown>(API_ENDPOINTS.RISK_AGENT_DRAWDOWN_HISTORY(agentId), {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD,
  });
  if (loading) return <div className="text-slate-400 text-sm">Loading...</div>;
  if (error) return <div className="text-red-400 text-sm">Error loading drawdown data.</div>;
  return (
    <div>
      <div style={{ color: CHART_COLORS.RED }}>Drawdown Chart</div>
    </div>
  );
});

DrawdownChart.displayName = 'DrawdownChart';
export default DrawdownChart;
