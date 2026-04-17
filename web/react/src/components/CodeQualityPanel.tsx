import React from 'react';
import { API_ENDPOINTS, DEFAULTS, CHART_COLORS } from '../config/constants';
import { useApiData } from '../hooks/useApiData';

function CodeQualityPanel() {
  const { loading, error } = useApiData<unknown>(API_ENDPOINTS.SYSTEM_HEALTH, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.INFREQUENT,
  });
  if (loading) return <div className="text-slate-400 text-sm">Loading...</div>;
  if (error) return <div className="text-red-400 text-sm">Error loading code quality data.</div>;
  return (
    <div>
      <div style={{ color: CHART_COLORS.BLUE }}>Code Quality Panel</div>
    </div>
  );
}

CodeQualityPanel.displayName = 'CodeQualityPanel';
export default React.memo(CodeQualityPanel);
