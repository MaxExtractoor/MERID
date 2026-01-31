"""
Immutable Audit Trail - Production implementation.

Append-only decision log for full auditability.
Every action is recorded and cannot be modified.
"""

from __future__ import annotations

import asyncio
import json
import hashlib
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from pathlib import Path
import time

from core.streaming_bus import get_event_bus, EventChannel, StreamEvent
from utils.logger import get_logger

logger = get_logger("core.audit")


@dataclass
class AuditEntry:
    """Immutable audit log entry."""
    sequence: int
    timestamp: float
    event_type: str
    source: str
    data: Dict[str, Any]
    previous_hash: str
    entry_hash: str = ""
    
    def __post_init__(self):
        if not self.entry_hash:
            self.entry_hash = self._calculate_hash()
    
    def _calculate_hash(self) -> str:
        """Calculate entry hash for chain integrity."""
        content = json.dumps({
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "source": self.source,
            "data": self.data,
            "previous_hash": self.previous_hash
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "source": self.source,
            "data": self.data,
            "previous_hash": self.previous_hash,
            "entry_hash": self.entry_hash
        }


class AuditTrail:
    """
    Immutable audit trail for all system decisions.
    
    Features:
    - Append-only log
    - Hash chain for integrity
    - Persistent storage
    - Real-time streaming
    """
    
    def __init__(self, storage_path: str = "data/audit"):
        self.bus = get_event_bus()
        self.running = False
        self._task: Optional[asyncio.Task] = None
        
        # Storage
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # Chain state
        self.entries: List[AuditEntry] = []
        self.sequence = 0
        self.last_hash = "genesis"
        
        # Load existing entries
        self._load_entries()
        
    def _load_entries(self):
        """Load existing audit entries from storage."""
        audit_file = self.storage_path / "audit_log.jsonl"
        if audit_file.exists():
            try:
                with open(audit_file, "r") as f:
                    for idx, raw_line in enumerate(f, start=1):
                        line = raw_line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            entry = AuditEntry(
                                sequence=data["sequence"],
                                timestamp=data["timestamp"],
                                event_type=data["event_type"],
                                source=data["source"],
                                data=data["data"],
                                previous_hash=data["previous_hash"],
                                entry_hash=data["entry_hash"]
                            )
                        except Exception as parse_err:
                            logger.warning("Skipping corrupt audit entry at line %d: %s", idx, parse_err)
                            continue

                        self.entries.append(entry)
                        self.sequence = entry.sequence
                        self.last_hash = entry.entry_hash

                if self.entries:
                    logger.info(f"Loaded {len(self.entries)} audit entries")
                else:
                    logger.info("Audit log file present but no valid entries found")
            except Exception as e:
                logger.error(f"Failed to load audit entries: {e}")
                # Fallback to empty chain if file is unrecoverable
                self.entries = []
                self.sequence = 0
                self.last_hash = "genesis"
                
    async def start(self):
        """Start the audit trail."""
        if self.running:
            return
        
        self.running = True
        
        # Subscribe to all auditable channels
        await self.bus.subscribe(
            subscriber_id="audit-trail",
            channels=[
                EventChannel.CONSENSUS,
                EventChannel.AGENT_OUTPUT,
                EventChannel.SIMULATION,
                EventChannel.EXECUTION
            ],
            queue_size=200
        )
        
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Audit trail started")
        
    async def stop(self):
        """Stop the audit trail."""
        self.running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        await self.bus.unsubscribe("audit-trail")
        logger.info(f"Audit trail stopped - {len(self.entries)} entries recorded")
        
    async def _run_loop(self):
        """Main audit recording loop."""
        logger.info("Audit trail entering recording loop")
        
        while self.running:
            try:
                event = await asyncio.wait_for(
                    self.bus.get_event("audit-trail"),
                    timeout=1.0
                )
                
                if event:
                    await self._record_event(event)
                    
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Audit trail error: {e}")
                await asyncio.sleep(1)
                
    async def _record_event(self, event: StreamEvent):
        """Record an event to the audit trail."""
        self.sequence += 1
        
        entry = AuditEntry(
            sequence=self.sequence,
            timestamp=event.timestamp,
            event_type=event.event_type,
            source=event.source,
            data=event.data,
            previous_hash=self.last_hash
        )
        
        self.entries.append(entry)
        self.last_hash = entry.entry_hash
        
        # Persist to storage
        await self._persist_entry(entry)
        
        # Publish audit event
        await self.bus.publish(StreamEvent(
            channel=EventChannel.AUDIT,
            event_type="audit_recorded",
            source="audit-trail",
            data={
                "sequence": entry.sequence,
                "event_type": entry.event_type,
                "source": entry.source,
                "entry_hash": entry.entry_hash
            },
            timestamp=time.time()
        ))
        
    async def _persist_entry(self, entry: AuditEntry):
        """Persist entry to storage."""
        audit_file = self.storage_path / "audit_log.jsonl"
        try:
            with open(audit_file, "a") as f:
                f.write(json.dumps(entry.to_dict()) + "\n")
        except Exception as e:
            logger.error(f"Failed to persist audit entry: {e}")
            
    def verify_chain(self) -> bool:
        """Verify the integrity of the audit chain."""
        if not self.entries:
            return True
        
        previous_hash = "genesis"
        for entry in self.entries:
            # Verify previous hash link
            if entry.previous_hash != previous_hash:
                logger.error(f"Chain broken at sequence {entry.sequence}")
                return False
            
            # Verify entry hash
            expected_hash = entry._calculate_hash()
            if entry.entry_hash != expected_hash:
                logger.error(f"Hash mismatch at sequence {entry.sequence}")
                return False
            
            previous_hash = entry.entry_hash
        
        logger.info(f"Audit chain verified: {len(self.entries)} entries")
        return True
        
    def get_entries(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Get audit entries."""
        entries = self.entries[offset:offset + limit]
        return [e.to_dict() for e in entries]
        
    def get_by_source(self, source: str, limit: int = 50) -> List[Dict]:
        """Get entries by source."""
        entries = [e for e in self.entries if e.source == source][-limit:]
        return [e.to_dict() for e in entries]


# Singleton
_audit_trail: Optional[AuditTrail] = None


def get_audit_trail() -> AuditTrail:
    """Get the singleton audit trail."""
    global _audit_trail
    if _audit_trail is None:
        _audit_trail = AuditTrail()
    return _audit_trail
