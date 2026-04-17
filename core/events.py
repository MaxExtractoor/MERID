"""
EventEnvelope - Canonical event schema per MASTER_SPEC v1.0

This module defines the foundational event wrapper for ALL system messages.
It enforces event typing, deterministic serialization, idempotency,
trace IDs, and replay safety.

Reference: MASTER_SPEC.md Section 5.1
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, Optional, Union

from utils.logger import get_logger

logger = get_logger("core.events")


class EventType(Enum):
    """Canonical event types in MERID system."""
    
    MARKET_DATA = "market_data"
    NEWS = "news"
    SOCIAL = "social"
    ONCHAIN = "onchain"
    AGENT_OUTPUT = "agent_output"
    CONSENSUS = "consensus"
    EXECUTION = "execution"
    SIMULATION = "simulation"
    SYSTEM = "system"
    AUDIT = "audit"
    HEARTBEAT = "heartbeat"
    ERROR = "error"


class EventPriority(Enum):
    """Event priority levels for processing order."""
    
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


@dataclass
class EventMetadata:
    """
    Metadata attached to events for traceability and routing.
    """
    
    schema_version: str = "1.0"
    producer_id: str = ""
    producer_type: str = ""
    environment: str = "production"
    region: str = "default"
    partition_key: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    ttl_seconds: Optional[int] = None
    tags: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, object]:
        """Convert to dictionary for serialization."""
        return {
            "schema_version": self.schema_version,
            "producer_id": self.producer_id,
            "producer_type": self.producer_type,
            "environment": self.environment,
            "region": self.region,
            "partition_key": self.partition_key,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "ttl_seconds": self.ttl_seconds,
            "tags": self.tags,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> EventMetadata:
        """Create from dictionary."""
        return cls(
            schema_version=str(data.get("schema_version", "1.0")),
            producer_id=str(data.get("producer_id", "")),
            producer_type=str(data.get("producer_type", "")),
            environment=str(data.get("environment", "production")),
            region=str(data.get("region", "default")),
            partition_key=data.get("partition_key"),  # type: ignore
            retry_count=int(data.get("retry_count", 0)),
            max_retries=int(data.get("max_retries", 3)),
            ttl_seconds=data.get("ttl_seconds"),  # type: ignore
            tags=dict(data.get("tags", {})),  # type: ignore
        )


@dataclass
class EventEnvelope:
    """
    Canonical event wrapper for all system messages.
    
    This is the foundational schema for all events flowing through MERID.
    Every event MUST be wrapped in an EventEnvelope for:
    - Consistent typing and validation
    - Traceability via correlation/causation IDs
    - Idempotency via deterministic event IDs
    - Replay safety via sequence numbers
    - Audit trail via signatures
    
    Reference: MASTER_SPEC.md Section 5.1
    
    Immutability: Once created, event_id and timestamp are frozen.
    Payload should be treated as immutable after creation.
    """
    
    event_type: EventType
    source: str
    payload: Dict[str, object]
    
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    sequence_number: Optional[int] = None
    
    priority: EventPriority = EventPriority.NORMAL
    metadata: EventMetadata = field(default_factory=EventMetadata)
    
    signature: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validate envelope after creation."""
        if not self.source:
            raise ValueError("source cannot be empty")
        if not isinstance(self.event_type, EventType):
            raise TypeError(f"event_type must be EventType, got {type(self.event_type)}")
        if not isinstance(self.payload, dict):
            raise TypeError(f"payload must be dict, got {type(self.payload)}")
    
    def validate(self) -> bool:
        """
        Validate envelope structure and constraints.
        
        Returns:
            True if valid, False otherwise
        """
        if not self.event_id:
            logger.warning("Validation failed: empty event_id")
            return False
        if not self.source:
            logger.warning("Validation failed: empty source")
            return False
        if self.timestamp <= 0:
            logger.warning("Validation failed: invalid timestamp %f", self.timestamp)
            return False
        if not isinstance(self.payload, dict):
            logger.warning("Validation failed: payload is not dict")
            return False
        return True
    
    def is_expired(self) -> bool:
        """
        Check if event has expired based on TTL.
        
        Returns:
            True if expired, False otherwise
        """
        if self.metadata.ttl_seconds is None:
            return False
        age_seconds = time.time() - self.timestamp
        return age_seconds > self.metadata.ttl_seconds
    
    def can_retry(self) -> bool:
        """
        Check if event can be retried.
        
        Returns:
            True if retry count < max retries
        """
        return self.metadata.retry_count < self.metadata.max_retries
    
    def increment_retry(self) -> EventEnvelope:
        """
        Create new envelope with incremented retry count.
        
        Returns:
            New EventEnvelope with retry_count + 1
        """
        new_metadata = EventMetadata(
            schema_version=self.metadata.schema_version,
            producer_id=self.metadata.producer_id,
            producer_type=self.metadata.producer_type,
            environment=self.metadata.environment,
            region=self.metadata.region,
            partition_key=self.metadata.partition_key,
            retry_count=self.metadata.retry_count + 1,
            max_retries=self.metadata.max_retries,
            ttl_seconds=self.metadata.ttl_seconds,
            tags=dict(self.metadata.tags),
        )
        return EventEnvelope(
            event_type=self.event_type,
            source=self.source,
            payload=dict(self.payload),
            event_id=self.event_id,
            timestamp=self.timestamp,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
            sequence_number=self.sequence_number,
            priority=self.priority,
            metadata=new_metadata,
            signature=None,
        )
    
    def with_causation(self, parent_event_id: str) -> EventEnvelope:
        """
        Create derived event with causation chain.
        
        Args:
            parent_event_id: ID of the event that caused this one
            
        Returns:
            New EventEnvelope with causation_id set
        """
        return EventEnvelope(
            event_type=self.event_type,
            source=self.source,
            payload=dict(self.payload),
            event_id=str(uuid.uuid4()),
            timestamp=time.time(),
            correlation_id=self.correlation_id or parent_event_id,
            causation_id=parent_event_id,
            sequence_number=None,
            priority=self.priority,
            metadata=self.metadata,
            signature=None,
        )
    
    def compute_hash(self) -> str:
        """
        Compute deterministic hash of event content.
        
        Used for idempotency checks and deduplication.
        
        Returns:
            SHA-256 hash of canonical event representation
        """
        canonical = {
            "event_type": self.event_type.value,
            "source": self.source,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }
        canonical_json = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    
    def sign(self, secret_key: str) -> str:
        """
        Sign event with HMAC for authenticity.
        
        Args:
            secret_key: Secret key for HMAC signing
            
        Returns:
            HMAC signature
        """
        import hmac
        content_hash = self.compute_hash()
        signature = hmac.new(
            secret_key.encode("utf-8"),
            content_hash.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        self.signature = signature
        return signature
    
    def verify_signature(self, secret_key: str) -> bool:
        """
        Verify event signature.
        
        Args:
            secret_key: Secret key for HMAC verification
            
        Returns:
            True if signature is valid
        """
        if not self.signature:
            return False
        import hmac
        content_hash = self.compute_hash()
        expected = hmac.new(
            secret_key.encode("utf-8"),
            content_hash.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(self.signature, expected)
    
    def to_dict(self) -> Dict[str, object]:
        """
        Serialize to dictionary for JSON encoding.
        
        Returns:
            Dictionary representation
        """
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "source": self.source,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "sequence_number": self.sequence_number,
            "priority": self.priority.value,
            "metadata": self.metadata.to_dict(),
            "signature": self.signature,
        }
    
    def to_json(self) -> str:
        """
        Serialize to JSON string.
        
        Returns:
            JSON string representation
        """
        return json.dumps(self.to_dict(), separators=(",", ":"))
    
    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> EventEnvelope:
        """
        Deserialize from dictionary.
        
        Args:
            data: Dictionary representation
            
        Returns:
            EventEnvelope instance
        """
        event_type_str = str(data.get("event_type", "system"))
        try:
            event_type = EventType(event_type_str)
        except ValueError:
            logger.warning("Unknown event_type '%s', defaulting to SYSTEM", event_type_str)
            event_type = EventType.SYSTEM
        
        priority_val = data.get("priority", EventPriority.NORMAL.value)
        if isinstance(priority_val, int):
            try:
                priority = EventPriority(priority_val)
            except ValueError:
                priority = EventPriority.NORMAL
        else:
            priority = EventPriority.NORMAL
        
        metadata_data = data.get("metadata", {})
        if isinstance(metadata_data, dict):
            metadata = EventMetadata.from_dict(metadata_data)
        else:
            metadata = EventMetadata()
        
        return cls(
            event_id=str(data.get("event_id", str(uuid.uuid4()))),
            event_type=event_type,
            source=str(data.get("source", "")),
            timestamp=float(data.get("timestamp", time.time())),
            payload=dict(data.get("payload", {})),  # type: ignore
            correlation_id=data.get("correlation_id"),  # type: ignore
            causation_id=data.get("causation_id"),  # type: ignore
            sequence_number=data.get("sequence_number"),  # type: ignore
            priority=priority,
            metadata=metadata,
            signature=data.get("signature"),  # type: ignore
        )
    
    @classmethod
    def from_json(cls, json_str: str) -> EventEnvelope:
        """
        Deserialize from JSON string.
        
        Args:
            json_str: JSON string representation
            
        Returns:
            EventEnvelope instance
            
        Raises:
            json.JSONDecodeError: If JSON is invalid
        """
        data = json.loads(json_str)
        return cls.from_dict(data)


def create_market_event(
    source: str,
    symbol: str,
    price: float,
    volume: float,
    correlation_id: Optional[str] = None,
) -> EventEnvelope:
    """
    Factory function for market data events.
    
    Args:
        source: Data source (e.g., "coinbase", "binance")
        symbol: Trading symbol (e.g., "BTC/USDT")
        price: Current price
        volume: Trading volume
        correlation_id: Optional correlation ID
        
    Returns:
        EventEnvelope with market data
    """
    return EventEnvelope(
        event_type=EventType.MARKET_DATA,
        source=source,
        payload={
            "symbol": symbol,
            "price": price,
            "volume": volume,
            "timestamp": time.time(),
        },
        correlation_id=correlation_id,
        priority=EventPriority.HIGH,
    )


def create_agent_output_event(
    agent_id: str,
    output_type: str,
    content: Dict[str, object],
    correlation_id: Optional[str] = None,
) -> EventEnvelope:
    """
    Factory function for agent output events.
    
    Args:
        agent_id: ID of the producing agent
        output_type: Type of output (e.g., "analysis", "vote", "alert")
        content: Output content
        correlation_id: Optional correlation ID
        
    Returns:
        EventEnvelope with agent output
    """
    return EventEnvelope(
        event_type=EventType.AGENT_OUTPUT,
        source=agent_id,
        payload={
            "output_type": output_type,
            "content": content,
            "agent_id": agent_id,
        },
        correlation_id=correlation_id,
        priority=EventPriority.NORMAL,
    )


def create_consensus_event(
    round_id: str,
    state: str,
    votes: Dict[str, object],
    result: Optional[str] = None,
) -> EventEnvelope:
    """
    Factory function for consensus events.
    
    Args:
        round_id: Consensus round ID
        state: Current consensus state
        votes: Vote summary
        result: Final result if consensus reached
        
    Returns:
        EventEnvelope with consensus data
    """
    return EventEnvelope(
        event_type=EventType.CONSENSUS,
        source="consensus_engine",
        payload={
            "round_id": round_id,
            "state": state,
            "votes": votes,
            "result": result,
        },
        priority=EventPriority.HIGH,
    )


def create_audit_event(
    action: str,
    actor: str,
    details: Dict[str, object],
    severity: str = "info",
) -> EventEnvelope:
    """
    Factory function for audit trail events.
    
    Args:
        action: Action being audited
        actor: Entity performing the action
        details: Additional details
        severity: Severity level (info, warning, error, critical)
        
    Returns:
        EventEnvelope for audit trail
    """
    return EventEnvelope(
        event_type=EventType.AUDIT,
        source="audit_system",
        payload={
            "action": action,
            "actor": actor,
            "details": details,
            "severity": severity,
        },
        priority=EventPriority.LOW,
    )
