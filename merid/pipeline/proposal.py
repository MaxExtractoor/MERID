"""Normalized TradeProposal — the single object all agents produce.

Every swarm agent emits TradeProposals.  The pipeline validates them
through risk, routes them to the correct venue adapter, and records
the ExecutionResult.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional


class TradeDomain(str, Enum):
    """Market domain classification."""
    PREDICTION = "prediction"
    CRYPTO = "crypto"
    EQUITY = "equity"
    MACRO = "macro"


class ProposalStatus(str, Enum):
    """Lifecycle of a trade proposal."""
    PENDING = "pending"
    RISK_APPROVED = "risk_approved"
    RISK_REJECTED = "risk_rejected"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    IOC = "ioc"
    FOK = "fok"


@dataclass
class TradeProposal:
    """Normalized trade proposal that flows through the entire pipeline.

    Agents create these; the risk manager approves/rejects; the router
    dispatches to the correct venue adapter.
    """
    # Identity
    proposal_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    domain: TradeDomain = TradeDomain.CRYPTO
    strategy_id: str = ""
    agent_id: str = ""

    # Instrument
    venue: str = ""                    # Target venue (e.g. "kalshi", "binance", "alpaca")
    instrument_id: str = ""            # MERID-internal symbol
    native_symbol: str = ""            # Venue-native symbol (filled by router)

    # Order parameters
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.LIMIT
    qty: Decimal = Decimal("0")
    price: Optional[Decimal] = None    # Required for limit orders
    notional_usd: Optional[Decimal] = None

    # Risk tags
    risk_tags: List[str] = field(default_factory=list)
    max_slippage_pct: Decimal = Decimal("0.01")  # 1 % default

    # Metadata
    rationale: str = ""                # Human-readable reason
    confidence: Decimal = Decimal("0.5")
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Lifecycle
    status: ProposalStatus = ProposalStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None
    risk_check_result: Optional[Dict[str, Any]] = None
    execution_result: Optional["ExecutionResult"] = None

    def approve(self) -> None:
        self.status = ProposalStatus.RISK_APPROVED
        self.updated_at = datetime.now(timezone.utc)

    def reject(self, reason: str) -> None:
        self.status = ProposalStatus.RISK_REJECTED
        self.risk_check_result = {"rejected": True, "reason": reason}
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "domain": self.domain.value,
            "strategy_id": self.strategy_id,
            "agent_id": self.agent_id,
            "venue": self.venue,
            "instrument_id": self.instrument_id,
            "native_symbol": self.native_symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "qty": str(self.qty),
            "price": str(self.price) if self.price else None,
            "notional_usd": str(self.notional_usd) if self.notional_usd else None,
            "risk_tags": self.risk_tags,
            "rationale": self.rationale,
            "confidence": str(self.confidence),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ExecutionResult:
    """Result of submitting a proposal to a venue adapter."""
    proposal_id: str
    venue: str
    venue_order_id: str = ""
    status: str = "unknown"            # filled, partially_filled, rejected, error
    filled_qty: Decimal = Decimal("0")
    avg_price: Decimal = Decimal("0")
    fee: Decimal = Decimal("0")
    fee_currency: str = "USD"
    latency_ms: float = 0.0
    error: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "venue": self.venue,
            "venue_order_id": self.venue_order_id,
            "status": self.status,
            "filled_qty": str(self.filled_qty),
            "avg_price": str(self.avg_price),
            "fee": str(self.fee),
            "latency_ms": self.latency_ms,
            "error": self.error,
            "timestamp": self.timestamp.isoformat(),
        }
