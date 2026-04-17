import React from 'react';
import { API_ENDPOINTS, DEFAULTS, READINESS_STATUS } from '../config/constants';
import { useApiData } from '../hooks/useApiData';

const DevSwarmReadiness = React.memo(function DevSwarmReadiness() {
  const { loading, error } = useApiData<unknown>(API_ENDPOINTS.DEV_SWARM_PAUSE, {
    pollingInterval: DEFAULTS.POLLING_INTERVALS.BACKGROUND,
  });
  if (loading) return <div className="text-slate-400 text-sm">Loading...</div>;
  if (error) return <div className="text-red-400 text-sm">Error loading readiness data.</div>;
  const status = READINESS_STATUS.OK;
  return (
    <div className="p-4">
      <h2 className="font-semibold">Swarm Readiness</h2>
      <span className="text-xs text-slate-400">{status}</span>
    </div>
  );
});

DevSwarmReadiness.displayName = 'DevSwarmReadiness';
export default DevSwarmReadiness;
