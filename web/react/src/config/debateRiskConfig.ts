/**
 * Debate Risk Configuration - Frontend constants aligned with backend
 * Ensures consistent debate risk adjustment behavior across UI and backend.
 */

export const DEBATE_RISK_CONFIG = {
  // Critical alert reductions
  CRITICAL_REDUCTION_PER_ALERT: 0.20,  // 20% reduction per critical alert
  MAX_CRITICAL_ALERTS: 5,              // Cap critical alerts for safety
  MIN_CRITICAL_MULTIPLIER: 0.10,       // Minimum 10% of original size
  
  // Warning alert reductions  
  WARNING_REDUCTION_PER_ALERT: 0.10,   // 10% reduction per warning alert
  MAX_WARNING_ALERTS: 3,              // Cap warning alerts for safety
  MIN_WARNING_MULTIPLIER: 0.50,        // Minimum 50% of original size
  
  // Unknown/missing context
  UNKNOWN_MULTIPLIER: 0.80,            // Conservative reduction for unknown status
  
  // Cache and performance
  CACHE_TIMEOUT_MS: 300000,           // 5 minutes cache timeout
  
  // Safety thresholds
  MIN_POSITION_SIZE: 1,               // Minimum 1 contract
  MAX_POSITION_REDUCTION: 0.90,       // Maximum 90% reduction
} as const;

// Export individual constants for easy import
export const CRITICAL_REDUCTION_PER_ALERT = DEBATE_RISK_CONFIG.CRITICAL_REDUCTION_PER_ALERT;
export const WARNING_REDUCTION_PER_ALERT = DEBATE_RISK_CONFIG.WARNING_REDUCTION_PER_ALERT;
export const MIN_CRITICAL_MULTIPLIER = DEBATE_RISK_CONFIG.MIN_CRITICAL_MULTIPLIER;
export const MIN_WARNING_MULTIPLIER = DEBATE_RISK_CONFIG.MIN_WARNING_MULTIPLIER;
export const UNKNOWN_MULTIPLIER = DEBATE_RISK_CONFIG.UNKNOWN_MULTIPLIER;
