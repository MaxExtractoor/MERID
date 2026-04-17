"""
MERID Recovery - Shadow Promotion Manager

Manages failover control and shadow system promotion.
Enables seamless transition from primary to backup systems.

Part of MERID-GOV (Layer 0 - Constitutional Foundation)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("recovery.shadow_promotion")


class SystemRole(Enum):
    """Role of a system instance."""
    PRIMARY = "primary"
    SHADOW = "shadow"
    STANDBY = "standby"
    PROMOTING = "promoting"
    DEMOTING = "demoting"
    OFFLINE = "offline"


class PromotionReason(Enum):
    """Reason for promotion."""
    PRIMARY_FAILURE = "primary_failure"
    SCHEDULED_MAINTENANCE = "scheduled_maintenance"
    PERFORMANCE_DEGRADATION = "performance_degradation"
    MANUAL_OVERRIDE = "manual_override"
    HEALTH_CHECK_FAILURE = "health_check_failure"
    DIVERGENCE_DETECTED = "divergence_detected"


@dataclass
class SystemInstance:
    """A system instance (primary or shadow)."""
    instance_id: str
    system_name: str
    role: SystemRole
    
    # Health
    last_heartbeat: float = 0.0
    health_score: float = 1.0
    consecutive_failures: int = 0
    
    # State
    state_hash: str = ""
    last_sync_ts: float = 0.0
    sync_lag_ms: float = 0.0
    
    # Metadata
    created_at: float = field(default_factory=time.time)
    promoted_at: Optional[float] = None
    demoted_at: Optional[float] = None
    
    def is_healthy(self, heartbeat_timeout: float = 30.0) -> bool:
        """Check if instance is healthy."""
        if self.role == SystemRole.OFFLINE:
            return False
        
        time_since_heartbeat = time.time() - self.last_heartbeat
        return (
            time_since_heartbeat < heartbeat_timeout and
            self.health_score > 0.5 and
            self.consecutive_failures < 3
        )
    
    def record_heartbeat(self, health_score: float = 1.0) -> None:
        """Record a heartbeat."""
        self.last_heartbeat = time.time()
        self.health_score = health_score
        if health_score > 0.8:
            self.consecutive_failures = 0
    
    def record_failure(self) -> None:
        """Record a failure."""
        self.consecutive_failures += 1
        self.health_score = max(0, self.health_score - 0.2)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "system_name": self.system_name,
            "role": self.role.value,
            "health_score": round(self.health_score, 4),
            "consecutive_failures": self.consecutive_failures,
            "is_healthy": self.is_healthy(),
            "last_heartbeat": self.last_heartbeat,
            "sync_lag_ms": self.sync_lag_ms,
        }


@dataclass
class PromotionEvent:
    """A promotion/demotion event."""
    event_id: str
    timestamp: float
    
    # Instances involved
    promoted_instance: str
    demoted_instance: Optional[str]
    
    # Details
    reason: PromotionReason
    initiated_by: str
    
    # Outcome
    success: bool = False
    duration_ms: float = 0.0
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "promoted_instance": self.promoted_instance,
            "demoted_instance": self.demoted_instance,
            "reason": self.reason.value,
            "initiated_by": self.initiated_by,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


class ShadowPromotionManager:
    """
    Manages shadow system promotion and failover.
    
    Features:
    - Automatic failover on primary failure
    - Manual promotion support
    - State synchronization verification
    - Promotion history tracking
    - Health monitoring
    """
    
    def __init__(
        self,
        heartbeat_timeout: float = 30.0,
        auto_failover: bool = True,
        min_sync_threshold_ms: float = 1000.0,
    ):
        self._instances: Dict[str, SystemInstance] = {}
        self._primary_id: Optional[str] = None
        self._promotion_history: List[PromotionEvent] = []
        
        # Configuration
        self._heartbeat_timeout = heartbeat_timeout
        self._auto_failover = auto_failover
        self._min_sync_threshold_ms = min_sync_threshold_ms
        
        # Callbacks
        self._on_promotion: Optional[Callable[[PromotionEvent], None]] = None
        self._on_demotion: Optional[Callable[[str], None]] = None
        
        logger.info(
            "Shadow promotion manager initialized: auto_failover=%s",
            auto_failover
        )
    
    def register_instance(
        self,
        instance_id: str,
        system_name: str,
        role: SystemRole = SystemRole.SHADOW,
    ) -> SystemInstance:
        """Register a system instance."""
        instance = SystemInstance(
            instance_id=instance_id,
            system_name=system_name,
            role=role,
        )
        
        self._instances[instance_id] = instance
        
        if role == SystemRole.PRIMARY:
            self._primary_id = instance_id
        
        logger.info(
            "Registered instance %s as %s",
            instance_id[:8], role.value
        )
        
        return instance
    
    def heartbeat(
        self,
        instance_id: str,
        health_score: float = 1.0,
        state_hash: str = "",
        sync_lag_ms: float = 0.0,
    ) -> bool:
        """Record heartbeat from an instance."""
        instance = self._instances.get(instance_id)
        if not instance:
            logger.warning("Unknown instance: %s", instance_id)
            return False
        
        instance.record_heartbeat(health_score)
        instance.state_hash = state_hash
        instance.sync_lag_ms = sync_lag_ms
        instance.last_sync_ts = time.time()
        
        return True
    
    def check_primary_health(self) -> bool:
        """Check if primary is healthy."""
        if not self._primary_id:
            return False
        
        primary = self._instances.get(self._primary_id)
        if not primary:
            return False
        
        return primary.is_healthy(self._heartbeat_timeout)
    
    def get_best_shadow(self) -> Optional[SystemInstance]:
        """Get the best shadow for promotion."""
        shadows = [
            inst for inst in self._instances.values()
            if inst.role == SystemRole.SHADOW and inst.is_healthy()
        ]
        
        if not shadows:
            return None
        
        # Sort by health score and sync lag
        shadows.sort(
            key=lambda s: (s.health_score, -s.sync_lag_ms),
            reverse=True
        )
        
        best = shadows[0]
        
        # Check sync threshold
        if best.sync_lag_ms > self._min_sync_threshold_ms:
            logger.warning(
                "Best shadow %s has high sync lag: %.2fms",
                best.instance_id[:8], best.sync_lag_ms
            )
        
        return best
    
    def promote(
        self,
        instance_id: str,
        reason: PromotionReason,
        initiated_by: str = "system",
    ) -> PromotionEvent:
        """Promote an instance to primary."""
        import uuid
        
        start_time = time.time()
        
        instance = self._instances.get(instance_id)
        if not instance:
            raise ValueError(f"Instance not found: {instance_id}")
        
        if instance.role == SystemRole.PRIMARY:
            raise ValueError(f"Instance already primary: {instance_id}")
        
        # Create event
        event = PromotionEvent(
            event_id=str(uuid.uuid4()),
            timestamp=start_time,
            promoted_instance=instance_id,
            demoted_instance=self._primary_id,
            reason=reason,
            initiated_by=initiated_by,
        )
        
        try:
            # Demote current primary
            if self._primary_id:
                old_primary = self._instances.get(self._primary_id)
                if old_primary:
                    old_primary.role = SystemRole.SHADOW
                    old_primary.demoted_at = time.time()
                    
                    if self._on_demotion:
                        self._on_demotion(self._primary_id)
            
            # Promote new primary
            instance.role = SystemRole.PRIMARY
            instance.promoted_at = time.time()
            self._primary_id = instance_id
            
            event.success = True
            event.duration_ms = (time.time() - start_time) * 1000
            
            logger.info(
                "Promoted %s to primary (reason: %s, duration: %.2fms)",
                instance_id[:8], reason.value, event.duration_ms
            )
            
            if self._on_promotion:
                self._on_promotion(event)
        
        except Exception as e:
            event.success = False
            event.error = str(e)
            event.duration_ms = (time.time() - start_time) * 1000
            logger.error("Promotion failed: %s", e)
        
        self._promotion_history.append(event)
        return event
    
    def auto_failover_check(self) -> Optional[PromotionEvent]:
        """Check and perform auto-failover if needed."""
        if not self._auto_failover:
            return None
        
        if self.check_primary_health():
            return None
        
        logger.warning("Primary unhealthy, initiating auto-failover")
        
        best_shadow = self.get_best_shadow()
        if not best_shadow:
            logger.error("No healthy shadow available for failover")
            return None
        
        return self.promote(
            best_shadow.instance_id,
            PromotionReason.PRIMARY_FAILURE,
            initiated_by="auto_failover",
        )
    
    def set_promotion_callback(
        self,
        callback: Callable[[PromotionEvent], None],
    ) -> None:
        """Set callback for promotion events."""
        self._on_promotion = callback
    
    def set_demotion_callback(
        self,
        callback: Callable[[str], None],
    ) -> None:
        """Set callback for demotion events."""
        self._on_demotion = callback
    
    def get_instance(self, instance_id: str) -> Optional[SystemInstance]:
        """Get instance by ID."""
        return self._instances.get(instance_id)
    
    def get_primary(self) -> Optional[SystemInstance]:
        """Get current primary instance."""
        if self._primary_id:
            return self._instances.get(self._primary_id)
        return None
    
    def get_shadows(self) -> List[SystemInstance]:
        """Get all shadow instances."""
        return [
            inst for inst in self._instances.values()
            if inst.role == SystemRole.SHADOW
        ]
    
    def get_promotion_history(self, limit: int = 10) -> List[PromotionEvent]:
        """Get recent promotion history."""
        return self._promotion_history[-limit:]
    
    def get_status(self) -> Dict[str, Any]:
        """Get manager status."""
        primary = self.get_primary()
        shadows = self.get_shadows()
        
        return {
            "primary": primary.to_dict() if primary else None,
            "primary_healthy": self.check_primary_health(),
            "shadow_count": len(shadows),
            "healthy_shadows": sum(1 for s in shadows if s.is_healthy()),
            "auto_failover": self._auto_failover,
            "promotion_count": len(self._promotion_history),
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get manager statistics."""
        successful_promotions = sum(
            1 for e in self._promotion_history if e.success
        )
        
        return {
            "total_instances": len(self._instances),
            "total_promotions": len(self._promotion_history),
            "successful_promotions": successful_promotions,
            "auto_failover_enabled": self._auto_failover,
            "heartbeat_timeout": self._heartbeat_timeout,
        }


# Singleton instance
_shadow_manager: Optional[ShadowPromotionManager] = None
_shadow_manager_lock = threading.Lock()


def get_shadow_manager() -> ShadowPromotionManager:
    """Get the singleton shadow promotion manager."""
    global _shadow_manager
    if _shadow_manager is None:
        with _shadow_manager_lock:
            if _shadow_manager is None:
                _shadow_manager = ShadowPromotionManager()
    return _shadow_manager
