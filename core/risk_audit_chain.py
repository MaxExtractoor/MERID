"""Hash-chain audit logger for critical risk events.

Provides tamper-evident logging for the 4 critical risk events:
- risk.position_sync_failed
- risk.bankroll_unavailable  
- risk.equity_feed_lost
- consensus.threshold_changed

Design:
- Append-only line-delimited JSON
- SHA256 hash chain linking each record to previous
- Canonical JSON serialization for deterministic hashing
- Verification tool to detect any tampering

Usage:
    from core.risk_audit_chain import get_risk_audit_chain
    
    # Log a risk event
    chain = get_risk_audit_chain()
    chain.log_event("risk.position_sync_failed", {
        "ticker": "KXBTC15M-...",
        "size": 10,
        "reason": "missing_avg_price"
    })
    
    # Verify chain integrity
    result = chain.verify_chain()
    if not result.valid:
        print(f"Chain broken at record {result.broken_at}")
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("core.risk_audit_chain")

# Default storage path
DEFAULT_AUDIT_LOG_PATH = os.environ.get(
    "MERID_RISK_AUDIT_LOG",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "risk_audit_chain.jsonl")
)

GENESIS_HASH = "GENESIS"


@dataclass(frozen=True)
class AuditRecord:
    """Single tamper-evident audit record."""
    timestamp: str  # ISO format UTC
    event_type: str  # e.g., "risk.position_sync_failed"
    payload: Dict[str, Any]  # Event-specific data
    prev_hash: str  # Hash of previous record
    event_hash: str  # Hash of this record (chained)
    sequence: int  # Monotonic sequence number

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "payload": self.payload,
            "prev_hash": self.prev_hash,
            "event_hash": self.event_hash,
            "sequence": self.sequence,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AuditRecord:
        return cls(
            timestamp=data["timestamp"],
            event_type=data["event_type"],
            payload=data["payload"],
            prev_hash=data["prev_hash"],
            event_hash=data["event_hash"],
            sequence=data["sequence"],
        )


@dataclass
class VerificationResult:
    """Result of chain verification."""
    valid: bool
    records_checked: int
    broken_at: Optional[int] = None  # Sequence number where break occurred
    expected_hash: Optional[str] = None
    actual_hash: Optional[str] = None


class RiskAuditChain:
    """Tamper-evident audit chain for critical risk events.
    
    Thread-safe singleton that maintains an append-only hash chain
    of risk events for compliance and forensic analysis.
    """
    
    # Critical event types that must be logged
    CRITICAL_EVENTS = {
        "risk.position_sync_failed",
        "risk.bankroll_unavailable",
        "risk.equity_feed_lost",
        "consensus.threshold_changed",
    }
    
    def __init__(self, log_path: Optional[str] = None):
        self._log_path = Path(log_path or DEFAULT_AUDIT_LOG_PATH)
        self._lock = threading.Lock()
        self._sequence = 0
        self._last_hash = GENESIS_HASH
        
        # Ensure directory exists
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing chain to determine current state
        self._load_chain_state()
    
    def _load_chain_state(self) -> None:
        """Load existing chain to determine next sequence and last hash."""
        if not self._log_path.exists():
            return
            
        try:
            with open(self._log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        record = AuditRecord.from_dict(data)
                        self._sequence = max(self._sequence, record.sequence)
                        self._last_hash = record.event_hash
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning("Corrupt audit record found: %s", e)
                        continue
        except Exception as e:
            logger.error("Failed to load audit chain state: %s", e)
    
    def _compute_hash(self, timestamp: str, event_type: str, 
                      payload: Dict[str, Any], prev_hash: str) -> str:
        """Compute deterministic hash for a record.
        
        Hash = SHA256(prev_hash + canonical_json(payload_with_meta))
        """
        # Build canonical data structure
        canonical_data = {
            "timestamp": timestamp,
            "event_type": event_type,
            "payload": payload,
            "prev_hash": prev_hash,
        }
        
        # Deterministic JSON serialization (sorted keys, no extra whitespace)
        canonical_json_str = json.dumps(canonical_data, sort_keys=True, separators=(',', ':'))
        
        # Compute hash
        hasher = hashlib.sha256()
        hasher.update(canonical_json_str.encode('utf-8'))
        return hasher.hexdigest()
    
    def log_event(self, event_type: str, payload: Dict[str, Any]) -> AuditRecord:
        """Log a critical risk event to the tamper-evident chain.
        
        Args:
            event_type: One of CRITICAL_EVENTS or custom event type
            payload: Event-specific data (must be JSON serializable)
            
        Returns:
            The created AuditRecord
            
        Raises:
            ValueError: If event_type is not in CRITICAL_EVENTS (unless override)
        """
        if event_type not in self.CRITICAL_EVENTS:
            # Still log but warn - we want to capture all risk events
            logger.debug("Logging non-critical event type: %s", event_type)
        
        with self._lock:
            timestamp = datetime.now(timezone.utc).isoformat()
            
            # Compute hash including previous hash for chaining
            event_hash = self._compute_hash(timestamp, event_type, payload, self._last_hash)
            
            # Increment sequence
            self._sequence += 1
            
            # Create record
            record = AuditRecord(
                timestamp=timestamp,
                event_type=event_type,
                payload=payload,
                prev_hash=self._last_hash,
                event_hash=event_hash,
                sequence=self._sequence,
            )
            
            # Append to log file
            try:
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
                    f.flush()
                    os.fsync(f.fileno())  # Ensure durable write
            except Exception as e:
                logger.error("Failed to write audit record: %s", e)
                raise
            
            # Update internal state
            self._last_hash = event_hash
            
            logger.debug(
                "[AUDIT_CHAIN] seq=%d event=%s hash=%s... prev=%s...",
                record.sequence,
                event_type,
                event_hash[:16],
                record.prev_hash[:16] if record.prev_hash != GENESIS_HASH else "GENESIS"
            )
            
            return record
    
    def verify_chain(self) -> VerificationResult:
        """Verify the integrity of the entire audit chain.
        
        Walks the chain from GENESIS to the most recent record,
        recomputing and comparing each hash.
        
        Returns:
            VerificationResult with validity status and break location if any
        """
        if not self._log_path.exists():
            return VerificationResult(valid=True, records_checked=0)
        
        records_checked = 0
        expected_prev_hash = GENESIS_HASH
        
        try:
            with open(self._log_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    if not line.strip():
                        continue
                    
                    try:
                        data = json.loads(line)
                        record = AuditRecord.from_dict(data)
                    except (json.JSONDecodeError, KeyError) as e:
                        return VerificationResult(
                            valid=False,
                            records_checked=records_checked,
                            broken_at=records_checked,
                            expected_hash="valid JSON",
                            actual_hash=f"corrupt record at line {line_num}: {e}"
                        )
                    
                    # Verify sequence continuity
                    if record.sequence != records_checked + 1:
                        return VerificationResult(
                            valid=False,
                            records_checked=records_checked,
                            broken_at=record.sequence,
                            expected_hash=f"sequence {records_checked + 1}",
                            actual_hash=f"sequence {record.sequence}"
                        )
                    
                    # Verify prev_hash chain
                    if record.prev_hash != expected_prev_hash:
                        return VerificationResult(
                            valid=False,
                            records_checked=records_checked,
                            broken_at=record.sequence,
                            expected_hash=expected_prev_hash[:32] + "...",
                            actual_hash=record.prev_hash[:32] + "..."
                        )
                    
                    # Recompute hash and verify
                    computed_hash = self._compute_hash(
                        record.timestamp,
                        record.event_type,
                        record.payload,
                        record.prev_hash
                    )
                    
                    if computed_hash != record.event_hash:
                        return VerificationResult(
                            valid=False,
                            records_checked=records_checked,
                            broken_at=record.sequence,
                            expected_hash=computed_hash[:32] + "...",
                            actual_hash=record.event_hash[:32] + "..."
                        )
                    
                    records_checked += 1
                    expected_prev_hash = record.event_hash
        
        except Exception as e:
            logger.error("Chain verification failed with exception: %s", e)
            return VerificationResult(
                valid=False,
                records_checked=records_checked,
                broken_at=records_checked,
                expected_hash="verification complete",
                actual_hash=f"exception: {e}"
            )
        
        return VerificationResult(valid=True, records_checked=records_checked)
    
    def export_proof_bundle(self, start_sequence: Optional[int] = None,
                           end_sequence: Optional[int] = None) -> List[Dict[str, Any]]:
        """Export a range of records as a proof bundle.
        
        This can be used for external verification or compliance submission.
        
        Args:
            start_sequence: First sequence number to include (default: 1)
            end_sequence: Last sequence number to include (default: latest)
            
        Returns:
            List of audit records as dictionaries
        """
        if not self._log_path.exists():
            return []
        
        start_sequence = start_sequence or 1
        records = []
        
        try:
            with open(self._log_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        record = AuditRecord.from_dict(data)
                        if record.sequence >= start_sequence:
                            if end_sequence and record.sequence > end_sequence:
                                break
                            records.append(record.to_dict())
                    except (json.JSONDecodeError, KeyError):
                        continue
        except Exception as e:
            logger.error("Failed to export proof bundle: %s", e)
            raise
        
        return records
    
    def get_latest_hash(self) -> str:
        """Get the hash of the most recent record."""
        return self._last_hash
    
    def get_sequence(self) -> int:
        """Get the current sequence number."""
        return self._sequence


# Singleton instance
_audit_chain_instance: Optional[RiskAuditChain] = None
_audit_chain_lock = threading.Lock()


def get_risk_audit_chain(log_path: Optional[str] = None) -> RiskAuditChain:
    """Get the singleton RiskAuditChain instance."""
    global _audit_chain_instance
    
    if _audit_chain_instance is None:
        with _audit_chain_lock:
            if _audit_chain_instance is None:
                _audit_chain_instance = RiskAuditChain(log_path)
    
    return _audit_chain_instance


def verify_audit_chain(log_path: Optional[str] = None) -> VerificationResult:
    """Standalone verification function for CLI/tool usage."""
    chain = RiskAuditChain(log_path)
    return chain.verify_chain()
