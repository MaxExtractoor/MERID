"""
ArbitrageOpportunity Schema - Canonical arbitrage opportunity structure.

Defines all arbitrage types and the data structures needed to
identify, evaluate, and execute arbitrage opportunities.

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


class ArbitrageType(Enum):
    """Types of arbitrage opportunities."""
    CROSS_CEX = "cross_cex"              # Price diff between centralized exchanges
    DEX_CEX = "dex_cex"                  # DEX vs CEX price diff
    PERP_SPOT = "perp_spot"              # Perpetual vs spot basis
    FUNDING_RATE = "funding_rate"        # Funding rate capture
    TRIANGULAR = "triangular"            # A->B->C->A currency triangle
    PREDICTION_CROSS = "prediction_cross" # Cross-platform prediction market
    STABLECOIN = "stablecoin"            # Stablecoin depeg arbitrage
    LIQUIDATION = "liquidation"          # Liquidation arbitrage
    NFT = "nft"                          # NFT floor arbitrage


class ArbitrageStatus(Enum):
    """Status of an arbitrage opportunity."""
    DETECTED = "detected"
    VALIDATING = "validating"
    VALID = "valid"
    INVALID = "invalid"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"
    EXPIRED = "expired"
    INSUFFICIENT_LIQUIDITY = "insufficient_liquidity"


class VenueType(Enum):
    """Types of trading venues."""
    CEX = "cex"
    DEX = "dex"
    PERP = "perp"
    PREDICTION = "prediction"
    OTC = "otc"


@dataclass
class ArbitrageLeg:
    """A single leg of an arbitrage trade."""
    leg_id: str = field(default_factory=lambda: f"leg_{uuid.uuid4().hex[:8]}")
    sequence: int = 0  # Order of execution
    
    # Venue
    venue: str = ""  # Exchange/DEX name
    venue_type: VenueType = VenueType.CEX
    
    # Trade details
    symbol: str = ""
    side: str = "buy"  # buy, sell
    quantity: float = 0.0
    price: float = 0.0
    
    # Costs
    estimated_fee: float = 0.0
    estimated_slippage: float = 0.0
    estimated_gas: float = 0.0  # For on-chain legs
    
    # Timing
    estimated_latency_ms: float = 0.0
    
    # Execution
    executed: bool = False
    actual_price: Optional[float] = None
    actual_fee: Optional[float] = None
    actual_slippage: Optional[float] = None
    execution_time: Optional[float] = None
    
    def estimated_cost(self) -> float:
        """Total estimated cost for this leg."""
        return self.estimated_fee + self.estimated_slippage + self.estimated_gas
    
    def actual_cost(self) -> float:
        """Total actual cost for this leg (after execution)."""
        if not self.executed:
            return 0.0
        return (self.actual_fee or 0) + (self.actual_slippage or 0)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "leg_id": self.leg_id,
            "sequence": self.sequence,
            "venue": self.venue,
            "venue_type": self.venue_type.value,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "estimated_fee": self.estimated_fee,
            "estimated_slippage": self.estimated_slippage,
            "estimated_gas": self.estimated_gas,
            "estimated_latency_ms": self.estimated_latency_ms,
            "estimated_cost": self.estimated_cost(),
            "executed": self.executed,
            "actual_price": self.actual_price,
            "actual_fee": self.actual_fee,
            "actual_slippage": self.actual_slippage,
            "execution_time": self.execution_time,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArbitrageLeg":
        return cls(
            leg_id=data.get("leg_id", f"leg_{uuid.uuid4().hex[:8]}"),
            sequence=data.get("sequence", 0),
            venue=data.get("venue", ""),
            venue_type=VenueType(data.get("venue_type", "cex")),
            symbol=data.get("symbol", ""),
            side=data.get("side", "buy"),
            quantity=data.get("quantity", 0.0),
            price=data.get("price", 0.0),
            estimated_fee=data.get("estimated_fee", 0.0),
            estimated_slippage=data.get("estimated_slippage", 0.0),
            estimated_gas=data.get("estimated_gas", 0.0),
            estimated_latency_ms=data.get("estimated_latency_ms", 0.0),
            executed=data.get("executed", False),
            actual_price=data.get("actual_price"),
            actual_fee=data.get("actual_fee"),
            actual_slippage=data.get("actual_slippage"),
            execution_time=data.get("execution_time"),
        )


@dataclass
class CostModel:
    """Cost model for arbitrage evaluation."""
    total_fees: float = 0.0
    total_slippage: float = 0.0
    total_gas: float = 0.0
    latency_penalty: float = 0.0
    mev_risk: float = 0.0
    
    def total_cost(self) -> float:
        return self.total_fees + self.total_slippage + self.total_gas + self.latency_penalty + self.mev_risk
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_fees": self.total_fees,
            "total_slippage": self.total_slippage,
            "total_gas": self.total_gas,
            "latency_penalty": self.latency_penalty,
            "mev_risk": self.mev_risk,
            "total_cost": self.total_cost(),
        }


@dataclass
class ArbitrageOpportunity:
    """
    A complete arbitrage opportunity with all legs and cost analysis.
    
    This is the canonical structure for any arbitrage detected by MERID.
    """
    
    # Identity
    opportunity_id: str = field(default_factory=lambda: f"arb_{uuid.uuid4().hex[:12]}")
    
    # Type and status
    arb_type: ArbitrageType = ArbitrageType.CROSS_CEX
    status: ArbitrageStatus = ArbitrageStatus.DETECTED
    
    # Legs
    legs: List[ArbitrageLeg] = field(default_factory=list)
    
    # Profit analysis
    gross_profit_usd: float = 0.0
    cost_model: CostModel = field(default_factory=CostModel)
    net_profit_usd: float = 0.0
    profit_margin_pct: float = 0.0
    
    # Risk metrics
    execution_risk: float = 0.0  # 0-1, probability of failure
    liquidity_score: float = 1.0  # 0-1, available liquidity
    time_sensitivity: float = 0.0  # Seconds until opportunity expires
    
    # Thresholds
    min_profit_threshold_usd: float = 10.0
    min_margin_threshold_pct: float = 0.1  # 0.1%
    
    # Timing
    detected_at: float = field(default_factory=time.time)
    validated_at: Optional[float] = None
    executed_at: Optional[float] = None
    expires_at: Optional[float] = None
    
    # Execution
    intent_id: Optional[str] = None
    execution_result_id: Optional[str] = None
    actual_profit_usd: Optional[float] = None
    
    # Metadata
    source_scanner: str = ""
    confidence: float = 0.0
    notes: str = ""
    
    def compute_hash(self) -> str:
        """Compute deterministic hash of the opportunity."""
        hash_data = {
            "opportunity_id": self.opportunity_id,
            "arb_type": self.arb_type.value,
            "legs": [l.to_dict() for l in self.legs],
            "detected_at": self.detected_at,
        }
        json_str = json.dumps(hash_data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(json_str.encode()).hexdigest()[:16]
    
    def calculate_profit(self) -> None:
        """Calculate net profit from legs and cost model."""
        if len(self.legs) < 2:
            return
        
        # Calculate gross profit from price differences
        buy_legs = [l for l in self.legs if l.side == "buy"]
        sell_legs = [l for l in self.legs if l.side == "sell"]
        
        if buy_legs and sell_legs:
            avg_buy = sum(l.price * l.quantity for l in buy_legs) / sum(l.quantity for l in buy_legs)
            avg_sell = sum(l.price * l.quantity for l in sell_legs) / sum(l.quantity for l in sell_legs)
            total_quantity = min(sum(l.quantity for l in buy_legs), sum(l.quantity for l in sell_legs))
            
            self.gross_profit_usd = (avg_sell - avg_buy) * total_quantity
        
        # Calculate costs
        self.cost_model.total_fees = sum(l.estimated_fee for l in self.legs)
        self.cost_model.total_slippage = sum(l.estimated_slippage for l in self.legs)
        self.cost_model.total_gas = sum(l.estimated_gas for l in self.legs)
        
        # Net profit
        self.net_profit_usd = self.gross_profit_usd - self.cost_model.total_cost()
        
        # Margin
        total_value = sum(l.price * l.quantity for l in self.legs) / 2  # Approximate
        if total_value > 0:
            self.profit_margin_pct = (self.net_profit_usd / total_value) * 100
    
    def is_profitable(self) -> bool:
        """Check if opportunity meets profit thresholds."""
        return (
            self.net_profit_usd >= self.min_profit_threshold_usd and
            self.profit_margin_pct >= self.min_margin_threshold_pct
        )
    
    def is_expired(self) -> bool:
        """Check if opportunity has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    def can_execute(self) -> bool:
        """Check if opportunity can be executed."""
        return (
            self.status == ArbitrageStatus.VALID and
            self.is_profitable() and
            not self.is_expired() and
            self.liquidity_score > 0.5 and
            self.execution_risk < 0.5
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "opportunity_id": self.opportunity_id,
            "hash": self.compute_hash(),
            "arb_type": self.arb_type.value,
            "status": self.status.value,
            "legs": [l.to_dict() for l in self.legs],
            "gross_profit_usd": self.gross_profit_usd,
            "cost_model": self.cost_model.to_dict(),
            "net_profit_usd": self.net_profit_usd,
            "profit_margin_pct": self.profit_margin_pct,
            "execution_risk": self.execution_risk,
            "liquidity_score": self.liquidity_score,
            "time_sensitivity": self.time_sensitivity,
            "min_profit_threshold_usd": self.min_profit_threshold_usd,
            "min_margin_threshold_pct": self.min_margin_threshold_pct,
            "detected_at": self.detected_at,
            "validated_at": self.validated_at,
            "executed_at": self.executed_at,
            "expires_at": self.expires_at,
            "intent_id": self.intent_id,
            "execution_result_id": self.execution_result_id,
            "actual_profit_usd": self.actual_profit_usd,
            "source_scanner": self.source_scanner,
            "confidence": self.confidence,
            "notes": self.notes,
            "is_profitable": self.is_profitable(),
            "can_execute": self.can_execute(),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArbitrageOpportunity":
        legs = [ArbitrageLeg.from_dict(l) for l in data.get("legs", [])]
        cost_data = data.get("cost_model", {})
        
        return cls(
            opportunity_id=data.get("opportunity_id", f"arb_{uuid.uuid4().hex[:12]}"),
            arb_type=ArbitrageType(data.get("arb_type", "cross_cex")),
            status=ArbitrageStatus(data.get("status", "detected")),
            legs=legs,
            gross_profit_usd=data.get("gross_profit_usd", 0.0),
            cost_model=CostModel(
                total_fees=cost_data.get("total_fees", 0.0),
                total_slippage=cost_data.get("total_slippage", 0.0),
                total_gas=cost_data.get("total_gas", 0.0),
                latency_penalty=cost_data.get("latency_penalty", 0.0),
                mev_risk=cost_data.get("mev_risk", 0.0),
            ),
            net_profit_usd=data.get("net_profit_usd", 0.0),
            profit_margin_pct=data.get("profit_margin_pct", 0.0),
            execution_risk=data.get("execution_risk", 0.0),
            liquidity_score=data.get("liquidity_score", 1.0),
            time_sensitivity=data.get("time_sensitivity", 0.0),
            min_profit_threshold_usd=data.get("min_profit_threshold_usd", 10.0),
            min_margin_threshold_pct=data.get("min_margin_threshold_pct", 0.1),
            detected_at=data.get("detected_at", time.time()),
            validated_at=data.get("validated_at"),
            executed_at=data.get("executed_at"),
            expires_at=data.get("expires_at"),
            intent_id=data.get("intent_id"),
            execution_result_id=data.get("execution_result_id"),
            actual_profit_usd=data.get("actual_profit_usd"),
            source_scanner=data.get("source_scanner", ""),
            confidence=data.get("confidence", 0.0),
            notes=data.get("notes", ""),
        )
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_json(cls, json_str: str) -> "ArbitrageOpportunity":
        return cls.from_dict(json.loads(json_str))
