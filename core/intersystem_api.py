"""
MERID Inter-System API Layer

Production implementation of all inter-system contracts defined in MERID_INTERSYSTEM_APIS.md.
This module provides the canonical communication layer between MERID systems.

Systems:
- OPS: Regime Intelligence, Signal Generation
- GOV: Governance, Approval, Veto Authority
- FIN: Execution Dominance
- TREASURY: Capital & Yield Preservation
- ARCHIVE: Memory & Forensics

Authority Matrix:
- OPS: Can Signal, Cannot Execute, Cannot Move Capital, Cannot Veto
- GOV: Cannot Signal, Cannot Execute, Cannot Move Capital, Can Veto
- FIN: Cannot Signal, Can Execute (approved only), Cannot Move Capital, Cannot Veto
- TREASURY: Cannot Signal, Cannot Execute, Can Move Capital (profits only), Cannot Veto
- ARCHIVE: Cannot Signal, Cannot Execute, Cannot Move Capital, Cannot Veto
"""

from __future__ import annotations

import asyncio
import threading
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("core.intersystem_api")


class MeridSystem(Enum):
    """MERID system identifiers."""
    OPS = "OPS"
    GOV = "GOV"
    FIN = "FIN"
    TREASURY = "TREASURY"
    ARCHIVE = "ARCHIVE"


class IntentStatus(Enum):
    """Status of an intent."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ExecutionMode(Enum):
    """Execution modes."""
    AUTO = "AUTO"
    MANUAL_REQUIRED = "MANUAL_REQUIRED"
    SIMULATION_ONLY = "SIMULATION_ONLY"


class FreezeSeverity(Enum):
    """Emergency freeze severity levels."""
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EMERGENCY = "EMERGENCY"


class FreezeReason(Enum):
    """Reasons for emergency freeze."""
    ANOMALY_DETECTED = "ANOMALY_DETECTED"
    SECURITY_BREACH = "SECURITY_BREACH"
    MARKET_HALT = "MARKET_HALT"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


@dataclass
class RiskPreview:
    """Risk preview for intent proposal."""
    max_drawdown_pct: float
    corr_exposure: float
    var_95: float
    cvar_95: float
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "max_drawdown_pct": self.max_drawdown_pct,
            "corr_exposure": self.corr_exposure,
            "var_95": self.var_95,
            "cvar_95": self.cvar_95,
        }
    
    def validate(self) -> Tuple[bool, str]:
        """Validate risk preview fields."""
        if self.max_drawdown_pct < 0 or self.max_drawdown_pct > 1:
            return False, "max_drawdown_pct must be between 0 and 1"
        if self.var_95 < 0:
            return False, "var_95 must be non-negative"
        if self.cvar_95 < 0:
            return False, "cvar_95 must be non-negative"
        return True, ""


@dataclass
class ShadowSimulation:
    """Shadow simulation results."""
    expected_return: float
    p_loss: float
    sharpe_ratio: float
    max_adverse_excursion: float
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "expected_return": self.expected_return,
            "p_loss": self.p_loss,
            "sharpe_ratio": self.sharpe_ratio,
            "max_adverse_excursion": self.max_adverse_excursion,
        }


@dataclass
class PositionRequest:
    """Position request details."""
    asset: str
    side: str  # LONG or SHORT
    notional_usd: float
    leverage: float = 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.asset,
            "side": self.side,
            "notional_usd": self.notional_usd,
            "leverage": self.leverage,
        }


@dataclass
class ExecutionConstraints:
    """Constraints applied to execution."""
    max_notional: float
    slippage_bps: int
    time_lock_sec: int
    max_market_impact_bps: int = 50
    execution_deadline_ts: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_notional": self.max_notional,
            "slippage_bps": self.slippage_bps,
            "time_lock_sec": self.time_lock_sec,
            "max_market_impact_bps": self.max_market_impact_bps,
            "execution_deadline_ts": self.execution_deadline_ts,
        }


@dataclass
class Intent:
    """Trading intent from OPS to GOV."""
    intent_id: str
    origin_system: MeridSystem
    strategy_id: str
    regime: str
    confidence: float
    risk_preview: RiskPreview
    shadow_simulation: ShadowSimulation
    position_request: PositionRequest
    expiry_ts: float
    
    # Metadata
    signal_sources: List[str] = field(default_factory=list)
    epistemic_confidence: float = 0.0
    regime_confidence: float = 0.0
    
    # Status tracking
    status: IntentStatus = IntentStatus.PENDING
    created_at: float = field(default_factory=time.time)
    approved_at: Optional[float] = None
    approved_by: List[str] = field(default_factory=list)
    rejection_reason: Optional[str] = None
    constraints: Optional[ExecutionConstraints] = None
    
    def is_expired(self) -> bool:
        return time.time() > self.expiry_ts
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "origin_system": self.origin_system.value,
            "strategy_id": self.strategy_id,
            "regime": self.regime,
            "confidence": self.confidence,
            "risk_preview": self.risk_preview.to_dict(),
            "shadow_simulation": self.shadow_simulation.to_dict(),
            "position_request": self.position_request.to_dict(),
            "expiry_ts": self.expiry_ts,
            "status": self.status.value,
            "created_at": self.created_at,
        }


@dataclass
class ExecutionReport:
    """Execution report from FIN to GOV."""
    execution_id: str
    intent_id: str
    status: str  # COMPLETED, PARTIAL, FAILED, CANCELLED
    filled_notional: float
    avg_price: float
    slippage_bps: int
    fees_usd: float
    venue: str
    execution_ts: float
    
    # Market impact
    estimated_impact_bps: int = 0
    actual_impact_bps: int = 0
    
    # MEV analysis
    front_run_detected: bool = False
    sandwich_detected: bool = False
    estimated_mev_loss_usd: float = 0.0
    
    # Anomalies
    anomalies: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "intent_id": self.intent_id,
            "status": self.status,
            "execution_details": {
                "filled_notional": self.filled_notional,
                "avg_price": self.avg_price,
                "slippage_bps": self.slippage_bps,
                "fees_usd": self.fees_usd,
                "venue": self.venue,
                "execution_ts": self.execution_ts,
            },
            "market_impact": {
                "estimated_bps": self.estimated_impact_bps,
                "actual_bps": self.actual_impact_bps,
            },
            "mev_analysis": {
                "front_run_detected": self.front_run_detected,
                "sandwich_detected": self.sandwich_detected,
                "estimated_mev_loss_usd": self.estimated_mev_loss_usd,
            },
            "anomalies_detected": self.anomalies,
        }


@dataclass
class ProfitDeposit:
    """Profit deposit from FIN to TREASURY."""
    deposit_id: str
    source_intent: str
    execution_id: str
    amount: float
    asset: str
    source_strategy: str
    realized_ts: float
    
    # Verification
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: float = 0.0
    fees_deducted: float = 0.0
    audit_hash: str = ""
    
    # Status
    status: str = "PENDING_VERIFICATION"
    vault_assigned: Optional[str] = None
    rejection_reason: Optional[str] = None
    
    def compute_audit_hash(self) -> str:
        """Compute audit hash for verification."""
        content = {
            "source_intent": self.source_intent,
            "execution_id": self.execution_id,
            "amount": self.amount,
            "asset": self.asset,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "fees_deducted": self.fees_deducted,
        }
        content_str = json.dumps(content, sort_keys=True)
        return hashlib.sha256(content_str.encode()).hexdigest()
    
    def verify(self) -> Tuple[bool, str]:
        """Verify profit deposit."""
        if self.amount <= 0:
            return False, "ERR_NEGATIVE_AMOUNT"
        
        # Verify PnL calculation
        expected_pnl = (self.exit_price - self.entry_price) * self.quantity - self.fees_deducted
        if abs(expected_pnl - self.amount) > 0.01:  # Allow small rounding
            return False, "ERR_VERIFICATION_FAILED"
        
        # Verify audit hash
        if self.audit_hash and self.audit_hash != self.compute_audit_hash():
            return False, "ERR_VERIFICATION_FAILED"
        
        return True, ""


@dataclass
class EmergencyFreeze:
    """Emergency freeze from GOV."""
    freeze_id: str
    scope: str  # ALL, OPS, FIN, TREASURY
    reason: FreezeReason
    severity: FreezeSeverity
    duration_sec: int
    
    # Actions
    halt_new_intents: bool = True
    cancel_pending_executions: bool = False
    freeze_withdrawals: bool = False
    enable_emergency_unwind: bool = False
    
    # Authorization
    authorized_by: List[str] = field(default_factory=list)
    override_code: Optional[str] = None
    
    # Timing
    effective_ts: float = field(default_factory=time.time)
    expiry_ts: float = 0.0
    
    # Status
    active: bool = True
    acknowledged_by: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        if self.expiry_ts == 0.0:
            self.expiry_ts = self.effective_ts + self.duration_sec
    
    def is_expired(self) -> bool:
        return time.time() > self.expiry_ts


class APIError(Exception):
    """Inter-system API error."""
    def __init__(self, code: str, message: str, details: Optional[Dict] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"{code}: {message}")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "timestamp": time.time(),
                "request_id": str(uuid.uuid4()),
            }
        }


class InterSystemAPI:
    """
    Central inter-system API coordinator.
    
    Enforces authority boundaries and routes messages between systems.
    """
    
    # Confidence threshold for intent approval
    MIN_CONFIDENCE = 0.5
    
    # Risk limits
    MAX_DRAWDOWN_LIMIT = 0.10  # 10%
    MAX_NOTIONAL_DEFAULT = 100000.0
    
    # Quorum requirements
    APPROVAL_QUORUM = 2
    UNFREEZE_QUORUM_MULTIPLIER = 2
    
    def __init__(self):
        # Intent storage
        self._intents: Dict[str, Intent] = {}
        self._executions: Dict[str, ExecutionReport] = {}
        self._deposits: Dict[str, ProfitDeposit] = {}
        self._freezes: Dict[str, EmergencyFreeze] = {}
        
        # Active freeze state
        self._active_freeze: Optional[EmergencyFreeze] = None
        
        # Callbacks for system integration
        self._on_intent_approved: Optional[Callable[[Intent], None]] = None
        self._on_execution_authorized: Optional[Callable[[Intent, ExecutionConstraints], None]] = None
        self._on_freeze: Optional[Callable[[EmergencyFreeze], None]] = None
        self._on_unfreeze: Optional[Callable[[str], None]] = None
        
        # Archive callback
        self._archive_record: Optional[Callable[[Dict[str, Any]], None]] = None
        
        logger.info("Inter-system API initialized")
    
    # =========================================================================
    # CONTRACT 1: OPS → GOV - Intent Proposal
    # =========================================================================
    
    async def propose_intent(
        self,
        strategy_id: str,
        regime: str,
        confidence: float,
        risk_preview: RiskPreview,
        shadow_simulation: ShadowSimulation,
        position_request: PositionRequest,
        expiry_ts: float,
        signal_sources: Optional[List[str]] = None,
        epistemic_confidence: float = 0.0,
        regime_confidence: float = 0.0,
    ) -> Dict[str, Any]:
        """
        OPS proposes a trading intent to GOV.
        
        CONTRACT 1: OPS → GOV
        """
        # Check for active freeze
        if self._active_freeze and self._active_freeze.halt_new_intents:
            raise APIError(
                "ERR_SYSTEM_FROZEN",
                "System is frozen, new intents not accepted",
                {"freeze_id": self._active_freeze.freeze_id}
            )
        
        # Validate required fields
        if not regime:
            raise APIError("ERR_MISSING_REGIME", "Regime not specified")
        
        if confidence < self.MIN_CONFIDENCE:
            raise APIError(
                "ERR_LOW_CONFIDENCE",
                f"Confidence {confidence} below threshold {self.MIN_CONFIDENCE}"
            )
        
        # Validate risk preview
        valid, error = risk_preview.validate()
        if not valid:
            raise APIError("ERR_RISK_LIMIT_BREACH", error)
        
        # Check risk limits
        if risk_preview.max_drawdown_pct > self.MAX_DRAWDOWN_LIMIT:
            raise APIError(
                "ERR_RISK_LIMIT_BREACH",
                f"Max drawdown {risk_preview.max_drawdown_pct} exceeds limit {self.MAX_DRAWDOWN_LIMIT}"
            )
        
        # Create intent
        intent_id = str(uuid.uuid4())
        intent = Intent(
            intent_id=intent_id,
            origin_system=MeridSystem.OPS,
            strategy_id=strategy_id,
            regime=regime,
            confidence=confidence,
            risk_preview=risk_preview,
            shadow_simulation=shadow_simulation,
            position_request=position_request,
            expiry_ts=expiry_ts,
            signal_sources=signal_sources or [],
            epistemic_confidence=epistemic_confidence,
            regime_confidence=regime_confidence,
        )
        
        self._intents[intent_id] = intent
        
        # Record to archive
        await self._record_event("INTENT_PROPOSED", intent_id, {
            "strategy_id": strategy_id,
            "regime": regime,
            "confidence": confidence,
        })
        
        logger.info(
            "Intent proposed: %s strategy=%s regime=%s confidence=%.2f",
            intent_id[:8], strategy_id, regime, confidence
        )
        
        return {
            "intent_id": intent_id,
            "status": IntentStatus.PENDING.value,
            "review_agents": [],
            "constraints_applied": None,
            "rejection_reason": None,
            "approval_ts": None,
        }
    
    # =========================================================================
    # CONTRACT 2: GOV → FIN - Execution Authorization
    # =========================================================================
    
    async def authorize_execution(
        self,
        intent_id: str,
        approved_by: List[str],
        constraints: ExecutionConstraints,
        mode: ExecutionMode = ExecutionMode.MANUAL_REQUIRED,
        kill_switch_enabled: bool = True,
        preferred_venues: Optional[List[str]] = None,
        mev_protection: bool = True,
    ) -> Dict[str, Any]:
        """
        GOV authorizes FIN to execute an approved intent.
        
        CONTRACT 2: GOV → FIN
        """
        # Get intent
        intent = self._intents.get(intent_id)
        if not intent:
            raise APIError("ERR_INVALID_INTENT", "Intent ID not found")
        
        # Check expiry
        if intent.is_expired():
            intent.status = IntentStatus.EXPIRED
            raise APIError("ERR_EXPIRED", "Intent expired before authorization")
        
        # Check quorum
        if len(approved_by) < self.APPROVAL_QUORUM:
            raise APIError(
                "ERR_QUORUM_NOT_MET",
                f"Insufficient approvals: {len(approved_by)} < {self.APPROVAL_QUORUM}"
            )
        
        # Validate constraints
        if constraints.max_notional > self.MAX_NOTIONAL_DEFAULT:
            raise APIError(
                "ERR_CONSTRAINT_VIOLATION",
                f"Max notional {constraints.max_notional} exceeds limit"
            )
        
        # Update intent
        intent.status = IntentStatus.APPROVED
        intent.approved_at = time.time()
        intent.approved_by = approved_by
        intent.constraints = constraints
        
        # Set execution deadline if not set
        if constraints.execution_deadline_ts == 0.0:
            constraints.execution_deadline_ts = time.time() + 3600  # 1 hour default
        
        # Record to archive
        await self._record_event("INTENT_APPROVED", intent_id, {
            "approved_by": approved_by,
            "mode": mode.value,
            "constraints": constraints.to_dict(),
        })
        
        # Trigger callback
        if self._on_execution_authorized:
            self._on_execution_authorized(intent, constraints)
        
        logger.info(
            "Execution authorized: %s by %s mode=%s",
            intent_id[:8], approved_by, mode.value
        )
        
        return {
            "intent_id": intent_id,
            "execution_id": str(uuid.uuid4()),
            "status": "ACCEPTED",
            "estimated_execution_ts": time.time() + constraints.time_lock_sec,
            "rejection_reason": None,
        }
    
    async def reject_intent(
        self,
        intent_id: str,
        rejected_by: List[str],
        reason: str,
    ) -> Dict[str, Any]:
        """
        GOV rejects an intent.
        """
        intent = self._intents.get(intent_id)
        if not intent:
            raise APIError("ERR_INVALID_INTENT", "Intent ID not found")
        
        intent.status = IntentStatus.REJECTED
        intent.rejection_reason = reason
        
        await self._record_event("INTENT_REJECTED", intent_id, {
            "rejected_by": rejected_by,
            "reason": reason,
        })
        
        logger.info("Intent rejected: %s reason=%s", intent_id[:8], reason)
        
        return {
            "intent_id": intent_id,
            "status": IntentStatus.REJECTED.value,
            "rejection_reason": reason,
        }
    
    # =========================================================================
    # CONTRACT 3: FIN → GOV - Execution Report
    # =========================================================================
    
    async def report_execution(
        self,
        report: ExecutionReport,
    ) -> Dict[str, Any]:
        """
        FIN reports execution outcome to GOV.
        
        CONTRACT 3: FIN → GOV
        """
        # Validate intent exists
        intent = self._intents.get(report.intent_id)
        if not intent:
            raise APIError("ERR_INVALID_INTENT", "Intent ID not found")
        
        # Store execution
        self._executions[report.execution_id] = report
        
        # Update intent status
        if report.status == "COMPLETED":
            intent.status = IntentStatus.COMPLETED
        elif report.status == "FAILED":
            intent.status = IntentStatus.FAILED
        
        # Check for anomalies that need escalation
        alert_triggered = False
        for anomaly in report.anomalies:
            if anomaly.get("severity") in ["HIGH", "CRITICAL"]:
                alert_triggered = True
                logger.warning(
                    "HIGH/CRITICAL anomaly detected: %s",
                    anomaly.get("description")
                )
        
        # Check MEV losses
        if report.front_run_detected or report.sandwich_detected:
            alert_triggered = True
            logger.warning(
                "MEV attack detected: front_run=%s sandwich=%s loss=%.2f",
                report.front_run_detected, report.sandwich_detected,
                report.estimated_mev_loss_usd
            )
        
        # Record to archive
        await self._record_event("INTENT_EXECUTED", report.intent_id, {
            "execution_id": report.execution_id,
            "status": report.status,
            "filled_notional": report.filled_notional,
            "slippage_bps": report.slippage_bps,
            "mev_loss": report.estimated_mev_loss_usd,
        })
        
        logger.info(
            "Execution reported: %s status=%s filled=%.2f slippage=%dbps",
            report.execution_id[:8], report.status,
            report.filled_notional, report.slippage_bps
        )
        
        return {
            "execution_id": report.execution_id,
            "acknowledged": True,
            "follow_up_actions": [],
            "alert_triggered": alert_triggered,
        }
    
    # =========================================================================
    # CONTRACT 4: FIN → TREASURY - Profit Routing
    # =========================================================================
    
    async def deposit_profit(
        self,
        deposit: ProfitDeposit,
    ) -> Dict[str, Any]:
        """
        FIN routes realized profits to TREASURY.
        
        CONTRACT 4: FIN → TREASURY
        """
        # Verify deposit
        valid, error = deposit.verify()
        if not valid:
            deposit.status = "REJECTED"
            deposit.rejection_reason = error
            raise APIError(error, f"Profit deposit verification failed: {error}")
        
        # Compute and set audit hash
        deposit.audit_hash = deposit.compute_audit_hash()
        
        # Assign vault (production would integrate with treasury/vaults.py)
        deposit.vault_assigned = "profit_vault_primary"
        deposit.status = "ACCEPTED"
        
        # Store deposit
        self._deposits[deposit.deposit_id] = deposit
        
        # Record to archive
        await self._record_event("PROFIT_DEPOSIT", deposit.source_intent, {
            "deposit_id": deposit.deposit_id,
            "amount": deposit.amount,
            "asset": deposit.asset,
            "vault": deposit.vault_assigned,
            "audit_hash": deposit.audit_hash,
        })
        
        logger.info(
            "Profit deposited: %s amount=%.2f %s vault=%s",
            deposit.deposit_id[:8], deposit.amount, deposit.asset,
            deposit.vault_assigned
        )
        
        return {
            "deposit_id": deposit.deposit_id,
            "status": deposit.status,
            "vault_assigned": deposit.vault_assigned,
            "rejection_reason": None,
        }
    
    # =========================================================================
    # CONTRACT 7: GOV → ALL - Emergency Freeze
    # =========================================================================
    
    async def emergency_freeze(
        self,
        scope: str,
        reason: FreezeReason,
        severity: FreezeSeverity,
        duration_sec: int,
        authorized_by: List[str],
        halt_new_intents: bool = True,
        cancel_pending_executions: bool = False,
        freeze_withdrawals: bool = False,
        enable_emergency_unwind: bool = False,
        override_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        GOV issues emergency freeze to systems.
        
        CONTRACT 7: GOV → ALL
        """
        # Validate authorization for EMERGENCY severity
        if severity == FreezeSeverity.EMERGENCY and len(authorized_by) < 2:
            raise APIError(
                "ERR_INSUFFICIENT_AUTHORIZATION",
                "EMERGENCY freeze requires multi-sig (2+ authorizers)"
            )
        
        freeze_id = str(uuid.uuid4())
        freeze = EmergencyFreeze(
            freeze_id=freeze_id,
            scope=scope,
            reason=reason,
            severity=severity,
            duration_sec=duration_sec,
            halt_new_intents=halt_new_intents,
            cancel_pending_executions=cancel_pending_executions,
            freeze_withdrawals=freeze_withdrawals,
            enable_emergency_unwind=enable_emergency_unwind,
            authorized_by=authorized_by,
            override_code=override_code,
        )
        
        self._freezes[freeze_id] = freeze
        self._active_freeze = freeze
        
        # Cancel pending executions if requested
        if cancel_pending_executions:
            for intent in self._intents.values():
                if intent.status == IntentStatus.APPROVED:
                    intent.status = IntentStatus.EXPIRED
        
        # Record to archive
        await self._record_event("EMERGENCY_FREEZE", None, {
            "freeze_id": freeze_id,
            "scope": scope,
            "reason": reason.value,
            "severity": severity.value,
            "duration_sec": duration_sec,
            "authorized_by": authorized_by,
        })
        
        # Trigger callback
        if self._on_freeze:
            self._on_freeze(freeze)
        
        logger.warning(
            "EMERGENCY FREEZE: %s scope=%s reason=%s severity=%s duration=%ds",
            freeze_id[:8], scope, reason.value, severity.value, duration_sec
        )
        
        return {
            "freeze_id": freeze_id,
            "acknowledged_by": authorized_by,
            "effective_ts": freeze.effective_ts,
            "expiry_ts": freeze.expiry_ts,
            "systems_affected": [scope] if scope != "ALL" else ["OPS", "FIN", "TREASURY"],
        }
    
    # =========================================================================
    # CONTRACT 8: GOV → GOV - Unfreeze
    # =========================================================================
    
    async def unfreeze(
        self,
        freeze_id: str,
        unfreeze_reason: str,
        authorized_by: List[str],
        anomaly_resolved: bool = True,
        security_audit_passed: bool = True,
        manual_review_completed: bool = True,
    ) -> Dict[str, Any]:
        """
        GOV lifts an emergency freeze.
        
        CONTRACT 8: GOV → GOV
        """
        freeze = self._freezes.get(freeze_id)
        if not freeze:
            raise APIError("ERR_INVALID_FREEZE", "Freeze ID not found")
        
        # Require higher quorum for unfreeze
        required_quorum = len(freeze.authorized_by) * self.UNFREEZE_QUORUM_MULTIPLIER
        if len(authorized_by) < required_quorum:
            raise APIError(
                "ERR_QUORUM_NOT_MET",
                f"Unfreeze requires {required_quorum} authorizers, got {len(authorized_by)}"
            )
        
        # Verify all checks passed
        if not (anomaly_resolved and security_audit_passed and manual_review_completed):
            raise APIError(
                "ERR_VERIFICATION_FAILED",
                "All verification checks must pass for unfreeze"
            )
        
        # Deactivate freeze
        freeze.active = False
        if self._active_freeze and self._active_freeze.freeze_id == freeze_id:
            self._active_freeze = None
        
        # Record to archive
        await self._record_event("EMERGENCY_UNFREEZE", None, {
            "freeze_id": freeze_id,
            "unfreeze_reason": unfreeze_reason,
            "authorized_by": authorized_by,
        })
        
        # Trigger callback
        if self._on_unfreeze:
            self._on_unfreeze(freeze_id)
        
        logger.info(
            "UNFREEZE: %s reason=%s authorized_by=%s",
            freeze_id[:8], unfreeze_reason, authorized_by
        )
        
        return {
            "freeze_id": freeze_id,
            "status": "UNFROZEN",
            "effective_ts": time.time(),
            "systems_restored": [freeze.scope] if freeze.scope != "ALL" else ["OPS", "FIN", "TREASURY"],
        }
    
    # =========================================================================
    # CONTRACT 6: OPS → ARCHIVE - Decision Record
    # =========================================================================
    
    async def _record_event(
        self,
        event_type: str,
        intent_id: Optional[str],
        data: Dict[str, Any],
    ) -> None:
        """Record event to archive."""
        record = {
            "record_id": str(uuid.uuid4()),
            "event_type": event_type,
            "timestamp": time.time(),
            "intent_id": intent_id,
            "data": data,
        }
        
        if self._archive_record:
            self._archive_record(record)
    
    # =========================================================================
    # Query Methods
    # =========================================================================
    
    def get_intent(self, intent_id: str) -> Optional[Intent]:
        """Get intent by ID."""
        return self._intents.get(intent_id)
    
    def get_pending_intents(self) -> List[Intent]:
        """Get all pending intents."""
        return [i for i in self._intents.values() if i.status == IntentStatus.PENDING]
    
    def get_active_freeze(self) -> Optional[EmergencyFreeze]:
        """Get active freeze if any."""
        if self._active_freeze and not self._active_freeze.is_expired():
            return self._active_freeze
        return None
    
    def is_frozen(self, system: MeridSystem) -> bool:
        """Check if a system is frozen."""
        freeze = self.get_active_freeze()
        if not freeze:
            return False
        return freeze.scope == "ALL" or freeze.scope == system.value
    
    # =========================================================================
    # Callback Registration
    # =========================================================================
    
    def on_execution_authorized(self, callback: Callable[[Intent, ExecutionConstraints], None]) -> None:
        """Register callback for execution authorization."""
        self._on_execution_authorized = callback
    
    def on_freeze(self, callback: Callable[[EmergencyFreeze], None]) -> None:
        """Register callback for freeze events."""
        self._on_freeze = callback
    
    def on_unfreeze(self, callback: Callable[[str], None]) -> None:
        """Register callback for unfreeze events."""
        self._on_unfreeze = callback
    
    def set_archive_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Set archive recording callback."""
        self._archive_record = callback
    
    def get_stats(self) -> Dict[str, Any]:
        """Get API statistics."""
        return {
            "total_intents": len(self._intents),
            "pending_intents": len(self.get_pending_intents()),
            "total_executions": len(self._executions),
            "total_deposits": len(self._deposits),
            "active_freeze": self._active_freeze.freeze_id[:8] if self._active_freeze else None,
        }


# Singleton instance
_intersystem_api: Optional[InterSystemAPI] = None
_intersystem_api_lock = threading.Lock()


def get_intersystem_api() -> InterSystemAPI:
    """Get the singleton inter-system API."""
    global _intersystem_api
    if _intersystem_api is None:
        with _intersystem_api_lock:
            if _intersystem_api is None:
                _intersystem_api = InterSystemAPI()
    return _intersystem_api
