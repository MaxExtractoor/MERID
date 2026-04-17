"""
Debate Risk Filter for Trading Agent
Simple risk flag that checks for critical debate alerts before sizing trades.
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class DebateRiskFilter:
    """
    Simple risk filter that checks debate alerts before allowing trades.
    
    This provides a lightweight way to ensure the debate system isn't in a 
    known-bad state when making trading decisions.
    """
    
    def __init__(self, cache_minutes: int = 5):
        """
        Initialize the debate risk filter.
        
        Args:
            cache_minutes: How long to cache alert status (default: 5 minutes)
        """
        self.cache_minutes = cache_minutes
        self._alert_cache: Dict[str, Dict[str, Any]] = {}
        self._last_cache_update: Optional[datetime] = None
    
    async def check_agent_risk(self, agent_id: str, strategy_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Check if an agent has critical debate alerts that should block trading.
        
        Args:
            agent_id: The agent ID to check
            strategy_id: Optional strategy ID to check
            
        Returns:
            Risk assessment dict with:
            - blocked: bool - Whether trading should be blocked
            - reason: str - Reason for blocking (if blocked)
            - critical_alerts: int - Number of critical alerts
            - last_checked: datetime - When this check was performed
        """
        try:
            # Import here to avoid circular imports
            from web.api.debate_data_api import get_debate_alerts
            
            # Check cache first
            cache_key = f"{agent_id}_{strategy_id or 'default'}"
            now = datetime.now()
            
            if (self._last_cache_update and 
                now - self._last_cache_update < timedelta(minutes=self.cache_minutes) and
                cache_key in self._alert_cache):
                logger.debug(f"Using cached debate risk assessment for {agent_id}")
                return self._alert_cache[cache_key]
            
            # Fetch fresh alerts
            alerts_response = await get_debate_alerts(
                days_back=1,  # Last 24 hours
                tier="all",
                utilization_band="all",
                problems_only=True  # Only problems matter for risk
            )
            
            if not alerts_response or not alerts_response.get("alerts"):
                # No alerts - safe to trade
                result = {
                    "blocked": False,
                    "reason": None,
                    "critical_alerts": 0,
                    "warning_alerts": 0,
                    "last_checked": now
                }
                self._update_cache(cache_key, result)
                return result
            
            alerts = alerts_response["alerts"]
            
            # Filter alerts for this agent (and strategy if provided)
            agent_alerts = [
                alert for alert in alerts 
                if alert["agent_id"] == agent_id
            ]
            
            # If strategy filtering is needed, we could extend this
            # For now, we only filter by agent ID
            
            critical_count = sum(1 for alert in agent_alerts if alert["severity"] == "critical")
            warning_count = sum(1 for alert in agent_alerts if alert["severity"] == "warning")
            
            # Simple risk rule: block if any critical alerts
            blocked = critical_count > 0
            reason = None
            
            if blocked:
                if critical_count == 1:
                    reason = f"Agent {agent_id} has 1 critical debate alert"
                else:
                    reason = f"Agent {agent_id} has {critical_count} critical debate alerts"
            
            result = {
                "blocked": blocked,
                "reason": reason,
                "critical_alerts": critical_count,
                "warning_alerts": warning_count,
                "last_checked": now
            }
            
            self._update_cache(cache_key, result)
            return result
            
        except Exception as e:
            logger.error(f"Error checking debate risk for {agent_id}: {e}")
            # Fail safe - allow trading but log the error
            return {
                "blocked": False,
                "reason": f"Error checking debate alerts: {str(e)}",
                "critical_alerts": 0,
                "warning_alerts": 0,
                "last_checked": datetime.now()
            }
    
    def _update_cache(self, key: str, result: Dict[str, Any]):
        """Update the internal cache with new results."""
        self._alert_cache[key] = result
        self._last_cache_update = datetime.now()
    
    def clear_cache(self):
        """Clear the internal cache - useful for testing or forced refresh."""
        self._alert_cache.clear()
        self._last_cache_update = None
    
    async def get_system_risk_summary(self) -> Dict[str, Any]:
        """
        Get a summary of debate system risk across all agents.
        
        Returns:
            System-wide risk summary
        """
        try:
            from web.api.debate_data_api import get_debate_alerts
            
            alerts_response = await get_debate_alerts(
                days_back=1,
                tier="all",
                utilization_band="all",
                problems_only=True
            )
            
            if not alerts_response or not alerts_response.get("alerts"):
                return {
                    "system_status": "healthy",
                    "total_critical": 0,
                    "total_warnings": 0,
                    "affected_agents": [],
                    "last_checked": datetime.now()
                }
            
            alerts = alerts_response["alerts"]
            
            critical_count = sum(1 for alert in alerts if alert["severity"] == "critical")
            warning_count = sum(1 for alert in alerts if alert["severity"] == "warning")
            
            # Get unique affected agents
            affected_agents = list(set(alert["agent_id"] for alert in alerts))
            
            # Determine system status
            if critical_count == 0:
                system_status = "healthy"
            elif critical_count <= 2:
                system_status = "degraded"
            else:
                system_status = "critical"
            
            return {
                "system_status": system_status,
                "total_critical": critical_count,
                "total_warnings": warning_count,
                "affected_agents": affected_agents,
                "last_checked": datetime.now()
            }
            
        except Exception as e:
            logger.error(f"Error getting system risk summary: {e}")
            return {
                "system_status": "unknown",
                "total_critical": 0,
                "total_warnings": 0,
                "affected_agents": [],
                "last_checked": datetime.now(),
                "error": str(e)
            }

# Global instance for reuse
_debate_risk_filter: Optional[DebateRiskFilter] = None

def get_debate_risk_filter() -> DebateRiskFilter:
    """Get or create the global debate risk filter instance."""
    global _debate_risk_filter
    if _debate_risk_filter is None:
        _debate_risk_filter = DebateRiskFilter()
    return _debate_risk_filter
