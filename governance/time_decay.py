"""
MERID Time-Based Authority Decay

All permissions and approvals decay over time to prevent "zombie logic."

- Trade approvals expire after 60 seconds
- Strategy approvals expire after 24 hours
- Agent trust scores decay 0.1% daily
- Old strategies auto-disable after 30 days
- Human vetos expire after 30 days
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("governance.time_decay")


class DecayType(Enum):
    """Types of time-based decay."""
    TRADE_APPROVAL = "trade_approval"
    STRATEGY_APPROVAL = "strategy_approval"
    YIELD_ALLOCATION = "yield_allocation"
    RISK_OVERRIDE = "risk_override"
    HUMAN_VETO = "human_veto"
    AGENT_TRUST = "agent_trust"
    STRATEGY_ACTIVE = "strategy_active"
    MODEL_VALIDITY = "model_validity"


@dataclass
class DecayConfig:
    """Configuration for a decay type."""
    decay_type: DecayType
    max_age_seconds: float
    decay_rate_per_day: float = 0.0  # For gradual decay
    requires_renewal: bool = True
    auto_disable: bool = False
    warning_threshold_pct: float = 80.0  # Warn at 80% of max age


# Default decay configurations
DECAY_CONFIGS: Dict[DecayType, DecayConfig] = {
    DecayType.TRADE_APPROVAL: DecayConfig(
        decay_type=DecayType.TRADE_APPROVAL,
        max_age_seconds=60,
        requires_renewal=True,
    ),
    DecayType.STRATEGY_APPROVAL: DecayConfig(
        decay_type=DecayType.STRATEGY_APPROVAL,
        max_age_seconds=86400,  # 24 hours
        requires_renewal=True,
    ),
    DecayType.YIELD_ALLOCATION: DecayConfig(
        decay_type=DecayType.YIELD_ALLOCATION,
        max_age_seconds=604800,  # 7 days
        requires_renewal=True,
    ),
    DecayType.RISK_OVERRIDE: DecayConfig(
        decay_type=DecayType.RISK_OVERRIDE,
        max_age_seconds=3600,  # 1 hour
        requires_renewal=True,
    ),
    DecayType.HUMAN_VETO: DecayConfig(
        decay_type=DecayType.HUMAN_VETO,
        max_age_seconds=2592000,  # 30 days
        requires_renewal=True,
    ),
    DecayType.AGENT_TRUST: DecayConfig(
        decay_type=DecayType.AGENT_TRUST,
        max_age_seconds=0,  # Never expires, but decays
        decay_rate_per_day=0.001,  # 0.1% per day
        requires_renewal=False,
    ),
    DecayType.STRATEGY_ACTIVE: DecayConfig(
        decay_type=DecayType.STRATEGY_ACTIVE,
        max_age_seconds=2592000,  # 30 days
        requires_renewal=True,
        auto_disable=True,
    ),
    DecayType.MODEL_VALIDITY: DecayConfig(
        decay_type=DecayType.MODEL_VALIDITY,
        max_age_seconds=604800,  # 7 days
        decay_rate_per_day=0.05,  # 5% per day
        requires_renewal=True,
    ),
}


@dataclass
class TimedAuthority:
    """An authority/permission with time-based decay."""
    authority_id: str
    decay_type: DecayType
    granted_at: float
    granted_by: str
    initial_value: float = 1.0
    current_value: float = 1.0
    renewed_at: Optional[float] = None
    renewal_count: int = 0
    disabled: bool = False
    disabled_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def get_age_seconds(self) -> float:
        """Get age since last renewal or grant."""
        reference_time = self.renewed_at or self.granted_at
        return time.time() - reference_time
    
    def get_remaining_seconds(self, config: DecayConfig) -> float:
        """Get remaining time before expiry."""
        if config.max_age_seconds == 0:
            return float('inf')
        return max(0, config.max_age_seconds - self.get_age_seconds())
    
    def is_expired(self, config: DecayConfig) -> bool:
        """Check if authority has expired."""
        if config.max_age_seconds == 0:
            return False
        return self.get_age_seconds() > config.max_age_seconds
    
    def apply_decay(self, config: DecayConfig) -> float:
        """Apply decay and return current value."""
        if config.decay_rate_per_day > 0:
            days_elapsed = self.get_age_seconds() / 86400
            decay_factor = (1 - config.decay_rate_per_day) ** days_elapsed
            self.current_value = self.initial_value * decay_factor
        return self.current_value
    
    def to_dict(self) -> Dict[str, Any]:
        config = DECAY_CONFIGS.get(self.decay_type)
        return {
            "authority_id": self.authority_id,
            "decay_type": self.decay_type.value,
            "granted_at": self.granted_at,
            "granted_by": self.granted_by,
            "initial_value": self.initial_value,
            "current_value": self.current_value,
            "age_seconds": self.get_age_seconds(),
            "remaining_seconds": self.get_remaining_seconds(config) if config else None,
            "is_expired": self.is_expired(config) if config else False,
            "renewed_at": self.renewed_at,
            "renewal_count": self.renewal_count,
            "disabled": self.disabled,
            "disabled_reason": self.disabled_reason,
        }


class TimeDecayManager:
    """
    Manages time-based authority decay across MERID.
    
    Responsibilities:
    - Track all timed authorities
    - Apply decay calculations
    - Auto-disable expired authorities
    - Warn before expiry
    - Handle renewals
    """
    
    def __init__(self):
        self._authorities: Dict[str, TimedAuthority] = {}
        self._authority_count = 0
        self._expired_count = 0
        self._renewal_count = 0
        
        logger.info("Time decay manager initialized")
    
    def grant_authority(
        self,
        decay_type: DecayType,
        granted_by: str,
        initial_value: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TimedAuthority:
        """Grant a new timed authority."""
        self._authority_count += 1
        authority_id = f"auth_{decay_type.value}_{self._authority_count}_{int(time.time())}"
        
        authority = TimedAuthority(
            authority_id=authority_id,
            decay_type=decay_type,
            granted_at=time.time(),
            granted_by=granted_by,
            initial_value=initial_value,
            current_value=initial_value,
            metadata=metadata or {},
        )
        
        self._authorities[authority_id] = authority
        
        logger.info(
            "Authority granted: %s (%s) by %s",
            authority_id, decay_type.value, granted_by
        )
        
        return authority
    
    def check_authority(
        self,
        authority_id: str,
    ) -> tuple[bool, Optional[str], Optional[TimedAuthority]]:
        """
        Check if an authority is still valid.
        
        Returns (valid, reason, authority).
        """
        if authority_id not in self._authorities:
            return False, "Authority not found", None
        
        authority = self._authorities[authority_id]
        
        if authority.disabled:
            return False, authority.disabled_reason, authority
        
        config = DECAY_CONFIGS.get(authority.decay_type)
        if not config:
            return False, "Unknown decay type", authority
        
        # Check expiry
        if authority.is_expired(config):
            self._expire_authority(authority, config)
            return False, "Authority expired", authority
        
        # Apply decay
        authority.apply_decay(config)
        
        # Check if decayed below threshold
        if authority.current_value < 0.1:
            return False, "Authority decayed below threshold", authority
        
        return True, None, authority
    
    def renew_authority(
        self,
        authority_id: str,
        renewed_by: str,
    ) -> tuple[bool, Optional[str]]:
        """
        Renew an authority to reset its decay timer.
        
        Returns (success, reason).
        """
        if authority_id not in self._authorities:
            return False, "Authority not found"
        
        authority = self._authorities[authority_id]
        
        if authority.disabled:
            return False, "Cannot renew disabled authority"
        
        config = DECAY_CONFIGS.get(authority.decay_type)
        if not config or not config.requires_renewal:
            return False, "Authority type does not support renewal"
        
        # Renew
        authority.renewed_at = time.time()
        authority.renewal_count += 1
        authority.current_value = authority.initial_value
        self._renewal_count += 1
        
        logger.info(
            "Authority renewed: %s by %s (renewal #%d)",
            authority_id, renewed_by, authority.renewal_count
        )
        
        return True, None
    
    def _expire_authority(
        self,
        authority: TimedAuthority,
        config: DecayConfig,
    ) -> None:
        """Handle authority expiration."""
        self._expired_count += 1
        
        if config.auto_disable:
            authority.disabled = True
            authority.disabled_reason = "Auto-disabled due to expiry"
            logger.warning(
                "Authority auto-disabled: %s (expired after %d seconds)",
                authority.authority_id, config.max_age_seconds
            )
        else:
            logger.info(
                "Authority expired: %s",
                authority.authority_id
            )
    
    def get_expiring_soon(
        self,
        threshold_seconds: float = 300,
    ) -> List[TimedAuthority]:
        """Get authorities expiring within threshold."""
        expiring = []
        
        for authority in self._authorities.values():
            if authority.disabled:
                continue
            
            config = DECAY_CONFIGS.get(authority.decay_type)
            if not config or config.max_age_seconds == 0:
                continue
            
            remaining = authority.get_remaining_seconds(config)
            if 0 < remaining < threshold_seconds:
                expiring.append(authority)
        
        return expiring
    
    def cleanup_expired(self) -> int:
        """Clean up expired authorities and return count."""
        cleaned = 0
        
        for authority_id, authority in list(self._authorities.items()):
            config = DECAY_CONFIGS.get(authority.decay_type)
            if config and authority.is_expired(config):
                self._expire_authority(authority, config)
                cleaned += 1
        
        return cleaned
    
    def get_authority(self, authority_id: str) -> Optional[TimedAuthority]:
        """Get an authority by ID."""
        return self._authorities.get(authority_id)
    
    def get_authorities_by_type(
        self,
        decay_type: DecayType,
        include_disabled: bool = False,
    ) -> List[TimedAuthority]:
        """Get all authorities of a specific type."""
        return [
            a for a in self._authorities.values()
            if a.decay_type == decay_type and (include_disabled or not a.disabled)
        ]
    
    def get_status(self) -> Dict[str, Any]:
        """Get manager status."""
        active = sum(1 for a in self._authorities.values() if not a.disabled)
        disabled = sum(1 for a in self._authorities.values() if a.disabled)
        
        by_type = {}
        for decay_type in DecayType:
            authorities = self.get_authorities_by_type(decay_type)
            by_type[decay_type.value] = {
                "count": len(authorities),
                "config": {
                    "max_age_seconds": DECAY_CONFIGS[decay_type].max_age_seconds,
                    "decay_rate_per_day": DECAY_CONFIGS[decay_type].decay_rate_per_day,
                }
            }
        
        return {
            "total_authorities": len(self._authorities),
            "active": active,
            "disabled": disabled,
            "expired_count": self._expired_count,
            "renewal_count": self._renewal_count,
            "by_type": by_type,
            "expiring_soon": len(self.get_expiring_soon()),
        }
    
    def get_all_authorities(
        self,
        include_disabled: bool = False,
    ) -> List[Dict[str, Any]]:
        """Get all authorities."""
        return [
            a.to_dict() for a in self._authorities.values()
            if include_disabled or not a.disabled
        ]


# Singleton instance
_decay_manager: Optional[TimeDecayManager] = None
_decay_manager_lock = threading.Lock()


def get_time_decay_manager() -> TimeDecayManager:
    """Get the singleton time decay manager."""
    global _decay_manager
    if _decay_manager is None:
        with _decay_manager_lock:
            if _decay_manager is None:
                _decay_manager = TimeDecayManager()
    return _decay_manager
