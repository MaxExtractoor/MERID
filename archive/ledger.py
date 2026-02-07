"""
MERID Archive - Immutable Audit Ledger

Provides tamper-proof, append-only storage for all system decisions and events.
Implements hash chain integrity for forensic verification.

Part of MERID-ARCHIVE (Layer 7 - Memory & Forensics)
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from pathlib import Path

from utils.logger import get_logger

logger = get_logger("archive.ledger")


class EventType(Enum):
    """Types of events recorded in the ledger."""
    INTENT_PROPOSED = "intent_proposed"
    INTENT_APPROVED = "intent_approved"
    INTENT_REJECTED = "intent_rejected"
    INTENT_EXECUTED = "intent_executed"
    INTENT_EXPIRED = "intent_expired"
    ANOMALY_DETECTED = "anomaly_detected"
    REGIME_CHANGE = "regime_change"
    EMERGENCY_FREEZE = "emergency_freeze"
    EMERGENCY_UNFREEZE = "emergency_unfreeze"
    CAPITAL_MOVEMENT = "capital_movement"
    PROFIT_DEPOSIT = "profit_deposit"
    SYSTEM_ERROR = "system_error"
    GOVERNANCE_DECISION = "governance_decision"
    MODEL_DEPLOYED = "model_deployed"
    MODEL_RETIRED = "model_retired"


@dataclass
class LedgerEntry:
    """A single entry in the audit ledger."""
    record_id: str
    event_type: EventType
    timestamp: float
    origin_system: str
    
    # Event data
    intent_id: Optional[str] = None
    regime: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    outcome: Optional[Dict[str, Any]] = None
    
    # Hash chain
    previous_hash: str = ""
    current_hash: str = ""
    block_number: int = 0
    
    def compute_hash(self) -> str:
        """Compute hash of this entry."""
        content = {
            "record_id": self.record_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "origin_system": self.origin_system,
            "intent_id": self.intent_id,
            "regime": self.regime,
            "data": self.data,
            "outcome": self.outcome,
            "previous_hash": self.previous_hash,
            "block_number": self.block_number,
        }
        content_str = json.dumps(content, sort_keys=True, default=str)
        return hashlib.sha256(content_str.encode()).hexdigest()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "origin_system": self.origin_system,
            "intent_id": self.intent_id,
            "regime": self.regime,
            "data": self.data,
            "outcome": self.outcome,
            "previous_hash": self.previous_hash,
            "current_hash": self.current_hash,
            "block_number": self.block_number,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LedgerEntry':
        return cls(
            record_id=data["record_id"],
            event_type=EventType(data["event_type"]),
            timestamp=data["timestamp"],
            origin_system=data["origin_system"],
            intent_id=data.get("intent_id"),
            regime=data.get("regime"),
            data=data.get("data", {}),
            outcome=data.get("outcome"),
            previous_hash=data.get("previous_hash", ""),
            current_hash=data.get("current_hash", ""),
            block_number=data.get("block_number", 0),
        )


class AuditLedger:
    """
    Immutable audit ledger with hash chain integrity.
    
    Features:
    - Append-only storage
    - Hash chain for tamper detection
    - Query by various filters
    - Persistence to disk
    """
    
    GENESIS_HASH = "0" * 64
    
    def __init__(self, storage_path: Optional[str] = None):
        self._entries: List[LedgerEntry] = []
        self._storage_path = Path(storage_path) if storage_path else None
        self._last_hash = self.GENESIS_HASH
        self._block_number = 0
        
        # Load existing entries if storage exists
        if self._storage_path and self._storage_path.exists():
            self._load_from_disk()
        
        logger.info("Audit ledger initialized: %d entries", len(self._entries))
    
    def record(
        self,
        event_type: EventType,
        origin_system: str,
        intent_id: Optional[str] = None,
        regime: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        outcome: Optional[Dict[str, Any]] = None,
    ) -> LedgerEntry:
        """
        Record an event in the ledger.
        
        Returns the created entry.
        """
        import uuid
        
        self._block_number += 1
        
        entry = LedgerEntry(
            record_id=str(uuid.uuid4()),
            event_type=event_type,
            timestamp=time.time(),
            origin_system=origin_system,
            intent_id=intent_id,
            regime=regime,
            data=data or {},
            outcome=outcome,
            previous_hash=self._last_hash,
            block_number=self._block_number,
        )
        
        # Compute and set hash
        entry.current_hash = entry.compute_hash()
        self._last_hash = entry.current_hash
        
        # Append (immutable)
        self._entries.append(entry)
        
        # Persist
        if self._storage_path:
            self._persist_entry(entry)
        
        logger.debug(
            "Recorded event: type=%s, block=%d, hash=%s",
            event_type.value, self._block_number, entry.current_hash[:16]
        )
        
        return entry
    
    def verify_integrity(self) -> bool:
        """
        Verify hash chain integrity.
        
        Returns True if chain is valid, False if tampered.
        """
        if not self._entries:
            return True
        
        # Check genesis
        if self._entries[0].previous_hash != self.GENESIS_HASH:
            logger.error("Genesis hash mismatch")
            return False
        
        # Verify chain
        for i, entry in enumerate(self._entries):
            # Verify entry hash
            computed_hash = entry.compute_hash()
            if computed_hash != entry.current_hash:
                logger.error(
                    "Hash mismatch at block %d: expected %s, got %s",
                    entry.block_number, entry.current_hash[:16], computed_hash[:16]
                )
                return False
            
            # Verify chain link
            if i > 0:
                if entry.previous_hash != self._entries[i-1].current_hash:
                    logger.error(
                        "Chain break at block %d: previous_hash mismatch",
                        entry.block_number
                    )
                    return False
        
        logger.info("Ledger integrity verified: %d blocks", len(self._entries))
        return True
    
    def query(
        self,
        event_types: Optional[List[EventType]] = None,
        origin_system: Optional[str] = None,
        intent_id: Optional[str] = None,
        start_ts: Optional[float] = None,
        end_ts: Optional[float] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[LedgerEntry]:
        """Query ledger entries with filters."""
        results = []
        
        for entry in self._entries:
            # Apply filters
            if event_types and entry.event_type not in event_types:
                continue
            if origin_system and entry.origin_system != origin_system:
                continue
            if intent_id and entry.intent_id != intent_id:
                continue
            if start_ts and entry.timestamp < start_ts:
                continue
            if end_ts and entry.timestamp > end_ts:
                continue
            
            results.append(entry)
        
        # Apply pagination
        return results[offset:offset + limit]
    
    def get_by_intent(self, intent_id: str) -> List[LedgerEntry]:
        """Get all entries for an intent."""
        return [e for e in self._entries if e.intent_id == intent_id]
    
    def get_latest(self, n: int = 10) -> List[LedgerEntry]:
        """Get latest n entries."""
        return self._entries[-n:]
    
    def get_entry_count(self) -> int:
        """Get total entry count."""
        return len(self._entries)
    
    def get_last_hash(self) -> str:
        """Get last hash in chain."""
        return self._last_hash
    
    def _persist_entry(self, entry: LedgerEntry) -> None:
        """Persist entry to disk."""
        if not self._storage_path:
            return
        
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self._storage_path, "a") as f:
            f.write(json.dumps(entry.to_dict(), default=str) + "\n")
    
    def _load_from_disk(self) -> None:
        """Load entries from disk."""
        if not self._storage_path or not self._storage_path.exists():
            return
        
        with open(self._storage_path, "r") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    entry = LedgerEntry.from_dict(data)
                    self._entries.append(entry)
                    self._last_hash = entry.current_hash
                    self._block_number = entry.block_number
        
        logger.info("Loaded %d entries from disk", len(self._entries))
    
    def export_json(self, path: str) -> None:
        """Export ledger to JSON file."""
        data = {
            "entries": [e.to_dict() for e in self._entries],
            "last_hash": self._last_hash,
            "block_count": self._block_number,
            "exported_at": time.time(),
        }
        
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        
        logger.info("Exported %d entries to %s", len(self._entries), path)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get ledger statistics."""
        event_counts = {}
        for entry in self._entries:
            event_type = entry.event_type.value
            event_counts[event_type] = event_counts.get(event_type, 0) + 1
        
        return {
            "total_entries": len(self._entries),
            "block_number": self._block_number,
            "last_hash": self._last_hash[:16] + "..." if self._last_hash else None,
            "event_counts": event_counts,
            "integrity_valid": self.verify_integrity(),
        }


# Singleton instance
_audit_ledger: Optional[AuditLedger] = None


def get_audit_ledger(storage_path: Optional[str] = None) -> AuditLedger:
    """Get the singleton audit ledger."""
    global _audit_ledger
    if _audit_ledger is None:
        _audit_ledger = AuditLedger(storage_path)
    return _audit_ledger
