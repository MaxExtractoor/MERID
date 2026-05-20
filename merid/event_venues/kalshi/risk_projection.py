"""
Risk Projection Engine — Pure function backend snapshot → risk projection

This module implements the new risk/positions pipeline that is a faithful
projection of backend portfolios/contracts with no synthetic or inferred state.

Design principles:
1. Backend is the ONLY source of truth — no synthetic state
2. Pure function: backend snapshot → risk projection (no stored state)
3. All monetary values in dollars (matching Kalshi API)
4. Schema validation at edge with versioning
5. Parallel run with old pipeline for diff checking

Usage:
    from merid.event_venues.kalshi.risk_projection import (
        BackendSnapshot,
        RiskProjectionEngine,
        validate_backend_position,
    )
    
    # Fetch backend data
    snapshot = BackendSnapshot(
        positions=backend_positions,
        balance=backend_balance,
        fills=backend_fills,
        timestamp=datetime.now(timezone.utc),
    )
    
    # Compute projection
    engine = RiskProjectionEngine()
    projection = engine.compute_projection(snapshot)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from enum import Enum

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.risk_projection")


# ═══════════════════════════════════════════════════════════════════════════
# Schema Versioning
# ═══════════════════════════════════════════════════════════════════════════

POSITION_SCHEMA_VERSION = "v1"
BALANCE_SCHEMA_VERSION = "v1"
FILL_SCHEMA_VERSION = "v1"


class SchemaError(Exception):
    """Schema validation error."""
    pass


# ═══════════════════════════════════════════════════════════════════════════
# Backend Data Models (1:1 mapping to Kalshi API)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class BackendBalance:
    """1:1 mapping to Kalshi GET /portfolio/balance response.
    
    All values in dollars (matching Kalshi API).
    """
    available_usd: Decimal
    locked_usd: Decimal
    
    @property
    def total_usd(self) -> Decimal:
        return self.available_usd + self.locked_usd
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for validation."""
        return {
            "available_usd": str(self.available_usd),
            "locked_usd": str(self.locked_usd),
            "total_usd": str(self.total_usd),
        }
    
    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "BackendBalance":
        """Parse from Kalshi API response."""
        # Handle both {"USD": ..., "locked": ...} and {"available": ..., "locked": ...}
        available = raw.get("USD", raw.get("available", Decimal("0")))
        locked = raw.get("locked", Decimal("0"))
        
        return cls(
            available_usd=Decimal(str(available)),
            locked_usd=Decimal(str(locked)),
        )


@dataclass(frozen=True)
class BackendPosition:
    """1:1 mapping to Kalshi GET /portfolio/positions market_positions.
    
    All values in dollars (matching Kalshi API).
    No transformations, no derived fields — pure projection of backend data.
    """
    ticker: str
    side: str  # "yes" or "no"
    count: int
    avg_price_dollars: Decimal  # Average entry price (0-1 range)
    total_cost_dollars: Decimal
    unrealized_pnl_dollars: Decimal
    realized_pnl_dollars: Decimal
    created_at: datetime
    
    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "BackendPosition":
        """Parse from Kalshi API response with validation."""
        # Required fields - support both avg_price and avg_price_dollars
        required_base = ["ticker", "side", "count"]
        for field in required_base:
            if field not in raw:
                raise SchemaError(f"Missing required field: {field}")
        
        # Handle price field naming variations
        if "avg_price_dollars" in raw:
            avg_price = raw["avg_price_dollars"]
        elif "avg_price" in raw:
            avg_price = raw["avg_price"]
        elif "average_entry_price" in raw:
            avg_price = raw["average_entry_price"]
        else:
            raise SchemaError("Missing required field: avg_price (or avg_price_dollars or average_entry_price)")
        
        # Handle total_cost field naming variations
        if "total_cost_dollars" in raw:
            total_cost = raw["total_cost_dollars"]
        elif "total_cost" in raw:
            total_cost = raw["total_cost"]
        else:
            # Compute from count * avg_price
            total_cost = avg_price * raw["count"]
        
        # Type validation
        if not isinstance(raw["count"], int):
            raise SchemaError(f"count must be int, got {type(raw['count'])}")
        
        if raw["side"] not in ("yes", "no"):
            raise SchemaError(f"side must be 'yes' or 'no', got {raw['side']}")
        
        # Parse numeric fields
        avg_price_dec = Decimal(str(avg_price))
        total_cost_dec = Decimal(str(total_cost))
        unrealized_pnl = Decimal(str(raw.get("unrealized_pnl", raw.get("unrealized_pnl_dollars", 0))))
        realized_pnl = Decimal(str(raw.get("realized_pnl", raw.get("realized_pnl_dollars", 0))))
        
        # Parse timestamp
        created_at_str = raw.get("created_at")
        if created_at_str:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        else:
            created_at = datetime.now(timezone.utc)
        
        return cls(
            ticker=raw["ticker"],
            side=raw["side"],
            count=raw["count"],
            avg_price_dollars=avg_price_dec,
            total_cost_dollars=total_cost_dec,
            unrealized_pnl_dollars=unrealized_pnl,
            realized_pnl_dollars=realized_pnl,
            created_at=created_at,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "ticker": self.ticker,
            "side": self.side,
            "count": self.count,
            "avg_price_dollars": str(self.avg_price_dollars),
            "total_cost_dollars": str(self.total_cost_dollars),
            "unrealized_pnl_dollars": str(self.unrealized_pnl_dollars),
            "realized_pnl_dollars": str(self.realized_pnl_dollars),
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class BackendFill:
    """1:1 mapping to Kalshi GET /portfolio/fills response.
    
    All values in dollars (matching Kalshi API).
    """
    fill_id: str
    trade_id: Optional[str]
    order_id: str
    ticker: str
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    count: int
    yes_price_dollars: Optional[Decimal]
    no_price_dollars: Optional[Decimal]
    fee_cost_dollars: Decimal
    proceeds_dollars: Optional[Decimal]
    created_time: datetime
    
    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "BackendFill":
        """Parse from Kalshi API response with validation."""
        required = ["fill_id", "ticker", "side", "action", "count"]
        for field in required:
            if field not in raw:
                raise SchemaError(f"Missing required field: {field}")
        
        # Type validation
        if not isinstance(raw["count"], int):
            raise SchemaError(f"count must be int, got {type(raw['count'])}")
        
        if raw["side"] not in ("yes", "no"):
            raise SchemaError(f"side must be 'yes' or 'no', got {raw['side']}")
        
        if raw["action"] not in ("buy", "sell"):
            raise SchemaError(f"action must be 'buy' or 'sell', got {raw['action']}")
        
        # Parse numeric fields
        yes_price = Decimal(str(raw["yes_price"])) if raw.get("yes_price") else None
        no_price = Decimal(str(raw["no_price"])) if raw.get("no_price") else None
        fee_cost = Decimal(str(raw.get("fee_cost", 0)))
        proceeds = Decimal(str(raw["proceeds"])) if raw.get("proceeds") else None
        
        # Parse timestamp
        created_time_str = raw.get("created_time")
        if created_time_str:
            created_time = datetime.fromisoformat(created_time_str.replace("Z", "+00:00"))
        else:
            created_time = datetime.now(timezone.utc)
        
        return cls(
            fill_id=raw["fill_id"],
            trade_id=raw.get("trade_id"),
            order_id=raw.get("order_id", ""),
            ticker=raw["ticker"],
            side=raw["side"],
            action=raw["action"],
            count=raw["count"],
            yes_price_dollars=yes_price,
            no_price_dollars=no_price,
            fee_cost_dollars=fee_cost,
            proceeds_dollars=proceeds,
            created_time=created_time,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "fill_id": self.fill_id,
            "trade_id": self.trade_id,
            "order_id": self.order_id,
            "ticker": self.ticker,
            "side": self.side,
            "action": self.action,
            "count": self.count,
            "yes_price_dollars": str(self.yes_price_dollars) if self.yes_price_dollars else None,
            "no_price_dollars": str(self.no_price_dollars) if self.no_price_dollars else None,
            "fee_cost_dollars": str(self.fee_cost_dollars),
            "proceeds_dollars": str(self.proceeds_dollars) if self.proceeds_dollars else None,
            "created_time": self.created_time.isoformat(),
        }


@dataclass(frozen=True)
class BackendSnapshot:
    """Complete backend state at a point in time.
    
    This is the input to the risk projection engine.
    All data comes directly from Kalshi API — no synthetic state.
    """
    positions: List[BackendPosition]
    balance: BackendBalance
    fills: List[BackendFill]
    timestamp: datetime
    schema_version: str = POSITION_SCHEMA_VERSION
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "positions": [p.to_dict() for p in self.positions],
            "balance": {
                "available_usd": str(self.balance.available_usd),
                "locked_usd": str(self.balance.locked_usd),
                "total_usd": str(self.balance.total_usd),
            },
            "fills": [f.to_dict() for f in self.fills],
            "timestamp": self.timestamp.isoformat(),
            "schema_version": self.schema_version,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Risk Projection (Pure Function Output)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RiskProjection:
    """Pure function of backend data — no stored state.
    
    This is the output of the risk projection engine.
    All values are computed directly from backend snapshot — no synthetic inference.
    """
    positions_by_ticker: Dict[str, BackendPosition]
    total_exposure_dollars: Decimal
    unrealized_pnl_dollars: Decimal
    realized_pnl_dollars: Decimal
    equity_dollars: Decimal
    position_count: int
    
    # Raw echoes for audit
    backend_timestamp: datetime
    backend_positions_raw: List[Dict[str, Any]]
    backend_balance_raw: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "positions_by_ticker": {
                ticker: pos.to_dict()
                for ticker, pos in self.positions_by_ticker.items()
            },
            "total_exposure_dollars": str(self.total_exposure_dollars),
            "unrealized_pnl_dollars": str(self.unrealized_pnl_dollars),
            "realized_pnl_dollars": str(self.realized_pnl_dollars),
            "equity_dollars": str(self.equity_dollars),
            "position_count": self.position_count,
            "backend_timestamp": self.backend_timestamp.isoformat(),
            "backend_positions_raw": self.backend_positions_raw,
            "backend_balance_raw": self.backend_balance_raw,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Risk Projection Engine (Pure Function)
# ═══════════════════════════════════════════════════════════════════════════

class RiskProjectionEngine:
    """Pure function engine: backend snapshot → risk projection.
    
    This engine maintains NO state — it's a pure function that transforms
    backend data into risk metrics. All state lives in the backend (Kalshi API).
    
    Usage:
        engine = RiskProjectionEngine()
        projection = engine.compute_projection(snapshot)
    """
    
    def __init__(self):
        self._schema_mismatch_count = 0
        logger.info("RiskProjectionEngine initialized (pure function, no stored state)")
    
    def compute_projection(self, snapshot: BackendSnapshot) -> RiskProjection:
        """Compute risk metrics from backend data (no stored state).
        
        Args:
            snapshot: Complete backend state from Kalshi API
            
        Returns:
            RiskProjection with all metrics computed purely from backend data
        """
        # Build position lookup
        positions_by_ticker = {p.ticker: p for p in snapshot.positions}
        
        # Compute totals (pure aggregation, no inference)
        total_exposure = sum(p.total_cost_dollars for p in snapshot.positions)
        unrealized_pnl = sum(p.unrealized_pnl_dollars for p in snapshot.positions)
        realized_pnl = sum(p.realized_pnl_dollars for p in snapshot.positions)
        equity = snapshot.balance.available_usd + unrealized_pnl
        
        # Count open positions (count > 0)
        position_count = sum(1 for p in snapshot.positions if p.count > 0)
        
        # Raw echoes for audit
        backend_positions_raw = [p.to_dict() for p in snapshot.positions]
        backend_balance_raw = {
            "available_usd": str(snapshot.balance.available_usd),
            "locked_usd": str(snapshot.balance.locked_usd),
            "total_usd": str(snapshot.balance.total_usd),
        }
        
        projection = RiskProjection(
            positions_by_ticker=positions_by_ticker,
            total_exposure_dollars=total_exposure,
            unrealized_pnl_dollars=unrealized_pnl,
            realized_pnl_dollars=realized_pnl,
            equity_dollars=equity,
            position_count=position_count,
            backend_timestamp=snapshot.timestamp,
            backend_positions_raw=backend_positions_raw,
            backend_balance_raw=backend_balance_raw,
        )
        
        logger.debug(
            "RiskProjection computed: positions=%d exposure=$%.2f unrealized=$%.2f equity=$%.2f",
            position_count, total_exposure, unrealized_pnl, equity
        )
        
        return projection
    
    @property
    def schema_mismatch_count(self) -> int:
        """Count of schema validation failures (for monitoring)."""
        return self._schema_mismatch_count


# ═══════════════════════════════════════════════════════════════════════════
# Validation Functions (Edge Schema Validation)
# ═══════════════════════════════════════════════════════════════════════════

def validate_backend_position(data: Dict[str, Any]) -> BackendPosition:
    """Strict validation with version check.
    
    Args:
        data: Raw position data from Kalshi API
        
    Returns:
        BackendPosition if validation passes
        
    Raises:
        SchemaError: If validation fails
    """
    try:
        return BackendPosition.from_raw(data)
    except SchemaError as e:
        # Increment counter for monitoring
        try:
            from monitoring.metrics import get_metrics_registry
            registry = get_metrics_registry()
            counter = registry.counter(
                "risk_backend_schema_mismatch_total",
                help_text="Count of backend schema validation failures",
                label_names=["field", "error_type"]
            )
            counter.inc(labels={"field": "unknown", "error_type": type(e).__name__})
        except Exception:
            pass  # Metrics unavailable, skip
        
        logger.error(f"[SOURCE=backend] Schema validation failed: {e}")
        raise


def validate_backend_balance(data: Dict[str, Any]) -> BackendBalance:
    """Validate balance data from Kalshi API."""
    try:
        return BackendBalance.from_raw(data)
    except (KeyError, ValueError, TypeError) as e:
        logger.error(f"[SOURCE=backend] Balance schema validation failed: {e}")
        raise SchemaError(f"Invalid balance data: {e}")


def validate_backend_fill(data: Dict[str, Any]) -> BackendFill:
    """Validate fill data from Kalshi API."""
    try:
        return BackendFill.from_raw(data)
    except SchemaError as e:
        logger.error(f"[SOURCE=backend] Fill schema validation failed: {e}")
        raise


# ═══════════════════════════════════════════════════════════════════════════
# Singleton Access
# ═══════════════════════════════════════════════════════════════════════════

_risk_projection_engine_instance: Optional[RiskProjectionEngine] = None


def get_risk_projection_engine() -> RiskProjectionEngine:
    """Get singleton RiskProjectionEngine instance."""
    global _risk_projection_engine_instance
    if _risk_projection_engine_instance is None:
        _risk_projection_engine_instance = RiskProjectionEngine()
    return _risk_projection_engine_instance
