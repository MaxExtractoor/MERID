"""
Trading Policy Module - Severity-based trading enablement.

This module defines a single source of truth for trading mode decisions
based on severity signals from core subsystems (WS/REST transport,
DualityValidator, bankroll, market health).

Trading Modes:
- HALT: No trading allowed (P0 or P1 from any subsystem)
- EXITS_ONLY: Allow exit orders only (P2 present, no P0/P1)
- NORMAL: Full trading enabled (no active alerts above INFO)

The agent grid and order router should ONLY look at this single policy
output to decide whether to submit market/limit orders.
"""

from enum import Enum
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from merid.event_venues.kalshi.severity import Severity, Alarm


class TradingMode(Enum):
    """Trading mode based on severity signals."""
    
    HALT = "HALT"  # No trading allowed
    EXITS_ONLY = "EXITS_ONLY"  # Allow exit orders only
    NORMAL = "NORMAL"  # Full trading enabled
    
    def allows_new_entries(self) -> bool:
        """Check if this mode allows new entry orders."""
        return self == TradingMode.NORMAL
    
    def allows_exits(self) -> bool:
        """Check if this mode allows exit orders."""
        return self in (TradingMode.EXITS_ONLY, TradingMode.NORMAL)
    
    def allows_any_trading(self) -> bool:
        """Check if this mode allows any trading."""
        return self != TradingMode.HALT


@dataclass
class SubsystemStatus:
    """Status of a single subsystem."""
    
    name: str
    healthy: bool
    severity: Optional[Severity] = None
    alarms: List[Alarm] = None
    details: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.alarms is None:
            self.alarms = []
        if self.details is None:
            self.details = {}


@dataclass
class TradingPolicyResult:
    """Result of trading policy evaluation."""
    
    mode: TradingMode
    reason: str
    subsystems: Dict[str, SubsystemStatus]
    highest_severity: Severity
    blocking_subsystems: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "mode": self.mode.value,
            "reason": self.reason,
            "highest_severity": self.highest_severity.value,
            "blocking_subsystems": self.blocking_subsystems,
            "subsystems": {
                name: {
                    "healthy": status.healthy,
                    "severity": status.severity.value if status.severity else None,
                    "alarm_count": len(status.alarms),
                    "details": status.details,
                }
                for name, status in self.subsystems.items()
            },
        }


class TradingPolicy:
    """
    Trading policy engine that evaluates severity signals from all subsystems
    and determines the appropriate trading mode.
    
    This is the SINGLE SOURCE OF TRUTH for trading enablement decisions.
    All other components (agent grid, order router) should ONLY use this
    policy output to decide whether to submit orders.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize trading policy.
        
        Args:
            config: Optional configuration for severity thresholds.
                    Default: P0/P1 are fatal, P2 allows exits only.
        """
        self.config = config or {
            "fatal_severities": [Severity.P0, Severity.P1],
            "restrictive_severities": [Severity.P2],
        }
    
    def evaluate(
        self,
        ws_status: SubsystemStatus,
        rest_status: SubsystemStatus,
        duality_status: SubsystemStatus,
        bankroll_status: SubsystemStatus,
        market_health_status: SubsystemStatus,
    ) -> TradingPolicyResult:
        """
        Evaluate trading policy based on subsystem status.
        
        Args:
            ws_status: WebSocket transport status
            rest_status: REST transport status
            duality_status: Duality validator status
            bankroll_status: Bankroll service status
            market_health_status: Market health status
        
        Returns:
            TradingPolicyResult with mode and reasoning
        """
        subsystems = {
            "ws": ws_status,
            "rest": rest_status,
            "duality": duality_status,
            "bankroll": bankroll_status,
            "market_health": market_health_status,
        }
        
        # Find highest severity across all subsystems
        highest_severity = Severity.INFO
        blocking_subsystems = []
        
        for name, status in subsystems.items():
            if status.severity and status.severity.value > highest_severity.value:
                highest_severity = status.severity
            
            # Check if this subsystem is blocking
            if not status.healthy or (status.severity and status.severity in self.config["fatal_severities"]):
                blocking_subsystems.append(name)
        
        # Determine trading mode based on highest severity
        if highest_severity in self.config["fatal_severities"]:
            mode = TradingMode.HALT
            reason = f"Halting due to {highest_severity.value} from {blocking_subsystems}"
        elif highest_severity in self.config["restrictive_severities"]:
            mode = TradingMode.EXITS_ONLY
            reason = f"Restricting to exits due to {highest_severity.value}"
        else:
            mode = TradingMode.NORMAL
            reason = "Normal trading - no critical alerts"
        
        return TradingPolicyResult(
            mode=mode,
            reason=reason,
            subsystems=subsystems,
            highest_severity=highest_severity,
            blocking_subsystems=blocking_subsystems,
        )
    
    def evaluate_from_alarms(
        self,
        ws_alarms: List[Alarm],
        rest_alarms: List[Alarm],
        duality_alarms: List[Alarm],
        bankroll_alarms: List[Alarm],
        market_health_alarms: List[Alarm],
    ) -> TradingPolicyResult:
        """
        Evaluate trading policy from alarm lists (convenience method).
        
        Args:
            ws_alarms: Alarms from WebSocket transport
            rest_alarms: Alarms from REST transport
            duality_alarms: Alarms from duality validator
            bankroll_alarms: Alarms from bankroll service
            market_health_alarms: Alarms from market health
        
        Returns:
            TradingPolicyResult with mode and reasoning
        """
        # Convert alarm lists to subsystem status
        def alarms_to_status(name: str, alarms: List[Alarm]) -> SubsystemStatus:
            if not alarms:
                return SubsystemStatus(name=name, healthy=True, severity=Severity.INFO)
            
            # Find highest severity alarm
            highest_severity = max((a.severity for a in alarms), key=lambda s: s.value)
            healthy = highest_severity not in self.config["fatal_severities"]
            
            return SubsystemStatus(
                name=name,
                healthy=healthy,
                severity=highest_severity,
                alarms=alarms,
                details={"alarm_count": len(alarms)},
            )
        
        return self.evaluate(
            ws_status=alarms_to_status("ws", ws_alarms),
            rest_status=alarms_to_status("rest", rest_alarms),
            duality_status=alarms_to_status("duality", duality_alarms),
            bankroll_status=alarms_to_status("bankroll", bankroll_alarms),
            market_health_status=alarms_to_status("market_health", market_health_alarms),
        )


# Global policy instance
_trading_policy = TradingPolicy()


def get_trading_policy() -> TradingPolicy:
    """Get the global trading policy instance."""
    return _trading_policy


def evaluate_trading_mode(
    ws_alarms: List[Alarm] = None,
    rest_alarms: List[Alarm] = None,
    duality_alarms: List[Alarm] = None,
    bankroll_alarms: List[Alarm] = None,
    market_health_alarms: List[Alarm] = None,
) -> TradingPolicyResult:
    """
    Convenience function to evaluate trading mode from alarm lists.
    
    This is the primary entry point for components to check trading enablement.
    
    Args:
        ws_alarms: Alarms from WebSocket transport
        rest_alarms: Alarms from REST transport
        duality_alarms: Alarms from duality validator
        bankroll_alarms: Alarms from bankroll service
        market_health_alarms: Alarms from market health
    
    Returns:
        TradingPolicyResult with mode and reasoning
    """
    return _trading_policy.evaluate_from_alarms(
        ws_alarms=ws_alarms or [],
        rest_alarms=rest_alarms or [],
        duality_alarms=duality_alarms or [],
        bankroll_alarms=bankroll_alarms or [],
        market_health_alarms=market_health_alarms or [],
    )
