import { useApiData } from './useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

export interface BlockReason {
  source: string;
  severity: string;
  message: string;
  details: string | null;
  hint: string | null;
}

export type GateState = 'clear' | 'limited' | 'blocked';

interface ExecutionGateData {
  blocked: boolean;
  safe_to_trade: boolean;
  gate_state: GateState;
  reasons: BlockReason[];
  timestamp: number;
}

/**
 * Hook to check execution gate status for use in trading controls.
 * Returns { blocked, gateState, reasons, topHint, error, hasData } so controls can grey out + show tooltips.
 */
export function useExecutionGate() {
  const { data, error } = useApiData<ExecutionGateData>(
    API_ENDPOINTS.SYSTEM_EXECUTION_GATE,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH },
  );

  const reasons = data?.reasons ?? [];
  const topHint = reasons.find(r => r.hint)?.hint ?? null;

  return {
    blocked: data?.blocked ?? true,  // default blocked until first check
    safeToTrade: data?.safe_to_trade ?? false,
    gateState: (data?.gate_state ?? 'blocked') as GateState,
    reasons,
    blockSummary: reasons.map(r => r.message).join('; ') || 'Checking safety...',
    topHint,
    error: error?.message ?? null,
    hasData: !!data,
  };
}
