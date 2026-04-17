"""
Escalation Policies.

Defines escalation paths for alerts that require attention.

Version: 1.0.0
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import get_logger

logger = get_logger("notifications.escalation")


class EscalationLevel(Enum):
    """Escalation levels."""
    L1 = "l1"  # First responder
    L2 = "l2"  # Senior/specialist
    L3 = "l3"  # Management
    L4 = "l4"  # Executive


@dataclass
class EscalationStep:
    """A single step in an escalation policy."""
    level: EscalationLevel
    delay_minutes: float  # Minutes before escalating to this level
    
    # Contacts
    contacts: List[str] = field(default_factory=list)
    channels: List[str] = field(default_factory=list)
    
    # Actions
    auto_actions: List[str] = field(default_factory=list)  # e.g., "pause_trading"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level.value,
            "delay_minutes": self.delay_minutes,
            "contacts": self.contacts,
            "channels": self.channels,
            "auto_actions": self.auto_actions,
        }


@dataclass
class EscalationPolicy:
    """An escalation policy definition."""
    policy_id: str
    name: str
    description: str = ""
    
    # Steps
    steps: List[EscalationStep] = field(default_factory=list)
    
    # Applicable severities
    applicable_severities: List[str] = field(default_factory=lambda: ["critical"])
    
    # State
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    
    def get_step_for_time(self, elapsed_minutes: float) -> Optional[EscalationStep]:
        """Get the appropriate escalation step for elapsed time."""
        current_step = None
        for step in sorted(self.steps, key=lambda s: s.delay_minutes):
            if elapsed_minutes >= step.delay_minutes:
                current_step = step
        return current_step
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "applicable_severities": self.applicable_severities,
            "enabled": self.enabled,
        }


@dataclass
class ActiveEscalation:
    """An active escalation in progress."""
    escalation_id: str
    policy_id: str
    alert_id: str
    alert_data: Dict[str, Any]
    
    # State
    current_level: EscalationLevel = EscalationLevel.L1
    started_at: float = field(default_factory=time.time)
    acknowledged_at: Optional[float] = None
    acknowledged_by: Optional[str] = None
    resolved_at: Optional[float] = None
    resolved_by: Optional[str] = None
    
    # History
    notifications_sent: List[Dict[str, Any]] = field(default_factory=list)
    actions_taken: List[Dict[str, Any]] = field(default_factory=list)
    
    def elapsed_minutes(self) -> float:
        """Minutes since escalation started."""
        return (time.time() - self.started_at) / 60
    
    def is_active(self) -> bool:
        """Check if escalation is still active."""
        return self.resolved_at is None
    
    def acknowledge(self, by: str) -> None:
        """Acknowledge the escalation."""
        self.acknowledged_at = time.time()
        self.acknowledged_by = by
    
    def resolve(self, by: str) -> None:
        """Resolve the escalation."""
        self.resolved_at = time.time()
        self.resolved_by = by
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "escalation_id": self.escalation_id,
            "policy_id": self.policy_id,
            "alert_id": self.alert_id,
            "current_level": self.current_level.value,
            "started_at": self.started_at,
            "elapsed_minutes": self.elapsed_minutes(),
            "acknowledged_at": self.acknowledged_at,
            "acknowledged_by": self.acknowledged_by,
            "resolved_at": self.resolved_at,
            "resolved_by": self.resolved_by,
            "is_active": self.is_active(),
            "notifications_sent": len(self.notifications_sent),
            "actions_taken": self.actions_taken,
        }


class EscalationManager:
    """
    Manages escalation policies and active escalations.
    
    Features:
    - Policy definition
    - Automatic escalation progression
    - Acknowledgment tracking
    - Auto-actions on escalation
    """
    
    def __init__(self):
        self.logger = get_logger("notifications.escalation")
        
        # Policies
        self._policies: Dict[str, EscalationPolicy] = {}
        
        # Active escalations
        self._active: Dict[str, ActiveEscalation] = {}
        
        # History
        self._history: List[ActiveEscalation] = []
        self._max_history: int = 1000
        
        # Initialize default policies
        self._init_default_policies()
    
    def _init_default_policies(self) -> None:
        """Initialize default escalation policies."""
        # Critical system alert policy
        self.add_policy(EscalationPolicy(
            policy_id="critical_system",
            name="Critical System Alert",
            description="Escalation for critical system issues",
            applicable_severities=["critical"],
            steps=[
                EscalationStep(
                    level=EscalationLevel.L1,
                    delay_minutes=0,
                    channels=["push", "email"],
                    auto_actions=[],
                ),
                EscalationStep(
                    level=EscalationLevel.L2,
                    delay_minutes=5,
                    channels=["push", "email", "sms"],
                    auto_actions=["pause_trading"],
                ),
                EscalationStep(
                    level=EscalationLevel.L3,
                    delay_minutes=15,
                    channels=["push", "email", "sms", "webhook"],
                    auto_actions=["emergency_lockdown"],
                ),
            ],
        ))
        
        # High risk alert policy
        self.add_policy(EscalationPolicy(
            policy_id="high_risk",
            name="High Risk Alert",
            description="Escalation for high risk situations",
            applicable_severities=["error", "critical"],
            steps=[
                EscalationStep(
                    level=EscalationLevel.L1,
                    delay_minutes=0,
                    channels=["push"],
                ),
                EscalationStep(
                    level=EscalationLevel.L2,
                    delay_minutes=10,
                    channels=["push", "email"],
                    auto_actions=["reduce_exposure"],
                ),
            ],
        ))
        
        # Standard alert policy
        self.add_policy(EscalationPolicy(
            policy_id="standard",
            name="Standard Alert",
            description="Standard escalation for warnings",
            applicable_severities=["warning"],
            steps=[
                EscalationStep(
                    level=EscalationLevel.L1,
                    delay_minutes=0,
                    channels=["push"],
                ),
                EscalationStep(
                    level=EscalationLevel.L2,
                    delay_minutes=30,
                    channels=["push", "email"],
                ),
            ],
        ))
    
    def add_policy(self, policy: EscalationPolicy) -> None:
        """Add an escalation policy."""
        self._policies[policy.policy_id] = policy
        self.logger.info(f"Added escalation policy: {policy.name}")
    
    def remove_policy(self, policy_id: str) -> bool:
        """Remove an escalation policy."""
        if policy_id in self._policies:
            del self._policies[policy_id]
            return True
        return False
    
    def get_policy_for_severity(self, severity: str) -> Optional[EscalationPolicy]:
        """Get the appropriate policy for a severity level."""
        for policy in self._policies.values():
            if policy.enabled and severity in policy.applicable_severities:
                return policy
        return None
    
    def start_escalation(
        self,
        alert_id: str,
        severity: str,
        alert_data: Dict[str, Any],
        policy_id: Optional[str] = None,
    ) -> Optional[str]:
        """Start an escalation for an alert."""
        import uuid
        
        # Get policy
        if policy_id:
            policy = self._policies.get(policy_id)
        else:
            policy = self.get_policy_for_severity(severity)
        
        if not policy:
            self.logger.debug(f"No escalation policy for severity: {severity}")
            return None
        
        escalation_id = f"esc_{uuid.uuid4().hex[:12]}"
        
        escalation = ActiveEscalation(
            escalation_id=escalation_id,
            policy_id=policy.policy_id,
            alert_id=alert_id,
            alert_data=alert_data,
        )
        
        self._active[escalation_id] = escalation
        self.logger.warning(f"Started escalation: {escalation_id} for alert {alert_id}")
        
        return escalation_id
    
    def process_escalations(self) -> List[Dict[str, Any]]:
        """Process all active escalations and return actions to take."""
        actions = []
        
        for escalation in self._active.values():
            if not escalation.is_active():
                continue
            
            # Skip if acknowledged
            if escalation.acknowledged_at:
                continue
            
            policy = self._policies.get(escalation.policy_id)
            if not policy:
                continue
            
            # Get current step
            step = policy.get_step_for_time(escalation.elapsed_minutes())
            if not step:
                continue
            
            # Check if we need to escalate
            if step.level != escalation.current_level:
                escalation.current_level = step.level
                self.logger.warning(
                    f"Escalation {escalation.escalation_id} escalated to {step.level.value}"
                )
                
                # Record notification
                escalation.notifications_sent.append({
                    "level": step.level.value,
                    "channels": step.channels,
                    "timestamp": time.time(),
                })
                
                # Return actions to take
                for action in step.auto_actions:
                    action_record = {
                        "escalation_id": escalation.escalation_id,
                        "action": action,
                        "level": step.level.value,
                        "timestamp": time.time(),
                    }
                    actions.append(action_record)
                    escalation.actions_taken.append(action_record)
                
                # Return notification action
                actions.append({
                    "escalation_id": escalation.escalation_id,
                    "action": "notify",
                    "channels": step.channels,
                    "contacts": step.contacts,
                    "alert_data": escalation.alert_data,
                })
        
        return actions
    
    def acknowledge(self, escalation_id: str, by: str) -> bool:
        """Acknowledge an escalation."""
        escalation = self._active.get(escalation_id)
        if not escalation:
            return False
        
        escalation.acknowledge(by)
        self.logger.info(f"Escalation {escalation_id} acknowledged by {by}")
        return True
    
    def resolve(self, escalation_id: str, by: str) -> bool:
        """Resolve an escalation."""
        escalation = self._active.get(escalation_id)
        if not escalation:
            return False
        
        escalation.resolve(by)
        
        # Move to history
        self._history.append(escalation)
        del self._active[escalation_id]
        
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        
        self.logger.info(f"Escalation {escalation_id} resolved by {by}")
        return True
    
    def get_active_escalations(self) -> List[ActiveEscalation]:
        """Get all active escalations."""
        return list(self._active.values())
    
    def get_escalation(self, escalation_id: str) -> Optional[ActiveEscalation]:
        """Get an escalation by ID."""
        return self._active.get(escalation_id)
    
    def get_status(self) -> Dict[str, Any]:
        """Get escalation manager status."""
        return {
            "policies_count": len(self._policies),
            "active_escalations": len(self._active),
            "history_count": len(self._history),
            "policies": [p.to_dict() for p in self._policies.values()],
            "active": [e.to_dict() for e in self._active.values()],
        }


# Singleton
_escalation_manager: Optional[EscalationManager] = None
_escalation_manager_lock = threading.Lock()


def get_escalation_manager() -> EscalationManager:
    """Get or create the Escalation Manager singleton."""
    global _escalation_manager
    if _escalation_manager is None:
        with _escalation_manager_lock:
            if _escalation_manager is None:
                _escalation_manager = EscalationManager()
    return _escalation_manager
