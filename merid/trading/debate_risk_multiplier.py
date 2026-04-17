"""
Debate Risk Multiplier - Backend position sizing adjustments based on debate state
Mirrors the UI logic from useDebateRiskAdjustment for consistent risk management
"""

import logging
from typing import Dict, Optional, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass

from .debate_risk_config import DEBATE_RISK_CONFIG

logger = logging.getLogger(__name__)

@dataclass
class DebateRiskAdjustment:
    """Risk adjustment based on debate state"""
    multiplier: float
    reason: str
    should_warn: bool
    warning_message: str
    original_size: int
    adjusted_size: int
    debate_status: str
    alert_counts: Dict[str, int]

class DebateRiskMultiplier:
    """
    Calculates position size multipliers based on debate system state.
    Mirrors UI logic for consistent risk management across frontend and backend.
    """
    
    def __init__(self):
        # Configuration for risk adjustments - using shared config
        self.critical_reduction_per_alert = DEBATE_RISK_CONFIG.CRITICAL_REDUCTION_PER_ALERT
        self.warning_reduction_per_alert = DEBATE_RISK_CONFIG.WARNING_REDUCTION_PER_ALERT
        self.max_critical_alerts = DEBATE_RISK_CONFIG.MAX_CRITICAL_ALERTS
        self.max_warning_alerts = DEBATE_RISK_CONFIG.MAX_WARNING_ALERTS
        self.min_critical_multiplier = DEBATE_RISK_CONFIG.MIN_CRITICAL_MULTIPLIER
        self.min_warning_multiplier = DEBATE_RISK_CONFIG.MIN_WARNING_MULTIPLIER
        self.unknown_multiplier = DEBATE_RISK_CONFIG.UNKNOWN_MULTIPLIER
        
        # Cache for debate context to avoid excessive API calls
        self._cache_timeout = DEBATE_RISK_CONFIG.CACHE_TIMEOUT_SECONDS
        self._last_fetch: Optional[datetime] = None
        self._cached_context: Optional[Dict] = None
    
    def calculate_multiplier(self, debate_context: Dict, base_size: int) -> DebateRiskAdjustment:
        """
        Calculate position size multiplier based on debate state.
        
        Args:
            debate_context: Debate context from PredictionPublisher
            base_size: Original position size in contracts
            
        Returns:
            DebateRiskAdjustment with multiplier and details
        """
        if not debate_context:
            return self._create_unknown_adjustment(base_size)
        
        status = debate_context.get('status', 'unknown')
        
        # Handle malformed alerts_24h
        alerts_24h = debate_context.get('alerts_24h', {})
        if not isinstance(alerts_24h, dict):
            alerts_24h = {'critical': 0, 'warnings': 0, 'total': 0}
        else:
            # Ensure all required fields exist
            alerts_24h = {
                'critical': alerts_24h.get('critical', 0),
                'warnings': alerts_24h.get('warnings', 0),
                'total': alerts_24h.get('total', 0)
            }
        
        critical_count = alerts_24h.get('critical', 0)
        warning_count = alerts_24h.get('warnings', 0)
        total_alerts = alerts_24h.get('total', 0)
        
        # Default: no adjustment
        if total_alerts == 0:
            return DebateRiskAdjustment(
                multiplier=1.0,
                reason='No debate alerts - normal sizing',
                should_warn=False,
                warning_message='',
                original_size=base_size,
                adjusted_size=base_size,
                debate_status=status,
                alert_counts=alerts_24h
            )
        
        # Critical alerts: significant reduction
        if critical_count > 0:
            return self._calculate_critical_adjustment(
                critical_count, warning_count, total_alerts, base_size, status, alerts_24h
            )
        
        # Warning alerts: moderate reduction
        if warning_count > 0:
            return self._calculate_warning_adjustment(
                warning_count, total_alerts, base_size, status, alerts_24h
            )
        
        # Unknown status: conservative reduction
        return self._calculate_unknown_adjustment(base_size, status, alerts_24h)
    
    def _calculate_critical_adjustment(self, critical_count: int, warning_count: int, 
                                     total_alerts: int, base_size: int, status: str, 
                                     alerts_24h: Dict) -> DebateRiskAdjustment:
        """Calculate adjustment for critical debate state"""
        # Cap critical alerts for safety
        effective_critical = min(critical_count, self.max_critical_alerts)
        reduction = self.critical_reduction_per_alert * effective_critical
        multiplier = max(self.min_critical_multiplier, 1.0 - reduction)
        adjusted_size = max(1, int(base_size * multiplier))  # Minimum 1 contract
        
        return DebateRiskAdjustment(
            multiplier=multiplier,
            reason=f'Critical debate alerts: {total_alerts} total, {critical_count} critical',
            should_warn=True,
            warning_message=f'⚠️ Debate system critical - position size reduced by {int((1 - multiplier) * 100)}%',
            original_size=base_size,
            adjusted_size=adjusted_size,
            debate_status=status,
            alert_counts=alerts_24h
        )
    
    def _calculate_warning_adjustment(self, warning_count: int, total_alerts: int,
                                    base_size: int, status: str, alerts_24h: Dict) -> DebateRiskAdjustment:
        """Calculate adjustment for degraded debate state"""
        # Cap warning alerts for safety
        effective_warnings = min(warning_count, self.max_warning_alerts)
        reduction = self.warning_reduction_per_alert * effective_warnings
        multiplier = max(self.min_warning_multiplier, 1.0 - reduction)
        adjusted_size = max(1, int(base_size * multiplier))  # Minimum 1 contract
        
        return DebateRiskAdjustment(
            multiplier=multiplier,
            reason=f'Debate warnings: {total_alerts} total warnings',
            should_warn=True,
            warning_message=f'⚠️ Debate system degraded - position size reduced by {int((1 - multiplier) * 100)}%',
            original_size=base_size,
            adjusted_size=adjusted_size,
            debate_status=status,
            alert_counts=alerts_24h
        )
    
    def _calculate_unknown_adjustment(self, base_size: int, status: str, 
                                    alerts_24h: Dict) -> DebateRiskAdjustment:
        """Calculate adjustment for unknown debate state"""
        multiplier = self.unknown_multiplier
        adjusted_size = max(1, int(base_size * multiplier))  # Minimum 1 contract
        
        return DebateRiskAdjustment(
            multiplier=multiplier,
            reason='Debate system status unknown - conservative sizing',
            should_warn=True,
            warning_message='⚠️ Debate system status unknown - using conservative position sizing',
            original_size=base_size,
            adjusted_size=adjusted_size,
            debate_status=status,
            alert_counts=alerts_24h
        )
    
    def _create_unknown_adjustment(self, base_size: int) -> DebateRiskAdjustment:
        """Create adjustment for missing debate context"""
        multiplier = self.unknown_multiplier
        adjusted_size = max(1, int(base_size * multiplier))
        
        return DebateRiskAdjustment(
            multiplier=multiplier,
            reason='Debate context unavailable - conservative sizing',
            should_warn=True,
            warning_message='⚠️ Debate context unavailable - using conservative position sizing',
            original_size=base_size,
            adjusted_size=adjusted_size,
            debate_status='unknown',
            alert_counts={'critical': 0, 'warnings': 0, 'total': 0}
        )

# Global instance for consistent behavior
_debate_risk_multiplier: Optional[DebateRiskMultiplier] = None

def get_debate_risk_multiplier() -> DebateRiskMultiplier:
    """Get the global debate risk multiplier instance"""
    global _debate_risk_multiplier
    if _debate_risk_multiplier is None:
        _debate_risk_multiplier = DebateRiskMultiplier()
    return _debate_risk_multiplier

def apply_debate_risk_adjustment(base_size: int, debate_context: Optional[Dict] = None) -> DebateRiskAdjustment:
    """
    Apply debate risk adjustment to position size.
    
    Args:
        base_size: Original position size in contracts
        debate_context: Debate context from PredictionPublisher (optional)
        
    Returns:
        DebateRiskAdjustment with multiplier and adjusted size
    """
    multiplier = get_debate_risk_multiplier()
    adjustment = multiplier.calculate_multiplier(debate_context or {}, base_size)
    
    # Log the adjustment for audit trail
    if adjustment.should_warn:
        logger.warning(
            f"Debate risk adjustment applied: {adjustment.reason} | "
            f"Size: {adjustment.original_size} → {adjustment.adjusted_size} "
            f"({adjustment.multiplier:.2f}x) | Status: {adjustment.debate_status}"
        )
    else:
        logger.info(
            f"Debate risk check: {adjustment.reason} | "
            f"Size: {adjustment.original_size} → {adjustment.adjusted_size} "
            f"({adjustment.multiplier:.2f}x)"
        )
    
    return adjustment
