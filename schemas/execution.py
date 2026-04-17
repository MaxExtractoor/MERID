"""
ExecutionResult Schema - Canonical execution result structure.

Records the complete outcome of any execution attempt, including
all fills, fees, and error information.

Version: 1.0.0
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


class ExecutionStatus(Enum):
    """Status of an execution."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


class ExecutionVenue(Enum):
    """Where execution occurred."""
    PAPER = "paper"
    CEX_SPOT = "cex_spot"
    CEX_PERP = "cex_perp"
    DEX_SPOT = "dex_spot"
    DEX_PERP = "dex_perp"
    OTC = "otc"
    PREDICTION = "prediction"


class FailureReason(Enum):
    """Reasons for execution failure."""
    NONE = "none"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    INSUFFICIENT_MARGIN = "insufficient_margin"
    PRICE_MOVED = "price_moved"
    SLIPPAGE_EXCEEDED = "slippage_exceeded"
    RATE_LIMITED = "rate_limited"
    EXCHANGE_ERROR = "exchange_error"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    REJECTED_BY_EXCHANGE = "rejected_by_exchange"
    INVALID_ORDER = "invalid_order"
    MARKET_CLOSED = "market_closed"
    KILL_SWITCH_TRIGGERED = "kill_switch_triggered"
    MANUAL_CANCEL = "manual_cancel"
    UNKNOWN = "unknown"


@dataclass
class OrderFill:
    """A single fill event for an order."""
    fill_id: str = field(default_factory=lambda: f"fill_{uuid.uuid4().hex[:8]}")
    
    # Fill details
    quantity: float = 0.0
    price: float = 0.0
    value: float = 0.0  # quantity * price
    
    # Fees
    fee: float = 0.0
    fee_currency: str = "USDT"
    
    # Timing
    timestamp: float = field(default_factory=time.time)
    
    # Venue info
    venue: str = ""
    venue_order_id: str = ""
    venue_trade_id: str = ""
    
    # For on-chain
    tx_hash: Optional[str] = None
    block_number: Optional[int] = None
    gas_used: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "fill_id": self.fill_id,
            "quantity": self.quantity,
            "price": self.price,
            "value": self.value,
            "fee": self.fee,
            "fee_currency": self.fee_currency,
            "timestamp": self.timestamp,
            "venue": self.venue,
            "venue_order_id": self.venue_order_id,
            "venue_trade_id": self.venue_trade_id,
            "tx_hash": self.tx_hash,
            "block_number": self.block_number,
            "gas_used": self.gas_used,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrderFill":
        return cls(
            fill_id=data.get("fill_id", f"fill_{uuid.uuid4().hex[:8]}"),
            quantity=data.get("quantity", 0.0),
            price=data.get("price", 0.0),
            value=data.get("value", 0.0),
            fee=data.get("fee", 0.0),
            fee_currency=data.get("fee_currency", "USDT"),
            timestamp=data.get("timestamp", time.time()),
            venue=data.get("venue", ""),
            venue_order_id=data.get("venue_order_id", ""),
            venue_trade_id=data.get("venue_trade_id", ""),
            tx_hash=data.get("tx_hash"),
            block_number=data.get("block_number"),
            gas_used=data.get("gas_used"),
        )


@dataclass
class ExecutionResult:
    """
    Complete record of an execution attempt.
    
    This is the canonical structure for any execution result in MERID.
    Immutable once finalized.
    """
    
    # Identity
    execution_id: str = field(default_factory=lambda: f"exec_{uuid.uuid4().hex[:12]}")
    
    # Link to intent
    intent_id: str = ""
    intent_hash: str = ""
    
    # Status
    status: ExecutionStatus = ExecutionStatus.PENDING
    failure_reason: FailureReason = FailureReason.NONE
    error_message: str = ""
    
    # Order details
    symbol: str = ""
    side: str = "buy"
    order_type: str = "market"
    requested_quantity: float = 0.0
    requested_price: Optional[float] = None
    
    # Venue
    venue: ExecutionVenue = ExecutionVenue.PAPER
    venue_name: str = ""
    venue_order_id: str = ""
    
    # Fills
    fills: List[OrderFill] = field(default_factory=list)
    
    # Aggregated results
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    total_value: float = 0.0
    total_fees: float = 0.0
    total_gas: float = 0.0
    
    # Slippage
    expected_price: Optional[float] = None
    actual_slippage_pct: float = 0.0
    
    # P&L (for closing trades)
    realized_pnl: Optional[float] = None
    realized_pnl_pct: Optional[float] = None
    
    # Timing
    created_at: float = field(default_factory=time.time)
    submitted_at: Optional[float] = None
    first_fill_at: Optional[float] = None
    completed_at: Optional[float] = None
    latency_ms: float = 0.0
    
    # Metadata
    retry_count: int = 0
    max_retries: int = 3
    notes: str = ""
    
    def compute_hash(self) -> str:
        """Compute deterministic hash of the execution result."""
        hash_data = {
            "execution_id": self.execution_id,
            "intent_id": self.intent_id,
            "symbol": self.symbol,
            "side": self.side,
            "filled_quantity": self.filled_quantity,
            "avg_fill_price": self.avg_fill_price,
            "status": self.status.value,
            "created_at": self.created_at,
        }
        json_str = json.dumps(hash_data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(json_str.encode()).hexdigest()[:16]
    
    def add_fill(self, fill: OrderFill) -> None:
        """Add a fill and update aggregates."""
        self.fills.append(fill)
        
        # Update first fill time
        if self.first_fill_at is None:
            self.first_fill_at = fill.timestamp
        
        # Recalculate aggregates
        self._recalculate_aggregates()
        
        # Update status
        if self.filled_quantity >= self.requested_quantity:
            self.status = ExecutionStatus.FILLED
            self.completed_at = time.time()
        elif self.filled_quantity > 0:
            self.status = ExecutionStatus.PARTIALLY_FILLED
    
    def _recalculate_aggregates(self) -> None:
        """Recalculate aggregate values from fills."""
        if not self.fills:
            return
        
        self.filled_quantity = sum(f.quantity for f in self.fills)
        self.total_value = sum(f.value for f in self.fills)
        self.total_fees = sum(f.fee for f in self.fills)
        self.total_gas = sum(f.gas_used or 0 for f in self.fills)
        
        if self.filled_quantity > 0:
            self.avg_fill_price = self.total_value / self.filled_quantity
        
        # Calculate slippage
        if self.expected_price and self.avg_fill_price:
            self.actual_slippage_pct = abs(
                (self.avg_fill_price - self.expected_price) / self.expected_price
            ) * 100
    
    def finalize(self, status: ExecutionStatus, reason: FailureReason = FailureReason.NONE) -> None:
        """Finalize the execution with final status."""
        self.status = status
        self.failure_reason = reason
        self.completed_at = time.time()
        
        if self.submitted_at:
            self.latency_ms = (self.completed_at - self.submitted_at) * 1000
    
    def fill_percentage(self) -> float:
        """Get fill percentage."""
        if self.requested_quantity <= 0:
            return 0.0
        return (self.filled_quantity / self.requested_quantity) * 100
    
    def is_complete(self) -> bool:
        """Check if execution is complete (success or failure)."""
        return self.status in [
            ExecutionStatus.FILLED,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.REJECTED,
            ExecutionStatus.EXPIRED,
            ExecutionStatus.FAILED,
        ]
    
    def is_successful(self) -> bool:
        """Check if execution was successful."""
        return self.status == ExecutionStatus.FILLED
    
    def net_cost(self) -> float:
        """Total cost including fees and gas."""
        return self.total_value + self.total_fees + self.total_gas
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "hash": self.compute_hash(),
            "intent_id": self.intent_id,
            "intent_hash": self.intent_hash,
            "status": self.status.value,
            "failure_reason": self.failure_reason.value,
            "error_message": self.error_message,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "requested_quantity": self.requested_quantity,
            "requested_price": self.requested_price,
            "venue": self.venue.value,
            "venue_name": self.venue_name,
            "venue_order_id": self.venue_order_id,
            "fills": [f.to_dict() for f in self.fills],
            "filled_quantity": self.filled_quantity,
            "avg_fill_price": self.avg_fill_price,
            "total_value": self.total_value,
            "total_fees": self.total_fees,
            "total_gas": self.total_gas,
            "expected_price": self.expected_price,
            "actual_slippage_pct": self.actual_slippage_pct,
            "realized_pnl": self.realized_pnl,
            "realized_pnl_pct": self.realized_pnl_pct,
            "created_at": self.created_at,
            "submitted_at": self.submitted_at,
            "first_fill_at": self.first_fill_at,
            "completed_at": self.completed_at,
            "latency_ms": self.latency_ms,
            "fill_percentage": self.fill_percentage(),
            "is_complete": self.is_complete(),
            "is_successful": self.is_successful(),
            "net_cost": self.net_cost(),
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "notes": self.notes,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionResult":
        fills = [OrderFill.from_dict(f) for f in data.get("fills", [])]
        
        return cls(
            execution_id=data.get("execution_id", f"exec_{uuid.uuid4().hex[:12]}"),
            intent_id=data.get("intent_id", ""),
            intent_hash=data.get("intent_hash", ""),
            status=ExecutionStatus(data.get("status", "pending")),
            failure_reason=FailureReason(data.get("failure_reason", "none")),
            error_message=data.get("error_message", ""),
            symbol=data.get("symbol", ""),
            side=data.get("side", "buy"),
            order_type=data.get("order_type", "market"),
            requested_quantity=data.get("requested_quantity", 0.0),
            requested_price=data.get("requested_price"),
            venue=ExecutionVenue(data.get("venue", "paper")),
            venue_name=data.get("venue_name", ""),
            venue_order_id=data.get("venue_order_id", ""),
            fills=fills,
            filled_quantity=data.get("filled_quantity", 0.0),
            avg_fill_price=data.get("avg_fill_price", 0.0),
            total_value=data.get("total_value", 0.0),
            total_fees=data.get("total_fees", 0.0),
            total_gas=data.get("total_gas", 0.0),
            expected_price=data.get("expected_price"),
            actual_slippage_pct=data.get("actual_slippage_pct", 0.0),
            realized_pnl=data.get("realized_pnl"),
            realized_pnl_pct=data.get("realized_pnl_pct"),
            created_at=data.get("created_at", time.time()),
            submitted_at=data.get("submitted_at"),
            first_fill_at=data.get("first_fill_at"),
            completed_at=data.get("completed_at"),
            latency_ms=data.get("latency_ms", 0.0),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            notes=data.get("notes", ""),
        )
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_json(cls, json_str: str) -> "ExecutionResult":
        return cls.from_dict(json.loads(json_str))
