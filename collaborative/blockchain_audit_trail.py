"""
Blockchain-based audit trail emitter.

Creates hashed audit entries with chain metadata so collaboration workflows can
anchor events (registrations, tasks, FL rounds) to an immutable ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List
import hashlib


@dataclass
class AuditEvent:
    event_id: str
    event_type: str
    payload_hash: str
    chain: str
    tx_hash: str
    timestamp: datetime


class BlockchainAuditTrail:
    def __init__(self) -> None:
        self._events: List[AuditEvent] = []

    def record_event(self, event_type: str, payload: Dict[str, str], chain: str = "merid-chain") -> AuditEvent:
        payload_hash = hashlib.sha256(str(sorted(payload.items())).encode()).hexdigest()
        tx_hash = hashlib.sha256(f"{event_type}:{payload_hash}:{datetime.utcnow().isoformat()}".encode()).hexdigest()
        event = AuditEvent(
            event_id=f"audit_{len(self._events)+1}",
            event_type=event_type,
            payload_hash=payload_hash,
            chain=chain,
            tx_hash=tx_hash,
            timestamp=datetime.utcnow(),
        )
        self._events.append(event)
        return event

    def recent_events(self, limit: int = 20) -> List[AuditEvent]:
        return self._events[-limit:]
