"""
IntentEnvelope Schema - The canonical trading intent structure.

An IntentEnvelope represents a complete, self-contained trading intention
that flows through the MERID system from creation to execution.

Version: 1.0.0
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional, Any


class IntentType(Enum):
    """Types of trading intents."""
    SPOT_BUY = "spot_buy"
    SPOT_SELL = "spot_sell"
    PERP_LONG = "perp_long"
    PERP_SHORT = "perp_short"
    PERP_CLOSE = "perp_close"
    ARBITRAGE = "arbitrage"
    REBALANCE = "rebalance"
    HEDGE = "hedge"
    TREASURY_MOVE = "treasury_move"
    PREDICTION_BET = "prediction_bet"
    SNIPE = "snipe"


class IntentStatus(Enum):
    """Lifecycle status of an intent."""
    DRAFT = "draft"                    # Created, not yet submitted
    PENDING_CONSENSUS = "pending_consensus"  # Awaiting agent votes
    APPROVED = "approved"              # Consensus reached, ready for execution
    REJECTED = "rejected"              # Consensus rejected
    VETOED = "vetoed"                  # Risk agent vetoed
    PENDING_EXECUTION = "pending_execution"  # Approved, awaiting execution
    EXECUTING = "executing"            # Currently being executed
    PARTIALLY_FILLED = "partially_filled"  # Some fills received
    FILLED = "filled"                  # Fully executed
    FAILED = "failed"                  # Execution failed
    CANCELLED = "cancelled"            # User cancelled
    EXPIRED = "expired"                # TTL exceeded


class IntentPriority(Enum):
    """Execution priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


@dataclass
class IntentMetadata:
    """Metadata attached to an intent."""
    source_agent: Optional[str] = None
    source_signal: Optional[str] = None
    strategy_id: Optional[str] = None
    parent_intent_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    custom: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IntentConstraints:
    """Execution constraints for an intent."""
    max_slippage_pct: float = 0.01      # 1% default
    min_fill_pct: float = 0.0           # 0% = allow partial
    ttl_seconds: int = 300              # 5 minute default TTL
    require_simulation: bool = True
    require_consensus: bool = True
    min_consensus_confidence: float = 0.65
    allowed_venues: List[str] = field(default_factory=list)
    blocked_venues: List[str] = field(default_factory=list)
    max_gas_gwei: Optional[float] = None
    max_priority_fee_gwei: Optional[float] = None


@dataclass
class IntentEnvelope:
    """
    The canonical trading intent structure.
    
    This is the single source of truth for any trading action in MERID.
    All intents are:
    - Immutable once created (new version = new intent)
    - Hashable for audit trail
    - Self-contained with all execution parameters
    - Traceable through the entire lifecycle
    """
    
    # Identity
    intent_id: str = field(default_factory=lambda: f"intent_{uuid.uuid4().hex[:16]}")
    version: int = 1
    
    # Core intent
    intent_type: IntentType = IntentType.SPOT_BUY
    symbol: str = ""
    side: str = "buy"  # buy, sell, long, short
    quantity: float = 0.0
    quantity_type: str = "base"  # base, quote, percent
    
    # Pricing
    order_type: str = "market"  # market, limit, stop_market, stop_limit
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    
    # Risk management
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    leverage: int = 1
    
    # Status
    status: IntentStatus = IntentStatus.DRAFT
    priority: IntentPriority = IntentPriority.NORMAL
    
    # Timestamps
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    
    # Constraints
    constraints: IntentConstraints = field(default_factory=IntentConstraints)
    
    # Metadata
    metadata: IntentMetadata = field(default_factory=IntentMetadata)
    
    # Audit
    creator_id: str = "system"
    approver_ids: List[str] = field(default_factory=list)
    rejection_reason: Optional[str] = None
    
    # Execution tracking
    execution_id: Optional[str] = None
    filled_quantity: float = 0.0
    avg_fill_price: Optional[float] = None
    total_fees: float = 0.0
    
    def __post_init__(self):
        """Set expiration based on TTL if not set."""
        if self.expires_at is None:
            self.expires_at = self.created_at + self.constraints.ttl_seconds
    
    def compute_hash(self) -> str:
        """Compute deterministic hash of the intent for audit."""
        # Only hash immutable fields
        hash_data = {
            "intent_id": self.intent_id,
            "version": self.version,
            "intent_type": self.intent_type.value,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "quantity_type": self.quantity_type,
            "order_type": self.order_type,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "leverage": self.leverage,
            "created_at": self.created_at,
            "creator_id": self.creator_id,
        }
        json_str = json.dumps(hash_data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(json_str.encode()).hexdigest()[:16]
    
    def is_expired(self) -> bool:
        """Check if intent has expired."""
        return time.time() > self.expires_at if self.expires_at else False
    
    def is_terminal(self) -> bool:
        """Check if intent is in a terminal state."""
        return self.status in [
            IntentStatus.FILLED,
            IntentStatus.FAILED,
            IntentStatus.CANCELLED,
            IntentStatus.EXPIRED,
            IntentStatus.REJECTED,
            IntentStatus.VETOED,
        ]
    
    def can_execute(self) -> bool:
        """Check if intent can be executed."""
        return (
            self.status == IntentStatus.APPROVED and
            not self.is_expired() and
            self.quantity > 0
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "intent_id": self.intent_id,
            "version": self.version,
            "intent_type": self.intent_type.value,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "quantity_type": self.quantity_type,
            "order_type": self.order_type,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "leverage": self.leverage,
            "status": self.status.value,
            "priority": self.priority.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "constraints": asdict(self.constraints),
            "metadata": asdict(self.metadata),
            "creator_id": self.creator_id,
            "approver_ids": self.approver_ids,
            "rejection_reason": self.rejection_reason,
            "execution_id": self.execution_id,
            "filled_quantity": self.filled_quantity,
            "avg_fill_price": self.avg_fill_price,
            "total_fees": self.total_fees,
            "hash": self.compute_hash(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IntentEnvelope":
        """Create from dictionary."""
        constraints_data = data.get("constraints", {})
        metadata_data = data.get("metadata", {})
        
        return cls(
            intent_id=data.get("intent_id", f"intent_{uuid.uuid4().hex[:16]}"),
            version=data.get("version", 1),
            intent_type=IntentType(data.get("intent_type", "spot_buy")),
            symbol=data.get("symbol", ""),
            side=data.get("side", "buy"),
            quantity=data.get("quantity", 0.0),
            quantity_type=data.get("quantity_type", "base"),
            order_type=data.get("order_type", "market"),
            limit_price=data.get("limit_price"),
            stop_price=data.get("stop_price"),
            stop_loss_pct=data.get("stop_loss_pct"),
            take_profit_pct=data.get("take_profit_pct"),
            leverage=data.get("leverage", 1),
            status=IntentStatus(data.get("status", "draft")),
            priority=IntentPriority(data.get("priority", "normal")),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            expires_at=data.get("expires_at"),
            constraints=IntentConstraints(**constraints_data) if constraints_data else IntentConstraints(),
            metadata=IntentMetadata(**metadata_data) if metadata_data else IntentMetadata(),
            creator_id=data.get("creator_id", "system"),
            approver_ids=data.get("approver_ids", []),
            rejection_reason=data.get("rejection_reason"),
            execution_id=data.get("execution_id"),
            filled_quantity=data.get("filled_quantity", 0.0),
            avg_fill_price=data.get("avg_fill_price"),
            total_fees=data.get("total_fees", 0.0),
        )
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_json(cls, json_str: str) -> "IntentEnvelope":
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))
