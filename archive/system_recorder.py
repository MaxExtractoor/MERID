"""
MERID Archive - System Recorder

Production implementation of ARCHIVE's system-wide event recording.
Connects to all MERID systems to capture audit-grade records.

Authority:
- ARCHIVE cannot influence live systems
- ARCHIVE provides immutable truth only
- All records are append-only with hash chain integrity
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("archive.system_recorder")


class RecordCategory(Enum):
    """Categories of system records."""
    INTENT = "intent"
    EXECUTION = "execution"
    PROFIT = "profit"
    GOVERNANCE = "governance"
    EMERGENCY = "emergency"
    ANOMALY = "anomaly"
    REGIME = "regime"
    SYSTEM = "system"


class RecordPriority(Enum):
    """Priority levels for records."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SystemRecord:
    """A system-wide audit record."""
    record_id: str
    category: RecordCategory
    event_type: str
    timestamp: float
    origin_system: str
    
    # Event data
    intent_id: Optional[str] = None
    execution_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    
    # Outcome tracking
    outcome: Optional[Dict[str, Any]] = None
    pnl: Optional[float] = None
    success: Optional[bool] = None
    
    # Priority and flags
    priority: RecordPriority = RecordPriority.NORMAL
    requires_review: bool = False
    
    # Hash chain
    previous_hash: str = ""
    current_hash: str = ""
    block_number: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "category": self.category.value,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "origin_system": self.origin_system,
            "intent_id": self.intent_id,
            "execution_id": self.execution_id,
            "data": self.data,
            "outcome": self.outcome,
            "pnl": self.pnl,
            "success": self.success,
            "priority": self.priority.value,
            "requires_review": self.requires_review,
            "block_number": self.block_number,
            "current_hash": self.current_hash[:16] + "..." if self.current_hash else None,
        }


class SystemRecorder:
    """
    ARCHIVE's system-wide event recorder.
    
    Responsibilities:
    - Capture events from all MERID systems
    - Maintain hash chain integrity
    - Provide query interface for audit
    - Track intent-to-outcome mappings
    - Support forensic analysis
    """
    
    def __init__(self):
        self._records: List[SystemRecord] = []
        self._by_intent: Dict[str, List[str]] = {}  # intent_id -> record_ids
        self._by_execution: Dict[str, List[str]] = {}  # execution_id -> record_ids
        self._by_category: Dict[RecordCategory, List[str]] = {cat: [] for cat in RecordCategory}
        
        # Hash chain state
        self._last_hash = "0" * 64
        self._block_number = 0
        
        # Ledger integration
        self._ledger = None
        self._decision_logger = None
        
        # Statistics
        self._records_by_system: Dict[str, int] = {}
        self._records_by_type: Dict[str, int] = {}
        
        logger.info("System recorder initialized")
    
    def initialize_components(self) -> None:
        """Initialize archive component integrations."""
        try:
            from archive.ledger import get_audit_ledger
            self._ledger = get_audit_ledger()
            logger.info("Audit ledger integration initialized")
        except Exception as e:
            logger.warning("Could not initialize audit ledger: %s", e)
        
        try:
            from archive.decisions import get_decision_logger
            self._decision_logger = get_decision_logger()
            logger.info("Decision logger integration initialized")
        except Exception as e:
            logger.warning("Could not initialize decision logger: %s", e)
    
    def record(
        self,
        category: RecordCategory,
        event_type: str,
        origin_system: str,
        intent_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        outcome: Optional[Dict[str, Any]] = None,
        pnl: Optional[float] = None,
        success: Optional[bool] = None,
        priority: RecordPriority = RecordPriority.NORMAL,
    ) -> SystemRecord:
        """
        Record a system event.
        
        Returns the created record.
        """
        import uuid
        import hashlib
        import json
        
        self._block_number += 1
        
        record = SystemRecord(
            record_id=str(uuid.uuid4()),
            category=category,
            event_type=event_type,
            timestamp=time.time(),
            origin_system=origin_system,
            intent_id=intent_id,
            execution_id=execution_id,
            data=data or {},
            outcome=outcome,
            pnl=pnl,
            success=success,
            priority=priority,
            previous_hash=self._last_hash,
            block_number=self._block_number,
        )
        
        # Compute hash
        hash_content = {
            "record_id": record.record_id,
            "category": record.category.value,
            "event_type": record.event_type,
            "timestamp": record.timestamp,
            "origin_system": record.origin_system,
            "data": record.data,
            "previous_hash": record.previous_hash,
            "block_number": record.block_number,
        }
        hash_str = json.dumps(hash_content, sort_keys=True, default=str)
        record.current_hash = hashlib.sha256(hash_str.encode()).hexdigest()
        self._last_hash = record.current_hash
        
        # Store record
        self._records.append(record)
        
        # Index by intent
        if intent_id:
            if intent_id not in self._by_intent:
                self._by_intent[intent_id] = []
            self._by_intent[intent_id].append(record.record_id)
        
        # Index by execution
        if execution_id:
            if execution_id not in self._by_execution:
                self._by_execution[execution_id] = []
            self._by_execution[execution_id].append(record.record_id)
        
        # Index by category
        self._by_category[category].append(record.record_id)
        
        # Update statistics
        self._records_by_system[origin_system] = self._records_by_system.get(origin_system, 0) + 1
        self._records_by_type[event_type] = self._records_by_type.get(event_type, 0) + 1
        
        # Persist to ledger
        if self._ledger:
            try:
                from archive.ledger import EventType
                ledger_event_type = self._map_to_ledger_event_type(event_type)
                self._ledger.record(
                    event_type=ledger_event_type,
                    origin_system=origin_system,
                    intent_id=intent_id,
                    data=data,
                    outcome=outcome,
                )
            except Exception as e:
                logger.error("Failed to persist to ledger: %s", e)
        
        # Log decision if applicable
        if self._decision_logger and intent_id and category == RecordCategory.INTENT:
            try:
                self._log_decision(record)
            except Exception as e:
                logger.error("Failed to log decision: %s", e)
        
        logger.debug(
            "Recorded: %s %s from %s (block %d)",
            category.value, event_type, origin_system, self._block_number
        )
        
        return record
    
    def _map_to_ledger_event_type(self, event_type: str):
        """Map event type string to ledger EventType."""
        from archive.ledger import EventType
        
        mapping = {
            "INTENT_PROPOSED": EventType.INTENT_PROPOSED,
            "INTENT_APPROVED": EventType.INTENT_APPROVED,
            "INTENT_REJECTED": EventType.INTENT_REJECTED,
            "INTENT_EXECUTED": EventType.INTENT_EXECUTED,
            "INTENT_EXPIRED": EventType.INTENT_EXPIRED,
            "ANOMALY_DETECTED": EventType.ANOMALY_DETECTED,
            "REGIME_CHANGE": EventType.REGIME_CHANGE,
            "EMERGENCY_FREEZE": EventType.EMERGENCY_FREEZE,
            "EMERGENCY_UNFREEZE": EventType.EMERGENCY_UNFREEZE,
            "CAPITAL_MOVEMENT": EventType.CAPITAL_MOVEMENT,
            "PROFIT_DEPOSIT": EventType.PROFIT_DEPOSIT,
        }
        
        return mapping.get(event_type, EventType.GOVERNANCE_DECISION)
    
    def _log_decision(self, record: SystemRecord) -> None:
        """Log decision to decision logger."""
        if not self._decision_logger or not record.intent_id:
            return
        
        # This would integrate with decisions.py
        pass
    
    # =========================================================================
    # Record Methods for Each System
    # =========================================================================
    
    def record_intent_proposed(
        self,
        intent_id: str,
        strategy_id: str,
        regime: str,
        confidence: float,
        notional: float,
    ) -> SystemRecord:
        """Record an intent proposal from OPS."""
        return self.record(
            category=RecordCategory.INTENT,
            event_type="INTENT_PROPOSED",
            origin_system="OPS",
            intent_id=intent_id,
            data={
                "strategy_id": strategy_id,
                "regime": regime,
                "confidence": confidence,
                "notional": notional,
            },
        )
    
    def record_intent_approved(
        self,
        intent_id: str,
        approved_by: List[str],
        constraints: Dict[str, Any],
    ) -> SystemRecord:
        """Record an intent approval from GOV."""
        return self.record(
            category=RecordCategory.GOVERNANCE,
            event_type="INTENT_APPROVED",
            origin_system="GOV",
            intent_id=intent_id,
            data={
                "approved_by": approved_by,
                "constraints": constraints,
            },
            success=True,
        )
    
    def record_intent_rejected(
        self,
        intent_id: str,
        rejected_by: List[str],
        reason: str,
    ) -> SystemRecord:
        """Record an intent rejection from GOV."""
        return self.record(
            category=RecordCategory.GOVERNANCE,
            event_type="INTENT_REJECTED",
            origin_system="GOV",
            intent_id=intent_id,
            data={
                "rejected_by": rejected_by,
                "reason": reason,
            },
            success=False,
        )
    
    def record_execution(
        self,
        intent_id: str,
        execution_id: str,
        status: str,
        filled_notional: float,
        slippage_bps: int,
        pnl: Optional[float] = None,
    ) -> SystemRecord:
        """Record an execution from FIN."""
        return self.record(
            category=RecordCategory.EXECUTION,
            event_type="INTENT_EXECUTED",
            origin_system="FIN",
            intent_id=intent_id,
            execution_id=execution_id,
            data={
                "status": status,
                "filled_notional": filled_notional,
                "slippage_bps": slippage_bps,
            },
            pnl=pnl,
            success=status == "COMPLETED",
        )
    
    def record_profit_deposit(
        self,
        intent_id: str,
        execution_id: str,
        amount: float,
        asset: str,
        vault: str,
    ) -> SystemRecord:
        """Record a profit deposit to TREASURY."""
        return self.record(
            category=RecordCategory.PROFIT,
            event_type="PROFIT_DEPOSIT",
            origin_system="FIN",
            intent_id=intent_id,
            execution_id=execution_id,
            data={
                "amount": amount,
                "asset": asset,
                "vault": vault,
            },
            pnl=amount,
            success=True,
        )
    
    def record_emergency_freeze(
        self,
        freeze_id: str,
        scope: str,
        reason: str,
        severity: str,
        authorized_by: List[str],
    ) -> SystemRecord:
        """Record an emergency freeze from GOV."""
        return self.record(
            category=RecordCategory.EMERGENCY,
            event_type="EMERGENCY_FREEZE",
            origin_system="GOV",
            data={
                "freeze_id": freeze_id,
                "scope": scope,
                "reason": reason,
                "severity": severity,
                "authorized_by": authorized_by,
            },
            priority=RecordPriority.CRITICAL,
            requires_review=True,
        )
    
    def record_anomaly(
        self,
        anomaly_type: str,
        severity: str,
        description: str,
        source: str,
    ) -> SystemRecord:
        """Record an anomaly detection from OPS."""
        priority = RecordPriority.HIGH if severity in ["high", "critical"] else RecordPriority.NORMAL
        
        return self.record(
            category=RecordCategory.ANOMALY,
            event_type="ANOMALY_DETECTED",
            origin_system="OPS",
            data={
                "anomaly_type": anomaly_type,
                "severity": severity,
                "description": description,
                "source": source,
            },
            priority=priority,
            requires_review=severity in ["high", "critical"],
        )
    
    def record_regime_change(
        self,
        old_regime: str,
        new_regime: str,
        confidence: float,
    ) -> SystemRecord:
        """Record a regime change from OPS."""
        return self.record(
            category=RecordCategory.REGIME,
            event_type="REGIME_CHANGE",
            origin_system="OPS",
            data={
                "old_regime": old_regime,
                "new_regime": new_regime,
                "confidence": confidence,
            },
        )
    
    # =========================================================================
    # Query Methods
    # =========================================================================
    
    def get_record(self, record_id: str) -> Optional[SystemRecord]:
        """Get a record by ID."""
        for record in self._records:
            if record.record_id == record_id:
                return record
        return None
    
    def get_by_intent(self, intent_id: str) -> List[SystemRecord]:
        """Get all records for an intent."""
        record_ids = self._by_intent.get(intent_id, [])
        return [r for r in self._records if r.record_id in record_ids]
    
    def get_by_execution(self, execution_id: str) -> List[SystemRecord]:
        """Get all records for an execution."""
        record_ids = self._by_execution.get(execution_id, [])
        return [r for r in self._records if r.record_id in record_ids]
    
    def get_by_category(
        self,
        category: RecordCategory,
        limit: int = 100,
    ) -> List[SystemRecord]:
        """Get records by category."""
        record_ids = self._by_category.get(category, [])
        records = [r for r in self._records if r.record_id in record_ids]
        return records[-limit:]
    
    def get_by_system(
        self,
        origin_system: str,
        limit: int = 100,
    ) -> List[SystemRecord]:
        """Get records by origin system."""
        records = [r for r in self._records if r.origin_system == origin_system]
        return records[-limit:]
    
    def get_by_time_range(
        self,
        start_ts: float,
        end_ts: float,
        limit: int = 1000,
    ) -> List[SystemRecord]:
        """Get records in a time range."""
        records = [r for r in self._records if start_ts <= r.timestamp <= end_ts]
        return records[:limit]
    
    def get_requiring_review(self) -> List[SystemRecord]:
        """Get records requiring review."""
        return [r for r in self._records if r.requires_review]
    
    def get_latest(self, n: int = 10) -> List[SystemRecord]:
        """Get latest n records."""
        return self._records[-n:]
    
    # =========================================================================
    # Integrity Methods
    # =========================================================================
    
    def verify_integrity(self) -> bool:
        """Verify hash chain integrity."""
        if not self._records:
            return True
        
        expected_hash = "0" * 64
        
        for record in self._records:
            if record.previous_hash != expected_hash:
                logger.error(
                    "Chain break at block %d: expected %s, got %s",
                    record.block_number, expected_hash[:16], record.previous_hash[:16]
                )
                return False
            expected_hash = record.current_hash
        
        logger.info("Integrity verified: %d records", len(self._records))
        return True
    
    def get_stats(self) -> Dict[str, Any]:
        """Get recorder statistics."""
        return {
            "total_records": len(self._records),
            "block_number": self._block_number,
            "last_hash": self._last_hash[:16] + "..." if self._last_hash else None,
            "by_category": {cat.value: len(ids) for cat, ids in self._by_category.items()},
            "by_system": self._records_by_system,
            "by_type": self._records_by_type,
            "intents_tracked": len(self._by_intent),
            "executions_tracked": len(self._by_execution),
            "requiring_review": len(self.get_requiring_review()),
            "integrity_valid": self.verify_integrity(),
        }


# Singleton instance
_system_recorder: Optional[SystemRecorder] = None


def get_system_recorder() -> SystemRecorder:
    """Get the singleton system recorder."""
    global _system_recorder
    if _system_recorder is None:
        _system_recorder = SystemRecorder()
        _system_recorder.initialize_components()
    return _system_recorder
