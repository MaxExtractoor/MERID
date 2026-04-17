/**
 * useDebateRiskAdjustment - Hook to calculate position sizing adjustments based on debate state
 */

import { useMemo } from 'react';
import { useDebateContext } from './useDebateContext';
import { DEBATE_RISK_CONFIG } from '../config/debateRiskConfig';

interface RiskAdjustment {
  multiplier: number;
  reason: string;
  shouldWarn: boolean;
  warningMessage: string;
}

export function useDebateRiskAdjustment(_baseSize: number = 1): RiskAdjustment {
  const { getDebateStatus, hasCriticalAlerts, hasWarnings, getTotalAlerts, getTopAlert } = useDebateContext();

  return useMemo(() => {
    const status = getDebateStatus();
    const totalAlerts = getTotalAlerts();
    const topAlert = getTopAlert();

    // Default: no adjustment
    if (totalAlerts === 0) {
      return {
        multiplier: 1.0,
        reason: 'No debate alerts - normal sizing',
        shouldWarn: false,
        warningMessage: ''
      };
    }

    // Critical alerts: reduce position size significantly
    if (hasCriticalAlerts()) {
      const criticalCount = Math.min(totalAlerts, DEBATE_RISK_CONFIG.MAX_CRITICAL_ALERTS);
      const reduction = DEBATE_RISK_CONFIG.CRITICAL_REDUCTION_PER_ALERT * criticalCount;
      const multiplier = Math.max(DEBATE_RISK_CONFIG.MIN_CRITICAL_MULTIPLIER, 1.0 - reduction);
      
      return {
        multiplier,
        reason: `Critical debate alerts: ${totalAlerts} total, ${criticalCount} critical`,
        shouldWarn: true,
        warningMessage: `⚠️ Debate system critical - position size reduced by ${Math.round((1 - multiplier) * 100)}%. Latest: ${topAlert?.message || 'System degraded'}`
      };
    }

    // Warning alerts: moderate position size reduction
    if (hasWarnings()) {
      const warningCount = Math.min(totalAlerts, DEBATE_RISK_CONFIG.MAX_WARNING_ALERTS);
      const reduction = DEBATE_RISK_CONFIG.WARNING_REDUCTION_PER_ALERT * warningCount;
      const multiplier = Math.max(DEBATE_RISK_CONFIG.MIN_WARNING_MULTIPLIER, 1.0 - reduction);
      
      return {
        multiplier,
        reason: `Debate warnings: ${totalAlerts} total warnings`,
        shouldWarn: true,
        warningMessage: `⚠️ Debate system degraded - position size reduced by ${Math.round((1 - multiplier) * 100)}%. Latest: ${topAlert?.message || 'System warnings active'}`
      };
    }

    // Unknown status: conservative reduction
    if (status === 'unknown') {
      return {
        multiplier: DEBATE_RISK_CONFIG.UNKNOWN_MULTIPLIER,
        reason: 'Debate system status unknown - conservative sizing',
        shouldWarn: true,
        warningMessage: '⚠️ Debate system status unknown - using conservative position sizing'
      };
    }

    // Fallback
    return {
      multiplier: 0.9,
      reason: 'Debate system active - slight reduction',
      shouldWarn: false,
      warningMessage: ''
    };
  }, [getDebateStatus, hasCriticalAlerts, hasWarnings, getTotalAlerts, getTopAlert]);
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
