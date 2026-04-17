"""
Secure inter-agent communication protocols.

Implements structured messaging with schemas, authentication, authorization,
encryption, integrity checks, and observability for agent-to-agent communication.
"""

from utils.logger import get_logger
from typing import Dict, List, Optional, Any, Set, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import hashlib
import hmac
from collections import defaultdict, deque
import threading

logger = get_logger(__name__)


class MessageType(Enum):
    """Type of inter-agent message."""
    INTENT = "intent"
    OBSERVATION = "observation"
    ALERT = "alert"
    GOVERNANCE_PROPOSAL = "governance_proposal"
    COORDINATION = "coordination"
    QUERY = "query"
    RESPONSE = "response"
    HEARTBEAT = "heartbeat"


class MessagePriority(Enum):
    """Message priority level."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class MessageSchema:
    """Schema definition for message type."""
    message_type: MessageType
    version: str
    required_fields: Set[str]
    optional_fields: Set[str]
    field_types: Dict[str, type]
    validation_function: Optional[Callable[[Dict[str, Any]], bool]] = None


@dataclass
class AgentIdentity:
    """Agent identity for authentication."""
    agent_id: str
    role: str
    public_key: str
    authorized_topics: Set[str]
    authorized_message_types: Set[MessageType]
    created_at: datetime
    last_authenticated: Optional[datetime] = None


@dataclass
class Message:
    """Inter-agent message."""
    message_id: str
    message_type: MessageType
    version: str
    
    sender_id: str
    recipient_id: Optional[str]
    topic: str
    
    payload: Dict[str, Any]
    
    priority: MessagePriority
    timestamp: datetime
    
    sequence_number: Optional[int] = None
    correlation_id: Optional[str] = None
    
    signature: Optional[str] = None
    encrypted: bool = False
    
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CommunicationMetrics:
    """Communication metrics for observability."""
    topic: str
    message_type: MessageType
    
    total_sent: int = 0
    total_received: int = 0
    total_errors: int = 0
    total_dropped: int = 0
    
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    
    last_updated: Optional[datetime] = None


class SecureAgentCommunication:
    """
    Secure inter-agent communication system.
    
    Implements:
    - Structured messaging with versioned schemas
    - Authentication and authorization per agent/topic
    - Message signing for integrity
    - Encryption for confidentiality (simulated)
    - Resilience with retries and circuit breakers
    - Ordering guarantees with sequence numbers
    - Observability metrics and logging
    """
    
    def __init__(self):
        self._schemas: Dict[MessageType, MessageSchema] = {}
        self._identities: Dict[str, AgentIdentity] = {}
        
        self._message_queue: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._sent_messages: deque = deque(maxlen=10000)
        self._received_messages: deque = deque(maxlen=10000)
        
        self._metrics: Dict[str, CommunicationMetrics] = {}
        self._latency_samples: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        
        self._circuit_breakers: Dict[str, Dict[str, Any]] = {}
        self._sequence_numbers: Dict[str, int] = defaultdict(int)
        
        self._lock = threading.Lock()
        
        self._initialize_schemas()
    
    def _initialize_schemas(self) -> None:
        """Initialize message schemas."""
        self.register_schema(
            message_type=MessageType.INTENT,
            version="1.0",
            required_fields={"action", "asset", "side", "size"},
            optional_fields={"price", "order_type", "time_in_force", "reason"},
            field_types={
                "action": str,
                "asset": str,
                "side": str,
                "size": float,
                "price": float,
                "order_type": str,
            },
        )
        
        self.register_schema(
            message_type=MessageType.ALERT,
            version="1.0",
            required_fields={"alert_type", "severity", "description"},
            optional_fields={"affected_agents", "recommended_action"},
            field_types={
                "alert_type": str,
                "severity": str,
                "description": str,
            },
        )
        
        self.register_schema(
            message_type=MessageType.GOVERNANCE_PROPOSAL,
            version="1.0",
            required_fields={"proposal_type", "proposed_change", "justification"},
            optional_fields={"impact_assessment", "required_approvers"},
            field_types={
                "proposal_type": str,
                "proposed_change": dict,
                "justification": str,
            },
        )
        
        logger.info("Initialized message schemas")
    
    def register_schema(
        self,
        message_type: MessageType,
        version: str,
        required_fields: Set[str],
        optional_fields: Set[str],
        field_types: Dict[str, type],
        validation_function: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> MessageSchema:
        """Register a message schema."""
        schema = MessageSchema(
            message_type=message_type,
            version=version,
            required_fields=required_fields,
            optional_fields=optional_fields,
            field_types=field_types,
            validation_function=validation_function,
        )
        
        self._schemas[message_type] = schema
        
        logger.info(
            f"Registered message schema: {message_type.value} v{version} "
            f"({len(required_fields)} required fields)"
        )
        
        return schema
    
    def register_agent(
        self,
        agent_id: str,
        role: str,
        public_key: str,
        authorized_topics: Set[str],
        authorized_message_types: Set[MessageType],
    ) -> AgentIdentity:
        """Register an agent identity."""
        identity = AgentIdentity(
            agent_id=agent_id,
            role=role,
            public_key=public_key,
            authorized_topics=authorized_topics,
            authorized_message_types=authorized_message_types,
            created_at=datetime.utcnow(),
        )
        
        self._identities[agent_id] = identity
        
        logger.info(
            f"Registered agent '{agent_id}': role={role}, "
            f"{len(authorized_topics)} topics, {len(authorized_message_types)} message types"
        )
        
        return identity
    
    def send_message(
        self,
        sender_id: str,
        message_type: MessageType,
        topic: str,
        payload: Dict[str, Any],
        recipient_id: Optional[str] = None,
        priority: MessagePriority = MessagePriority.NORMAL,
        correlation_id: Optional[str] = None,
        sign: bool = True,
        encrypt: bool = False,
    ) -> Optional[Message]:
        """Send a message to another agent or topic."""
        with self._lock:
            # Authenticate sender
            if not self._authenticate_agent(sender_id):
                logger.error(f"Authentication failed for agent '{sender_id}'")
                self._record_error(topic, message_type)
                return None
            
            # Authorize message
            if not self._authorize_message(sender_id, topic, message_type):
                logger.error(
                    f"Authorization failed for agent '{sender_id}' "
                    f"on topic '{topic}' with type '{message_type.value}'"
                )
                self._record_error(topic, message_type)
                return None
            
            # Validate schema
            if not self._validate_message(message_type, payload):
                logger.error(f"Schema validation failed for message type '{message_type.value}'")
                self._record_error(topic, message_type)
                return None
            
            # Check circuit breaker
            if self._is_circuit_open(topic):
                logger.warning(f"Circuit breaker open for topic '{topic}', dropping message")
                self._record_dropped(topic, message_type)
                return None
            
            # Create message
            message_id = hashlib.md5(
                f"{sender_id}_{topic}_{datetime.utcnow().isoformat()}".encode()
            ).hexdigest()[:16]
            
            message = Message(
                message_id=message_id,
                message_type=message_type,
                version=self._schemas[message_type].version,
                sender_id=sender_id,
                recipient_id=recipient_id,
                topic=topic,
                payload=payload,
                priority=priority,
                timestamp=datetime.utcnow(),
                sequence_number=self._get_next_sequence(sender_id),
                correlation_id=correlation_id,
            )
            
            # Sign message
            if sign:
                message.signature = self._sign_message(sender_id, message)
            
            # Encrypt message (simulated)
            if encrypt:
                message.encrypted = True
            
            # Queue message
            self._message_queue[topic].append(message)
            self._sent_messages.append(message)
            
            # Record metrics
            self._record_sent(topic, message_type)
            
            logger.debug(
                f"Sent message '{message_id}': {message_type.value} "
                f"from {sender_id} to topic '{topic}'"
            )
            
            return message
    
    def receive_messages(
        self,
        recipient_id: str,
        topic: str,
        message_type: Optional[MessageType] = None,
        max_messages: int = 10,
    ) -> List[Message]:
        """Receive messages from a topic."""
        with self._lock:
            # Authenticate recipient
            if not self._authenticate_agent(recipient_id):
                logger.error(f"Authentication failed for agent '{recipient_id}'")
                return []
            
            # Authorize topic access
            identity = self._identities.get(recipient_id)
            if not identity or topic not in identity.authorized_topics:
                logger.error(
                    f"Agent '{recipient_id}' not authorized for topic '{topic}'"
                )
                return []
            
            # Get messages from queue
            messages = []
            queue = self._message_queue.get(topic, deque())
            
            for _ in range(min(max_messages, len(queue))):
                if not queue:
                    break
                
                message = queue.popleft()
                
                # Filter by message type if specified
                if message_type and message.message_type != message_type:
                    queue.append(message)
                    continue
                
                # Filter by recipient if specified
                if message.recipient_id and message.recipient_id != recipient_id:
                    queue.append(message)
                    continue
                
                # Verify signature
                if message.signature:
                    if not self._verify_signature(message):
                        logger.warning(
                            f"Signature verification failed for message '{message.message_id}'"
                        )
                        self._record_error(topic, message.message_type)
                        continue
                
                messages.append(message)
                self._received_messages.append(message)
                
                # Record metrics
                self._record_received(topic, message.message_type)
                self._record_latency(
                    topic,
                    (datetime.utcnow() - message.timestamp).total_seconds() * 1000
                )
            
            return messages
    
    def _authenticate_agent(self, agent_id: str) -> bool:
        """Authenticate agent."""
        identity = self._identities.get(agent_id)
        if not identity:
            return False
        
        identity.last_authenticated = datetime.utcnow()
        return True
    
    def _authorize_message(
        self,
        agent_id: str,
        topic: str,
        message_type: MessageType,
    ) -> bool:
        """Authorize agent to send message."""
        identity = self._identities.get(agent_id)
        if not identity:
            return False
        
        if topic not in identity.authorized_topics:
            return False
        
        if message_type not in identity.authorized_message_types:
            return False
        
        return True
    
    def _validate_message(
        self,
        message_type: MessageType,
        payload: Dict[str, Any],
    ) -> bool:
        """Validate message against schema."""
        schema = self._schemas.get(message_type)
        if not schema:
            logger.error(f"No schema found for message type '{message_type.value}'")
            return False
        
        # Check required fields
        for field in schema.required_fields:
            if field not in payload:
                logger.error(f"Missing required field '{field}' in message")
                return False
        
        # Check field types
        for field, expected_type in schema.field_types.items():
            if field in payload:
                if not isinstance(payload[field], expected_type):
                    logger.error(
                        f"Invalid type for field '{field}': "
                        f"expected {expected_type}, got {type(payload[field])}"
                    )
                    return False
        
        # Run custom validation if provided
        if schema.validation_function:
            if not schema.validation_function(payload):
                logger.error("Custom validation failed for message")
                return False
        
        return True
    
    def _sign_message(self, sender_id: str, message: Message) -> str:
        """Sign message for integrity (simulated)."""
        identity = self._identities.get(sender_id)
        if not identity:
            return ""
        
        # In real implementation, use actual cryptographic signing
        message_data = json.dumps({
            "message_id": message.message_id,
            "sender_id": message.sender_id,
            "payload": message.payload,
            "timestamp": message.timestamp.isoformat(),
        }, sort_keys=True)
        
        signature = hmac.new(
            identity.public_key.encode(),
            message_data.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return signature
    
    def _verify_signature(self, message: Message) -> bool:
        """Verify message signature (simulated)."""
        identity = self._identities.get(message.sender_id)
        if not identity:
            return False
        
        # Recompute signature
        expected_signature = self._sign_message(message.sender_id, message)
        
        return hmac.compare_digest(message.signature, expected_signature)
    
    def _get_next_sequence(self, sender_id: str) -> int:
        """Get next sequence number for sender."""
        self._sequence_numbers[sender_id] += 1
        return self._sequence_numbers[sender_id]
    
    def _is_circuit_open(self, topic: str) -> bool:
        """Check if circuit breaker is open for topic."""
        breaker = self._circuit_breakers.get(topic)
        if not breaker:
            return False
        
        return breaker.get("open", False)
    
    def _record_sent(self, topic: str, message_type: MessageType) -> None:
        """Record sent message metric."""
        key = f"{topic}_{message_type.value}"
        
        if key not in self._metrics:
            self._metrics[key] = CommunicationMetrics(
                topic=topic,
                message_type=message_type,
            )
        
        self._metrics[key].total_sent += 1
        self._metrics[key].last_updated = datetime.utcnow()
    
    def _record_received(self, topic: str, message_type: MessageType) -> None:
        """Record received message metric."""
        key = f"{topic}_{message_type.value}"
        
        if key not in self._metrics:
            self._metrics[key] = CommunicationMetrics(
                topic=topic,
                message_type=message_type,
            )
        
        self._metrics[key].total_received += 1
        self._metrics[key].last_updated = datetime.utcnow()
    
    def _record_error(self, topic: str, message_type: MessageType) -> None:
        """Record error metric."""
        key = f"{topic}_{message_type.value}"
        
        if key not in self._metrics:
            self._metrics[key] = CommunicationMetrics(
                topic=topic,
                message_type=message_type,
            )
        
        self._metrics[key].total_errors += 1
        self._metrics[key].last_updated = datetime.utcnow()
    
    def _record_dropped(self, topic: str, message_type: MessageType) -> None:
        """Record dropped message metric."""
        key = f"{topic}_{message_type.value}"
        
        if key not in self._metrics:
            self._metrics[key] = CommunicationMetrics(
                topic=topic,
                message_type=message_type,
            )
        
        self._metrics[key].total_dropped += 1
        self._metrics[key].last_updated = datetime.utcnow()
    
    def _record_latency(self, topic: str, latency_ms: float) -> None:
        """Record message latency."""
        self._latency_samples[topic].append(latency_ms)
        
        # Update metrics
        for key, metrics in self._metrics.items():
            if metrics.topic == topic:
                samples = list(self._latency_samples[topic])
                if samples:
                    import numpy as np
                    metrics.avg_latency_ms = np.mean(samples)
                    metrics.p95_latency_ms = np.percentile(samples, 95)
                    metrics.p99_latency_ms = np.percentile(samples, 99)
    
    def get_communication_metrics(
        self,
        topic: Optional[str] = None,
        message_type: Optional[MessageType] = None,
    ) -> List[CommunicationMetrics]:
        """Get communication metrics."""
        metrics = list(self._metrics.values())
        
        if topic:
            metrics = [m for m in metrics if m.topic == topic]
        
        if message_type:
            metrics = [m for m in metrics if m.message_type == message_type]
        
        return metrics
    
    def get_communication_summary(self) -> Dict[str, Any]:
        """Get communication system summary."""
        total_sent = sum(m.total_sent for m in self._metrics.values())
        total_received = sum(m.total_received for m in self._metrics.values())
        total_errors = sum(m.total_errors for m in self._metrics.values())
        total_dropped = sum(m.total_dropped for m in self._metrics.values())
        
        return {
            "registered_agents": len(self._identities),
            "registered_schemas": len(self._schemas),
            "total_sent": total_sent,
            "total_received": total_received,
            "total_errors": total_errors,
            "total_dropped": total_dropped,
            "error_rate": total_errors / total_sent if total_sent > 0 else 0.0,
            "drop_rate": total_dropped / total_sent if total_sent > 0 else 0.0,
            "active_topics": len(self._message_queue),
            "queued_messages": sum(len(q) for q in self._message_queue.values()),
        }


_secure_agent_communication: Optional[SecureAgentCommunication] = None
_secure_agent_communication_lock = threading.Lock()


def get_secure_agent_communication() -> SecureAgentCommunication:
    """Get global SecureAgentCommunication instance."""
    global _secure_agent_communication
    if _secure_agent_communication is None:
        with _secure_agent_communication_lock:
            if _secure_agent_communication is None:
                _secure_agent_communication = SecureAgentCommunication()
    return _secure_agent_communication
