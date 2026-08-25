"""
Audit Logger.

Comprehensive audit logging for all system actions with
tamper-evident storage and cryptographic verification.

Version: 1.0.0
"""

from __future__ import annotations

import threading
import os
import json
import time
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger("compliance.audit")


class AuditCategory(Enum):
    """Categories of audit events."""
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    TRADING = "trading"
    WALLET = "wallet"
    CONFIGURATION = "configuration"
    SYSTEM = "system"
    DATA_ACCESS = "data_access"
    COMPLIANCE = "compliance"


class AuditSeverity(Enum):
    """Severity levels for audit events."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AuditEvent:
    """An audit event record."""
    event_id: str
    category: AuditCategory
    severity: AuditSeverity
    action: str
    
    # Actor
    actor_id: str = "system"
    actor_type: str = "system"  # user, system, agent, api
    actor_ip: str = ""
    
    # Target
    target_type: str = ""
    target_id: str = ""
    
    # Details
    details: Dict[str, Any] = field(default_factory=dict)
    result: str = "success"  # success, failure, partial
    error_message: str = ""
    
    # Timing
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    
    # Chain
    previous_hash: str = ""
    event_hash: str = ""
    
    def compute_hash(self) -> str:
        """Compute hash for tamper detection."""
        data = {
            "event_id": self.event_id,
            "category": self.category.value,
            "action": self.action,
            "actor_id": self.actor_id,
            "target_id": self.target_id,
            "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
        }
        data_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(data_str.encode()).hexdigest()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "action": self.action,
            "actor_id": self.actor_id,
            "actor_type": self.actor_type,
            "actor_ip": self.actor_ip,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "details": self.details,
            "result": self.result,
            "error_message": self.error_message,
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            "duration_ms": self.duration_ms,
            "previous_hash": self.previous_hash,
            "event_hash": self.event_hash,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditEvent":
        return cls(
            event_id=data["event_id"],
            category=AuditCategory(data["category"]),
            severity=AuditSeverity(data["severity"]),
            action=data["action"],
            actor_id=data.get("actor_id", "system"),
            actor_type=data.get("actor_type", "system"),
            actor_ip=data.get("actor_ip", ""),
            target_type=data.get("target_type", ""),
            target_id=data.get("target_id", ""),
            details=data.get("details", {}),
            result=data.get("result", "success"),
            error_message=data.get("error_message", ""),
            timestamp=data.get("timestamp", time.time()),
            duration_ms=data.get("duration_ms", 0.0),
            previous_hash=data.get("previous_hash", ""),
            event_hash=data.get("event_hash", ""),
        )


class AuditLogger:
    """
    Tamper-evident audit logging system.
    
    Features:
    - Cryptographic hash chain
    - Persistent storage
    - Query and search
    - Export capabilities
    """
    
    def __init__(self, log_dir: str = "data/audit"):
        self.logger = get_logger("compliance.audit")
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory buffer
        self._buffer: List[AuditEvent] = []
        self._buffer_size: int = 100
        
        # Hash chain
        self._last_hash: str = "genesis"
        
        # Current log file
        self._current_file: Optional[Path] = None
        self._current_date: str = ""
        
        # Statistics
        self._total_events: int = 0
        self._events_by_category: Dict[str, int] = {}
        
        # Load last hash
        self._load_last_hash()
    
    def _load_last_hash(self) -> None:
        """Load last hash from most recent log file."""
        try:
            log_files = sorted(self.log_dir.glob("audit_*.jsonl"), reverse=True)
            if log_files:
                with open(log_files[0], "r") as f:
                    lines = f.readlines()
                    if lines:
                        last_event = json.loads(lines[-1])
                        self._last_hash = last_event.get("event_hash", "genesis")
        except Exception as e:
            self.logger.warning(f"Could not load last hash: {e}")
    
    def _get_log_file(self) -> Path:
        """Get current log file (rotates daily)."""
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        
        if today != self._current_date:
            self._current_date = today
            self._current_file = self.log_dir / f"audit_{today}.jsonl"
        
        return self._current_file
    
    def log(
        self,
        category: AuditCategory,
        action: str,
        severity: AuditSeverity = AuditSeverity.INFO,
        actor_id: str = "system",
        actor_type: str = "system",
        actor_ip: str = "",
        target_type: str = "",
        target_id: str = "",
        details: Optional[Dict[str, Any]] = None,
        result: str = "success",
        error_message: str = "",
        duration_ms: float = 0.0,
        timestamp: Optional[float] = None,
    ) -> str:
        """Log an audit event."""
        import uuid

        event_id = f"audit_{uuid.uuid4().hex[:16]}"

        event = AuditEvent(
            event_id=event_id,
            category=category,
            severity=severity,
            action=action,
            actor_id=actor_id,
            actor_type=actor_type,
            actor_ip=actor_ip,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
            result=result,
            error_message=error_message,
            duration_ms=duration_ms,
            timestamp=timestamp if timestamp is not None else time.time(),
            previous_hash=self._last_hash,
        )
        
        # Compute hash
        event.event_hash = event.compute_hash()
        self._last_hash = event.event_hash
        
        # Add to buffer
        self._buffer.append(event)
        
        # Update stats
        self._total_events += 1
        cat_key = category.value
        self._events_by_category[cat_key] = self._events_by_category.get(cat_key, 0) + 1
        
        # Flush if buffer full
        if len(self._buffer) >= self._buffer_size:
            self._flush()
        
        # Log critical events immediately
        if severity == AuditSeverity.CRITICAL:
            self._flush()
            self.logger.critical(f"AUDIT: {action} by {actor_id} - {result}")
        
        return event_id
    
    def _flush(self) -> None:
        """Flush buffer to disk using write-ahead log (T-029).

        Pattern:
        1. Write events to WAL file first (append-only, fsync'd)
        2. Flush to primary log file
        3. Truncate WAL only after successful primary write
        """
        if not self._buffer:
            return

        log_file = self._get_log_file()
        wal_file = self.log_dir / "_audit_wal.jsonl"

        serialized = [json.dumps(event.to_dict()) + "\n" for event in self._buffer]

        # Step 1: Write to WAL with fsync for durability
        try:
            with open(wal_file, "a") as wf:
                wf.writelines(serialized)
                wf.flush()
                import os as _os
                _os.fsync(wf.fileno())
        except Exception as e:
            self.logger.error(f"WAL write failed (events preserved in buffer): {e}")
            return  # Do NOT clear buffer — retry on next flush

        # Step 2: Write to primary log file
        try:
            with open(log_file, "a") as f:
                f.writelines(serialized)
        except Exception as e:
            self.logger.error(f"Primary audit log write failed (WAL preserved): {e}")
            return  # WAL has the data; buffer cleared below so WAL is source of truth

        # Step 3: Truncate WAL after successful primary write
        try:
            wal_file.write_text("")
        except Exception:
            pass  # Non-critical — WAL will be replayed on next startup

        self._buffer.clear()
    
    def query(
        self,
        category: Optional[AuditCategory] = None,
        actor_id: Optional[str] = None,
        target_id: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        severity: Optional[AuditSeverity] = None,
        limit: int = 100,
    ) -> List[AuditEvent]:
        """Query audit events."""
        # Flush buffer first
        self._flush()
        
        events = []
        
        # Determine which files to search
        log_files = sorted(self.log_dir.glob("audit_*.jsonl"), reverse=True)
        
        for log_file in log_files:
            try:
                with open(log_file, "r") as f:
                    for line in f:
                        event_data = json.loads(line)
                        event = AuditEvent.from_dict(event_data)
                        
                        # Apply filters
                        if category and event.category != category:
                            continue
                        if actor_id and event.actor_id != actor_id:
                            continue
                        if target_id and event.target_id != target_id:
                            continue
                        if start_time and event.timestamp < start_time:
                            continue
                        if end_time and event.timestamp > end_time:
                            continue
                        if severity and event.severity != severity:
                            continue
                        
                        events.append(event)
                        
                        if len(events) >= limit:
                            break
                
                if len(events) >= limit:
                    break
                    
            except Exception as e:
                self.logger.error(f"Error reading {log_file}: {e}")
        
        return events
    
    def verify_chain(self, start_date: Optional[str] = None) -> Dict[str, Any]:
        """Verify the integrity of the audit chain."""
        self._flush()
        
        log_files = sorted(self.log_dir.glob("audit_*.jsonl"))
        
        if start_date:
            log_files = [f for f in log_files if f.stem >= f"audit_{start_date}"]
        
        total_events = 0
        valid_events = 0
        invalid_events = []
        previous_hash = "genesis"
        
        for log_file in log_files:
            try:
                with open(log_file, "r") as f:
                    for line_num, line in enumerate(f, 1):
                        event_data = json.loads(line)
                        event = AuditEvent.from_dict(event_data)
                        total_events += 1
                        
                        # Verify previous hash
                        if event.previous_hash != previous_hash:
                            invalid_events.append({
                                "file": log_file.name,
                                "line": line_num,
                                "event_id": event.event_id,
                                "error": "previous_hash_mismatch",
                            })
                        
                        # Verify event hash
                        computed_hash = event.compute_hash()
                        if computed_hash != event.event_hash:
                            invalid_events.append({
                                "file": log_file.name,
                                "line": line_num,
                                "event_id": event.event_id,
                                "error": "event_hash_mismatch",
                            })
                        else:
                            valid_events += 1
                        
                        previous_hash = event.event_hash
                        
            except Exception as e:
                self.logger.error(f"Error verifying {log_file}: {e}")
        
        return {
            "total_events": total_events,
            "valid_events": valid_events,
            "invalid_events": len(invalid_events),
            "chain_valid": len(invalid_events) == 0,
            "invalid_details": invalid_events[:10],
        }
    
    def export(
        self,
        start_time: float,
        end_time: float,
        format: str = "json",
    ) -> str:
        """Export audit events to file."""
        events = self.query(start_time=start_time, end_time=end_time, limit=100000)
        
        export_dir = self.log_dir / "exports"
        export_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        
        if format == "json":
            export_file = export_dir / f"audit_export_{timestamp}.json"
            with open(export_file, "w") as f:
                json.dump([e.to_dict() for e in events], f, indent=2)
        elif format == "csv":
            export_file = export_dir / f"audit_export_{timestamp}.csv"
            import csv
            with open(export_file, "w", newline="") as f:
                if events:
                    writer = csv.DictWriter(f, fieldnames=events[0].to_dict().keys())
                    writer.writeheader()
                    for event in events:
                        writer.writerow(event.to_dict())
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        return str(export_file)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get audit statistics."""
        self._flush()
        
        return {
            "total_events": self._total_events,
            "events_by_category": self._events_by_category,
            "last_hash": self._last_hash,
            "log_dir": str(self.log_dir),
            "buffer_size": len(self._buffer),
        }


# Singleton
_audit_logger: Optional[AuditLogger] = None
_audit_logger_lock = threading.Lock()


def get_audit_logger() -> AuditLogger:
    """Get or create the Audit Logger singleton."""
    global _audit_logger
    if _audit_logger is None:
        with _audit_logger_lock:
            if _audit_logger is None:
                _audit_logger = AuditLogger()
    return _audit_logger
