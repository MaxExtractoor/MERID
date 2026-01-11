"""
MERID Recovery Module

Disaster recovery, failover, and cold-start capabilities.

Part of MERID-GOV (Layer 0 - Constitutional Foundation)

Components:
- Disaster Recovery: Emergency halts, agent quarantine
- Shadow Promotion: Failover control, primary/shadow management
"""

from recovery.disaster_recovery import (
    get_disaster_recovery,
    DisasterRecoveryManager,
    SystemState,
    RecoveryMode,
    ComponentStatus,
    RecoveryPoint,
    ComponentHealth,
    AnomalyEvent,
)
from recovery.shadow_promotion import (
    ShadowPromotionManager,
    SystemInstance,
    SystemRole,
    PromotionEvent,
    PromotionReason,
    get_shadow_manager,
)

__all__ = [
    # Disaster Recovery
    "get_disaster_recovery",
    "DisasterRecoveryManager",
    "SystemState",
    "RecoveryMode",
    "ComponentStatus",
    "RecoveryPoint",
    "ComponentHealth",
    "AnomalyEvent",
    # Shadow Promotion
    "ShadowPromotionManager",
    "SystemInstance",
    "SystemRole",
    "PromotionEvent",
    "PromotionReason",
    "get_shadow_manager",
]
