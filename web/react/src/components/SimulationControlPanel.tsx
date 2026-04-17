import React from 'react';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { useApiData } from '../hooks/useApiData';

const SimulationControlPanel = React.memo(function SimulationControlPanel() {
  const { loading, error } = useApiData<unknown>(API_ENDPOINTS.SYSTEM_HEALTH, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW,
  });
  if (loading) return <div className="text-slate-400 text-sm">Loading...</div>;
  if (error) return <div className="text-red-400 text-sm">Error loading simulation data.</div>;
  return <div className="p-4"><h2 className="font-semibold">Simulation Control</h2></div>;
});

SimulationControlPanel.displayName = 'SimulationControlPanel';
export default SimulationControlPanel;
