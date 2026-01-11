"""
Intent-Based Actions - Inter-system message schemas per MERID Four-System Architecture

No system issues commands anymore - only INTENTS.

This means:
- Everything can be simulated first
- Everything can be vetoed
- Everything leaves an audit trail

This is how you avoid "one bad agent nuked the treasury."

Intent Flow:
1. System creates Intent
2. Intent is validated against contracts
3. Intent enters simulation (optional)
4. Intent requires approval (based on type)
5. Intent is executed or rejected
6. Full audit trail recorded
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Any

from contracts.system_contracts import SystemID, get_contract_enforcer, ContractViolationError
from utils.logger import get_logger

logger = get_logger("contracts.intents")


class IntentType(Enum):
    """Types of intents that can be issued."""
    
    ANALYZE = "analyze"
    SIGNAL = "signal"
    PROPOSE = "propose"
    VOTE = "vote"
    
    TRADE = "trade"
    HEDGE = "hedge"
    CLOSE_POSITION = "close_position"
    MODIFY_ORDER = "modify_order"
    
    ALLOCATE = "allocate"
    RETURN_CAPITAL = "return_capital"
    DEPLOY_DEFI = "deploy_defi"
    WITHDRAW_DEFI = "withdraw_defi"
    
    LOCKDOWN = "lockdown"
    RELEASE_LOCKDOWN = "release_lockdown"
    MODIFY_PARAMETER = "modify_parameter"
    VETO = "veto"
    EMERGENCY = "emergency"


class IntentStatus(Enum):
    """Status of an intent."""
    CREATED = "created"
    VALIDATING = "validating"
    SIMULATING = "simulating"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    EXECUTED = "executed"
    REJECTED = "rejected"
    VETOED = "vetoed"
    FAILED = "failed"
    EXPIRED = "expired"


class IntentPriority(Enum):
    """Priority levels for intents."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3
    EMERGENCY = 4


@dataclass
class IntentPayload:
    """Structured payload for an intent."""
    action: str
    parameters: Dict[str, Any]
    target_system: Optional[SystemID] = None
    amount_usd: Optional[float] = None
    symbol: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "parameters": self.parameters,
            "target_system": self.target_system.value if self.target_system else None,
            "amount_usd": self.amount_usd,
            "symbol": self.symbol,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> IntentPayload:
        target = data.get("target_system")
        return cls(
            action=data["action"],
            parameters=data.get("parameters", {}),
            target_system=SystemID(target) if target else None,
            amount_usd=data.get("amount_usd"),
            symbol=data.get("symbol"),
        )


@dataclass
class SimulationResult:
    """Result of simulating an intent."""
    success: bool
    predicted_outcome: Dict[str, Any]
    risk_score: float
    warnings: List[str]
    estimated_cost_usd: float
    estimated_duration_ms: float
    side_effects: List[str]
    
    def is_safe(self, max_risk: float = 0.7) -> bool:
        return self.success and self.risk_score <= max_risk


@dataclass
class Intent:
    """
    An intent represents a desired action that must be validated,
    optionally simulated, and approved before execution.
    
    This is the fundamental unit of inter-system communication.
    """
    
    intent_id: str
    intent_type: IntentType
    source_system: SystemID
    payload: IntentPayload
    
    priority: IntentPriority = IntentPriority.NORMAL
    status: IntentStatus = IntentStatus.CREATED
    
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    
    requires_simulation: bool = True
    simulation_result: Optional[SimulationResult] = None
    
    requires_approval: bool = True
    approval_threshold: int = 1
    approvals: List[str] = field(default_factory=list)
    rejections: List[str] = field(default_factory=list)
    veto_by: Optional[str] = None
    
    executed_at: Optional[float] = None
    execution_result: Optional[Dict[str, Any]] = None
    
    parent_intent_id: Optional[str] = None
    child_intent_ids: List[str] = field(default_factory=list)
    
    audit_trail: List[Dict[str, Any]] = field(default_factory=list)
    
    def __post_init__(self) -> None:
        if self.expires_at is None:
            ttl = self._get_default_ttl()
            self.expires_at = self.created_at + ttl
        self._record_audit("created", {"status": self.status.value})
    
    def _get_default_ttl(self) -> float:
        """Get default TTL based on intent type."""
        ttls = {
            IntentType.EMERGENCY: 60.0,
            IntentType.TRADE: 300.0,
            IntentType.ALLOCATE: 3600.0,
            IntentType.DEPLOY_DEFI: 86400.0,
            IntentType.MODIFY_PARAMETER: 86400.0,
        }
        return ttls.get(self.intent_type, 3600.0)
    
    def is_expired(self) -> bool:
        """Check if intent has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    def compute_hash(self) -> str:
        """Compute deterministic hash of intent."""
        canonical = {
            "intent_type": self.intent_type.value,
            "source_system": self.source_system.value,
            "payload": self.payload.to_dict(),
            "created_at": self.created_at,
        }
        canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode()).hexdigest()
    
    def _record_audit(self, event: str, details: Dict[str, Any]) -> None:
        """Record an audit event."""
        self.audit_trail.append({
            "timestamp": time.time(),
            "event": event,
            "details": details,
        })
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize intent to dictionary."""
        return {
            "intent_id": self.intent_id,
            "intent_type": self.intent_type.value,
            "source_system": self.source_system.value,
            "payload": self.payload.to_dict(),
            "priority": self.priority.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "requires_simulation": self.requires_simulation,
            "requires_approval": self.requires_approval,
            "approval_threshold": self.approval_threshold,
            "approvals": self.approvals,
            "rejections": self.rejections,
            "veto_by": self.veto_by,
            "executed_at": self.executed_at,
            "hash": self.compute_hash(),
        }


INTENT_APPROVAL_THRESHOLDS: Dict[IntentType, int] = {
    IntentType.ANALYZE: 0,
    IntentType.SIGNAL: 0,
    IntentType.PROPOSE: 1,
    IntentType.VOTE: 0,
    IntentType.TRADE: 2,
    IntentType.HEDGE: 1,
    IntentType.CLOSE_POSITION: 1,
    IntentType.MODIFY_ORDER: 1,
    IntentType.ALLOCATE: 2,
    IntentType.RETURN_CAPITAL: 1,
    IntentType.DEPLOY_DEFI: 4,
    IntentType.WITHDRAW_DEFI: 2,
    IntentType.LOCKDOWN: 2,
    IntentType.RELEASE_LOCKDOWN: 3,
    IntentType.MODIFY_PARAMETER: 3,
    IntentType.VETO: 1,
    IntentType.EMERGENCY: 2,
}

INTENT_REQUIRES_SIMULATION: Dict[IntentType, bool] = {
    IntentType.ANALYZE: False,
    IntentType.SIGNAL: False,
    IntentType.PROPOSE: False,
    IntentType.VOTE: False,
    IntentType.TRADE: True,
    IntentType.HEDGE: True,
    IntentType.CLOSE_POSITION: True,
    IntentType.MODIFY_ORDER: False,
    IntentType.ALLOCATE: True,
    IntentType.RETURN_CAPITAL: False,
    IntentType.DEPLOY_DEFI: True,
    IntentType.WITHDRAW_DEFI: True,
    IntentType.LOCKDOWN: False,
    IntentType.RELEASE_LOCKDOWN: False,
    IntentType.MODIFY_PARAMETER: True,
    IntentType.VETO: False,
    IntentType.EMERGENCY: False,
}


class IntentProcessor:
    """
    Processes intents through the validation -> simulation -> approval -> execution pipeline.
    """
    
    def __init__(self) -> None:
        self._pending_intents: Dict[str, Intent] = {}
        self._processed_intents: List[Intent] = []
        
        self._simulators: Dict[IntentType, Callable[[Intent], SimulationResult]] = {}
        self._executors: Dict[IntentType, Callable[[Intent], Dict[str, Any]]] = {}
        
        self._veto_authorities: List[str] = ["skeptic-agent-01", "governance"]
        
        self._logger = get_logger("contracts.intents.processor")
    
    def create_intent(
        self,
        intent_type: IntentType,
        source_system: SystemID,
        payload: IntentPayload,
        priority: IntentPriority = IntentPriority.NORMAL,
        parent_intent_id: Optional[str] = None,
    ) -> Intent:
        """
        Create a new intent.
        
        Args:
            intent_type: Type of intent
            source_system: System creating the intent
            payload: Intent payload
            priority: Priority level
            parent_intent_id: Parent intent if this is derived
            
        Returns:
            Created Intent
        """
        intent = Intent(
            intent_id=str(uuid.uuid4()),
            intent_type=intent_type,
            source_system=source_system,
            payload=payload,
            priority=priority,
            requires_simulation=INTENT_REQUIRES_SIMULATION.get(intent_type, True),
            requires_approval=INTENT_APPROVAL_THRESHOLDS.get(intent_type, 1) > 0,
            approval_threshold=INTENT_APPROVAL_THRESHOLDS.get(intent_type, 1),
            parent_intent_id=parent_intent_id,
        )
        
        self._pending_intents[intent.intent_id] = intent
        
        self._logger.info(
            "Intent created: %s %s from %s",
            intent.intent_id[:8], intent_type.value, source_system.value
        )
        
        return intent
    
    async def process_intent(self, intent: Intent) -> Intent:
        """
        Process an intent through the full pipeline.
        
        Args:
            intent: Intent to process
            
        Returns:
            Processed intent with final status
        """
        try:
            intent.status = IntentStatus.VALIDATING
            intent._record_audit("validating", {})
            
            self._validate_intent(intent)
            
            if intent.requires_simulation:
                intent.status = IntentStatus.SIMULATING
                intent._record_audit("simulating", {})
                
                simulation = await self._simulate_intent(intent)
                intent.simulation_result = simulation
                
                if not simulation.is_safe():
                    intent.status = IntentStatus.REJECTED
                    intent._record_audit("rejected", {
                        "reason": "simulation_unsafe",
                        "risk_score": simulation.risk_score,
                    })
                    return intent
            
            if intent.requires_approval:
                intent.status = IntentStatus.AWAITING_APPROVAL
                intent._record_audit("awaiting_approval", {
                    "threshold": intent.approval_threshold,
                })
                return intent
            
            return await self._execute_intent(intent)
            
        except ContractViolationError as e:
            intent.status = IntentStatus.REJECTED
            intent._record_audit("rejected", {
                "reason": "contract_violation",
                "violation": str(e.violation),
            })
            return intent
        
        except Exception as e:
            intent.status = IntentStatus.FAILED
            intent._record_audit("failed", {"error": str(e)})
            self._logger.error("Intent processing failed: %s", e)
            return intent
    
    def approve_intent(
        self,
        intent_id: str,
        approver_id: str,
    ) -> bool:
        """
        Approve an intent.
        
        Args:
            intent_id: Intent to approve
            approver_id: Entity approving
            
        Returns:
            True if approval recorded
        """
        if intent_id not in self._pending_intents:
            return False
        
        intent = self._pending_intents[intent_id]
        
        if intent.status != IntentStatus.AWAITING_APPROVAL:
            return False
        
        if intent.is_expired():
            intent.status = IntentStatus.EXPIRED
            return False
        
        if approver_id in intent.approvals:
            return False
        
        intent.approvals.append(approver_id)
        intent._record_audit("approved_by", {"approver": approver_id})
        
        if len(intent.approvals) >= intent.approval_threshold:
            intent.status = IntentStatus.APPROVED
            intent._record_audit("fully_approved", {
                "approvals": intent.approvals,
            })
        
        return True
    
    def reject_intent(
        self,
        intent_id: str,
        rejector_id: str,
        reason: str = "",
    ) -> bool:
        """Reject an intent."""
        if intent_id not in self._pending_intents:
            return False
        
        intent = self._pending_intents[intent_id]
        
        if intent.status in (IntentStatus.EXECUTED, IntentStatus.REJECTED, IntentStatus.VETOED):
            return False
        
        intent.rejections.append(rejector_id)
        intent.status = IntentStatus.REJECTED
        intent._record_audit("rejected_by", {
            "rejector": rejector_id,
            "reason": reason,
        })
        
        return True
    
    def veto_intent(
        self,
        intent_id: str,
        vetoer_id: str,
        reason: str = "",
    ) -> bool:
        """
        Veto an intent (requires veto authority).
        
        Args:
            intent_id: Intent to veto
            vetoer_id: Entity vetoing
            reason: Veto reason
            
        Returns:
            True if veto applied
        """
        if vetoer_id not in self._veto_authorities:
            self._logger.warning(
                "Veto attempt by non-authority: %s",
                vetoer_id
            )
            return False
        
        if intent_id not in self._pending_intents:
            return False
        
        intent = self._pending_intents[intent_id]
        
        if intent.status in (IntentStatus.EXECUTED, IntentStatus.VETOED):
            return False
        
        intent.veto_by = vetoer_id
        intent.status = IntentStatus.VETOED
        intent._record_audit("vetoed", {
            "vetoer": vetoer_id,
            "reason": reason,
        })
        
        self._logger.warning(
            "Intent %s VETOED by %s: %s",
            intent_id[:8], vetoer_id, reason
        )
        
        return True
    
    async def execute_approved_intent(self, intent_id: str) -> Optional[Intent]:
        """Execute an approved intent."""
        if intent_id not in self._pending_intents:
            return None
        
        intent = self._pending_intents[intent_id]
        
        if intent.status != IntentStatus.APPROVED:
            return None
        
        return await self._execute_intent(intent)
    
    def get_intent(self, intent_id: str) -> Optional[Intent]:
        """Get an intent by ID."""
        return self._pending_intents.get(intent_id)
    
    def get_pending_intents(
        self,
        system: Optional[SystemID] = None,
        intent_type: Optional[IntentType] = None,
    ) -> List[Intent]:
        """Get pending intents with optional filters."""
        intents = list(self._pending_intents.values())
        
        if system:
            intents = [i for i in intents if i.source_system == system]
        
        if intent_type:
            intents = [i for i in intents if i.intent_type == intent_type]
        
        return intents
    
    def register_simulator(
        self,
        intent_type: IntentType,
        simulator: Callable[[Intent], SimulationResult],
    ) -> None:
        """Register a simulator for an intent type."""
        self._simulators[intent_type] = simulator
    
    def register_executor(
        self,
        intent_type: IntentType,
        executor: Callable[[Intent], Dict[str, Any]],
    ) -> None:
        """Register an executor for an intent type."""
        self._executors[intent_type] = executor
    
    def _validate_intent(self, intent: Intent) -> None:
        """Validate intent against system contracts."""
        enforcer = get_contract_enforcer()
        
        action = intent.payload.action
        enforcer.check_action(intent.source_system, action)
        
        if intent.payload.target_system:
            enforcer.check_cross_system_request(
                intent.source_system,
                intent.payload.target_system,
                action,
            )
        
        if intent.payload.amount_usd:
            enforcer.check_capital_authority(
                intent.source_system,
                intent.payload.amount_usd,
            )
    
    async def _simulate_intent(self, intent: Intent) -> SimulationResult:
        """Simulate intent execution."""
        if intent.intent_type in self._simulators:
            return self._simulators[intent.intent_type](intent)
        
        return SimulationResult(
            success=True,
            predicted_outcome={"simulated": True},
            risk_score=0.3,
            warnings=[],
            estimated_cost_usd=0.0,
            estimated_duration_ms=100.0,
            side_effects=[],
        )
    
    async def _execute_intent(self, intent: Intent) -> Intent:
        """Execute the intent."""
        intent.status = IntentStatus.EXECUTING
        intent._record_audit("executing", {})
        
        try:
            if intent.intent_type in self._executors:
                result = self._executors[intent.intent_type](intent)
            else:
                result = {"executed": True, "default_executor": True}
            
            intent.execution_result = result
            intent.executed_at = time.time()
            intent.status = IntentStatus.EXECUTED
            intent._record_audit("executed", {"result": result})
            
            del self._pending_intents[intent.intent_id]
            self._processed_intents.append(intent)
            
            if len(self._processed_intents) > 1000:
                self._processed_intents = self._processed_intents[-500:]
            
            self._logger.info(
                "Intent %s executed successfully",
                intent.intent_id[:8]
            )
            
        except Exception as e:
            intent.status = IntentStatus.FAILED
            intent._record_audit("execution_failed", {"error": str(e)})
            self._logger.error("Intent execution failed: %s", e)
        
        return intent


_intent_processor: Optional[IntentProcessor] = None


def get_intent_processor() -> IntentProcessor:
    """Get or create global intent processor."""
    global _intent_processor
    if _intent_processor is None:
        _intent_processor = IntentProcessor()
    return _intent_processor
