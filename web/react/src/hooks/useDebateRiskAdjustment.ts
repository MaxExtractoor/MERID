/**
 * useDebateRiskAdjustment - Hook to calculate position sizing adjustments based on debate state
 * 
 * NOTE: Debate system moved to _legacy/ - this hook returns default values
 */

import { useMemo } from 'react';

interface RiskAdjustment {
  multiplier: number;
  reason: string;
  shouldWarn: boolean;
  warningMessage: string;
}

export function useDebateRiskAdjustment(_baseSize: number = 1): RiskAdjustment {
  return useMemo(() => ({
    multiplier: 1.0,
    reason: 'Debate system deprecated - normal sizing',
    shouldWarn: false,
    warningMessage: ''
  }), []);
}

export function useAdjustedPositionSize(baseSize: number): {
  adjustedSize: number;
  adjustment: RiskAdjustment;
} {
  const adjustment = useDebateRiskAdjustment(baseSize);
  
  return {
    adjustedSize: Math.round(baseSize * adjustment.multiplier),
    adjustment
  };
}
