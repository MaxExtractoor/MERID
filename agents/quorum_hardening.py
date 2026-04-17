"""Quorum Failure Handling — Explicit exceptions and alerting for consensus failures.

Replaces silent NO_ACTION with loud, auditable QuorumFailure that:
- Raises exception with full context
- Triggers watchdog/alert manager notifications  
- Blocks execution until quorum restored or explicitly overridden
- Surfaces asset/timeframe-specific impact

Usage:
    from agents.quorum_hardening import (
        QuorumFailure,
        ValidatedQuorumConfig,
        require_quorum,
    )
    
    # Raises QuorumFailure if insufficient agents
    decision = await require_quorum(
        min_quorum=3,
        actual_contributions=contributions,
        decision_type="trade_execution",
        affected_assets=["BTC"],
        affected_timeframes=["15m"],
    )
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("agents.quorum")


class QuorumFailure(Exception):
    """
    Exception raised when quorum requirements are not met.
    
    Contains full context for alerting and recovery.
    """
    
    def __init__(
        self,
        message: str,
        min_quorum: int,
        actual_contributions: int,
        decision_type: str,
        affected_assets: List[str],
        affected_timeframes: List[str],
        contributing_agents: List[str],
        missing_agent_roles: List[str],
        timestamp: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.min_quorum = min_quorum
        self.actual_contributions = actual_contributions
        self.decision_type = decision_type
        self.affected_assets = affected_assets
        self.affected_timeframes = affected_timeframes
        self.contributing_agents = contributing_agents
        self.missing_agent_roles = missing_agent_roles
        self.timestamp = timestamp or time.time()
        self.metadata = metadata or {}
        self.event_id = f"quorum_fail_{int(self.timestamp)}_{hash(message) % 10000:04d}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization/alerting."""
        return {
            "event_id": self.event_id,
            "error_type": "QuorumFailure",
            "message": str(self),
            "min_quorum": self.min_quorum,
            "actual_contributions": self.actual_contributions,
            "quorum_deficit": self.min_quorum - self.actual_contributions,
            "decision_type": self.decision_type,
            "affected_assets": self.affected_assets,
            "affected_timeframes": self.affected_timeframes,
            "contributing_agents": self.contributing_agents,
            "missing_agent_roles": self.missing_agent_roles,
            "timestamp": self.timestamp,
            "human_readable": self._format_human_readable(),
            **self.metadata
        }
    
    def _format_human_readable(self) -> str:
        """Format for operator alerts."""
        assets_str = ", ".join(self.affected_assets) if self.affected_assets else "unknown"
        timeframes_str = ", ".join(self.affected_timeframes) if self.affected_timeframes else "unknown"
        
        return (
            f"QUORUM FAILURE: {self.decision_type}\n"
            f"  Assets: {assets_str}\n"
            f"  Timeframes: {timeframes_str}\n"
            f"  Required: {self.min_quorum} agents, Got: {self.actual_contributions}\n"
            f"  Missing roles: {', '.join(self.missing_agent_roles) or 'none specified'}\n"
            f"  Event ID: {self.event_id}"
        )
    
    def is_emergency(self) -> bool:
        """Determine if this is an emergency (zero contributions)."""
        return self.actual_contributions == 0


@dataclass
class ValidatedQuorumConfig:
    """
    Validated quorum configuration that prevents disabling consensus.
    
    MIN_QUORUM is clamped to valid range [1, 5] to prevent:
    - 0 (no consensus required)
    - >5 (unreasonably high barrier)
    """
    
    min_quorum: int = 3
    max_quorum: int = 5
    min_valid_quorum: int = 1
    
    # Asset/timeframe specific overrides (emergency can lower for specific markets)
    asset_overrides: Dict[str, int] = field(default_factory=dict)
    timeframe_overrides: Dict[str, int] = field(default_factory=dict)
    
    def __post_init__(self):
        # Validate and clamp from environment
        env_quorum = os.environ.get("MERID_MIN_CONSENSUS_QUORUM")
        if env_quorum:
            try:
                parsed = int(env_quorum)
                if parsed < self.min_valid_quorum:
                    logger.error(
                        f"MERID_MIN_CONSENSUS_QUORUM={parsed} below minimum {self.min_valid_quorum}, "
                        f"clamping to {self.min_valid_quorum}"
                    )
                    self.min_quorum = self.min_valid_quorum
                elif parsed > self.max_quorum:
                    logger.error(
                        f"MERID_MIN_CONSENSUS_QUORUM={parsed} above maximum {self.max_quorum}, "
                        f"clamping to {self.max_quorum}"
                    )
                    self.min_quorum = self.max_quorum
                else:
                    self.min_quorum = parsed
                    logger.info(f"MERID_MIN_CONSENSUS_QUORUM set to {self.min_quorum}")
            except ValueError:
                logger.error(f"Invalid MERID_MIN_CONSENSUS_QUORUM={env_quorum}, using default {self.min_quorum}")
    
    def get_effective_quorum(
        self,
        assets: Optional[List[str]] = None,
        timeframes: Optional[List[str]] = None,
        emergency_override: bool = False
    ) -> int:
        """
        Get effective quorum for specific assets/timeframes.
        
        Args:
            assets: List of assets in decision
            timeframes: List of timeframes in decision
            emergency_override: If True, can use lower quorum (requires audit)
        """
        base = self.min_quorum
        
        # Check for asset-specific overrides
        if assets:
            for asset in assets:
                if asset in self.asset_overrides:
                    base = min(base, self.asset_overrides[asset])
        
        # Check for timeframe-specific overrides
        if timeframes:
            for tf in timeframes:
                if tf in self.timeframe_overrides:
                    base = min(base, self.timeframe_overrides[tf])
        
        # Emergency override can reduce quorum by 1 (minimum 2 for safety)
        if emergency_override and base > 2:
            base -= 1
        
        return max(self.min_valid_quorum, min(base, self.max_quorum))
    
    def to_dict(self) -> Dict[str, Any]:
        """Export configuration for UI display."""
        return {
            "min_quorum": self.min_quorum,
            "max_allowed": self.max_quorum,
            "min_allowed": self.min_valid_quorum,
            "asset_overrides": self.asset_overrides,
            "timeframe_overrides": self.timeframe_overrides,
            "source": "MERID_MIN_CONSENSUS_QUORUM env var (validated)" if os.environ.get("MERID_MIN_CONSENSUS_QUORUM") else "default",
        }


# Global validated config instance
_validated_config: Optional[ValidatedQuorumConfig] = None


def get_validated_quorum_config() -> ValidatedQuorumConfig:
    """Get the global validated quorum config."""
    global _validated_config
    if _validated_config is None:
        _validated_config = ValidatedQuorumConfig()
    return _validated_config


async def require_quorum(
    contributions: List[Any],
    decision_type: str,
    affected_assets: Optional[List[str]] = None,
    affected_timeframes: Optional[List[str]] = None,
    required_roles: Optional[Set[str]] = None,
    emergency_override: bool = False,
) -> None:
    """
    Verify quorum requirements are met, raise QuorumFailure if not.
    
    Args:
        contributions: List of agent contributions
        decision_type: Type of decision being made
        affected_assets: Assets affected by this decision
        affected_timeframes: Timeframes affected
        required_roles: Set of required agent roles that must be present
        emergency_override: Whether to allow reduced quorum (audited)
    
    Raises:
        QuorumFailure: If quorum requirements not met
    """
    config = get_validated_quorum_config()
    
    effective_quorum = config.get_effective_quorum(
        affected_assets,
        affected_timeframes,
        emergency_override
    )
    
    actual = len(contributions)
    
    # Extract contributing agent info
    contributing_agents = []
    present_roles = set()
    
    for contrib in contributions:
        agent_id = getattr(contrib, 'agent_id', None) or contrib.get('agent_id', 'unknown')
        contributing_agents.append(agent_id)
        
        role = getattr(contrib, 'agent_role', None) or contrib.get('agent_role', None)
        if role:
            present_roles.add(str(role))
    
    # Check role requirements
    missing_roles = []
    if required_roles:
        missing_roles = list(required_roles - present_roles)
    
    # Determine if quorum is met
    quorum_met = actual >= effective_quorum and not missing_roles
    
    if not quorum_met:
        raise QuorumFailure(
            message=f"Quorum not met for {decision_type}: {actual}/{effective_quorum} agents",
            min_quorum=effective_quorum,
            actual_contributions=actual,
            decision_type=decision_type,
            affected_assets=affected_assets or [],
            affected_timeframes=affected_timeframes or [],
            contributing_agents=contributing_agents,
            missing_agent_roles=missing_roles,
            metadata={
                "emergency_override_used": emergency_override,
                "present_roles": list(present_roles),
                "required_roles": list(required_roles) if required_roles else [],
            }
        )


def format_quorum_alert(quorum_failure: QuorumFailure) -> Dict[str, Any]:
    """
    Format a QuorumFailure for alerting systems.
    
    Returns dict suitable for:
    - Telegram alerts
    - UI notifications  
    - Audit logs
    """
    severity = "critical" if quorum_failure.is_emergency() else "high"
    
    # Build asset/timeframe impact summary
    impact_summary = []
    for asset in quorum_failure.affected_assets:
        for tf in quorum_failure.affected_timeframes:
            impact_summary.append(f"{asset}-{tf}")
    
    return {
        "alert_type": "quorum_failure",
        "severity": severity,
        "event_id": quorum_failure.event_id,
        "title": f"Quorum Failure: {quorum_failure.decision_type}",
        "message": str(quorum_failure),
        "affected_markets": impact_summary,
        "affected_assets": quorum_failure.affected_assets,
        "affected_timeframes": quorum_failure.affected_timeframes,
        "required_agents": quorum_failure.min_quorum,
        "actual_agents": quorum_failure.actual_contributions,
        "missing_roles": quorum_failure.missing_agent_roles,
        "timestamp": quorum_failure.timestamp,
        "action_required": "Check agent health and restart if needed, or use emergency override with audit trail",
        "auto_resolve": False,
    }
