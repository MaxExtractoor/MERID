"""
Kalshi Energy Dataclasses for Lane Operations

Specialized energy structures for Kalshi 15m crypto lane orchestration.
These provide type-safe interfaces between lanes and the core orchestrator.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from datetime import datetime


@dataclass
class KalshiEnergy:
    """
    Specialized energy packet for Kalshi 15m crypto lane operations.
    
    This replaces generic energy payloads with structured, type-safe
    data that the Kalshi core can process directly.
    """
    # Energy identification
    energy_id: str
    source: str = "lane"
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    
    # Lane identification
    lane_id: str                    # e.g., "BTC_15M", "ETH_15M"
    symbol: str                    # "BTC", "ETH", "SOL", "XRP"
    timeframe: str = "15m"
    
    # Market identification
    market_id: str                  # e.g., "KXBTC15M-20260306-0115"
    market_ticker: str              # e.g., "KXBTC15M-20260306-0115"
    series_ticker: str              # e.g., "KXBTC15M"
    
    # Market pricing (cents)
    yes_price_cents: int
    no_price_cents: int
    yes_bid_cents: Optional[int] = None
    yes_ask_cents: Optional[int] = None
    no_bid_cents: Optional[int] = None
    no_ask_cents: Optional[int] = None
    
    # Probabilities
    p_true: float                   # Bayesian estimated probability
    p_implied: float                # De-vigged market probability
    p_yes_implied: Optional[float] = None  # Raw implied probability
    p_yes_devig: Optional[float] = None      # De-vigged YES probability
    
    # Edge and decision
    edge_bps: float                 # Edge in basis points
    direction: str                  # "YES", "NO", "FLAT"
    
    # RCK sizing
    kelly_fraction_full: float      # Full Kelly fraction
    kelly_fraction_rck: float        # RCK solver result
    kelly_fraction_used: float      # Final fraction after safety
    target_drawdown: float          # RCK target drawdown
    drawdown_probability: float     # RCK DD probability
    safety_factor: float             # Safety factor applied
    size_contracts: int             # Position size in contracts
    
    # Bankroll
    bankroll_before: float          # Bankroll before trade
    bankroll_after: float           # Bankroll after trade
    
    # Features used for p_true estimation
    features: Dict[str, Any] = field(default_factory=dict)
    
    # Settlement information (for validation)
    settlement_time: Optional[float] = None
    outcome_yes: Optional[bool] = None
    settlement_price: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for core processing."""
        return {
            "energy_id": self.energy_id,
            "source": self.source,
            "timestamp": self.timestamp,
            "lane_id": self.lane_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "market_id": self.market_id,
            "market_ticker": self.market_ticker,
            "series_ticker": self.series_ticker,
            "yes_price_cents": self.yes_price_cents,
            "no_price_cents": self.no_price_cents,
            "yes_bid_cents": self.yes_bid_cents,
            "yes_ask_cents": self.yes_ask_cents,
            "no_bid_cents": self.no_bid_cents,
            "no_ask_cents": self.no_ask_cents,
            "p_true": self.p_true,
            "p_implied": self.p_implied,
            "p_yes_implied": self.p_yes_implied,
            "p_yes_devig": self.p_yes_devig,
            "edge_bps": self.edge_bps,
            "direction": self.direction,
            "kelly_fraction_full": self.kelly_fraction_full,
            "kelly_fraction_rck": self.kelly_fraction_rck,
            "kelly_fraction_used": self.kelly_fraction_used,
            "target_drawdown": self.target_drawdown,
            "drawdown_probability": self.drawdown_probability,
            "safety_factor": self.safety_factor,
            "size_contracts": self.size_contracts,
            "bankroll_before": self.bankroll_before,
            "bankroll_after": self.bankroll_after,
            "features": self.features,
            "settlement_time": self.settlement_time,
            "outcome_yes": self.outcome_yes,
            "settlement_price": self.settlement_price,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KalshiEnergy":
        """Create from dictionary (for legacy compatibility)."""
        return cls(
            energy_id=data["energy_id"],
            source=data.get("source", "lane"),
            timestamp=data.get("timestamp", datetime.now().timestamp()),
            lane_id=data["lane_id"],
            symbol=data["symbol"],
            timeframe=data.get("timeframe", "15m"),
            market_id=data["market_id"],
            market_ticker=data.get("market_ticker", ""),
            series_ticker=data.get("series_ticker", ""),
            yes_price_cents=data["yes_price_cents"],
            no_price_cents=data["no_price_cents"],
            yes_bid_cents=data.get("yes_bid_cents"),
            yes_ask_cents=data.get("yes_ask_cents"),
            no_bid_cents=data.get("no_bid_cents"),
            no_ask_cents=data.get("no_ask_cents"),
            p_true=data["p_true"],
            p_implied=data["p_implied"],
            p_yes_implied=data.get("p_yes_implied"),
            p_yes_devig=data.get("p_yes_devig"),
            edge_bps=data["edge_bps"],
            direction=data["direction"],
            kelly_fraction_full=data["kelly_fraction_full"],
            kelly_fraction_rck=data["kelly_fraction_rck"],
            kelly_fraction_used=data["kelly_fraction_used"],
            target_drawdown=data["target_drawdown"],
            drawdown_probability=data["drawdown_probability"],
            safety_factor=data["safety_factor"],
            size_contracts=data["size_contracts"],
            bankroll_before=data["bankroll_before"],
            bankroll_after=data["bankroll_after"],
            features=data.get("features", {}),
            settlement_time=data.get("settlement_time"),
            outcome_yes=data.get("outcome_yes"),
            settlement_price=data.get("settlement_price"),
        )
    
    def get_summary(self) -> str:
        """Get human-readable summary for logging."""
        return (
            f"{self.symbol} {self.direction} @ {self.yes_price_cents}c "
            f"(edge: {self.edge_bps} bps, kelly: {self.kelly_fraction_used:.3f}, "
            f"size: {self.size_contracts} contracts)"
        )


@dataclass
class KalshiValidationResult:
    """Validation result specific to Kalshi trades."""
    status: str                     # "confirmed", "wrong_side", "size_error", "drawdown_breach"
    validated: bool                 # Overall validation success
    score: float                    # Validation score (0-1)
    reality_gap: float              # Difference between p_true and empirical
    realized_edge: Optional[float] = None  # Actual edge realized
    pnl_contracts: Optional[float] = None  # P&L per contract
    drawdown_realized: Optional[float] = None  # Actual drawdown realized
    settlement_correct: bool        # Whether settlement matched direction
    rck_constraints_met: bool       # Whether RCK constraints were respected
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "status": self.status,
            "validated": self.validated,
            "score": self.score,
            "reality_gap": self.reality_gap,
            "realized_edge": self.realized_edge,
            "pnl_contracts": self.pnl_contracts,
            "drawdown_realized": self.drawdown_realized,
            "settlement_correct": self.settlement_correct,
            "rck_constraints_met": self.rck_constraints_met,
        }


# Factory functions for creating Kalshi energy from lane data
def create_kalshi_energy_from_lane(
    lane_id: str,
    market_data: Dict[str, Any],
    consensus_result: Dict[str, Any],
    risk_decision: Dict[str, Any],
    energy_id: Optional[str] = None
) -> KalshiEnergy:
    """
    Create KalshiEnergy from lane decision data.
    
    Args:
        lane_id: Lane identifier
        market_data: Kalshi market data
        consensus_result: Consensus calculation result
        risk_decision: Risk evaluation result
        energy_id: Optional energy ID (auto-generated if None)
        
    Returns:
        KalshiEnergy instance
    """
    import uuid
    import time
    
    if energy_id is None:
        energy_id = f"kalshi_{lane_id}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    
    return KalshiEnergy(
        energy_id=energy_id,
        lane_id=lane_id,
        symbol=market_data.get("symbol", ""),
        market_id=market_data.get("market_id", ""),
        market_ticker=market_data.get("market_ticker", ""),
        series_ticker=market_data.get("series_ticker", ""),
        yes_price_cents=market_data.get("yes_price_cents", 50),
        no_price_cents=market_data.get("no_price_cents", 50),
        yes_bid_cents=market_data.get("yes_bid"),
        yes_ask_cents=market_data.get("yes_ask"),
        no_bid_cents=market_data.get("no_bid"),
        no_ask_cents=market_data.get("no_ask"),
        p_true=consensus_result.get("p_true", 0.5),
        p_implied=consensus_result.get("p_implied", 0.5),
        edge_bps=consensus_result.get("edge_bps", 0.0),
        direction=consensus_result.get("direction", "FLAT"),
        kelly_fraction_full=risk_decision.get("kelly_fraction_full", 0.0),
        kelly_fraction_rck=risk_decision.get("risk_constrained_kelly", {}).get("f_rck", 0.0),
        kelly_fraction_used=risk_decision.get("kelly_fraction_used", 0.0),
        target_drawdown=risk_decision.get("risk_constrained_kelly", {}).get("target_drawdown", 0.1),
        drawdown_probability=risk_decision.get("risk_constrained_kelly", {}).get("drawdown_probability", 0.1),
        safety_factor=risk_decision.get("risk_constrained_kelly", {}).get("safety_factor", 0.8),
        size_contracts=int(risk_decision.get("position_size", 0) * 100),
        bankroll_before=risk_decision.get("bankroll_before", 0.0),
        bankroll_after=risk_decision.get("bankroll_after", 0.0),
        features=consensus_result.get("features", {}),
        settlement_time=market_data.get("expected_expiration_time_ts"),
    )


def create_validation_result_from_settlement(
    energy: KalshiEnergy,
    settlement_data: Dict[str, Any]
) -> KalshiValidationResult:
    """
    Create validation result from settlement data.
    
    Args:
        energy: Original KalshiEnergy
        settlement_data: Settlement outcome data
        
    Returns:
        KalshiValidationResult with market-specific validation
    """
    outcome_yes = settlement_data.get("outcome_yes", False)
    settlement_price = settlement_data.get("settlement_price", 0.0)
    
    # Check if direction was correct
    settlement_correct = (
        (energy.direction == "YES" and outcome_yes) or
        (energy.direction == "NO" and not outcome_yes)
    )
    
    # Calculate realized edge (cents PnL per contract)
    # YES contract: pays 100c if outcome=yes, 0c if outcome=no; cost = yes_price_cents
    # NO  contract: pays 100c if outcome=no,  0c if outcome=yes; cost = no_price_cents
    if energy.direction == "YES":
        entry_cost = energy.yes_price_cents
        payout = 100 if outcome_yes else 0
        realized_edge = payout - entry_cost
    elif energy.direction == "NO":
        entry_cost = energy.no_price_cents
        payout = 100 if not outcome_yes else 0
        realized_edge = payout - entry_cost
    else:
        realized_edge = None
    
    # Determine validation status
    if not settlement_correct:
        status = "wrong_side"
        validated = False
        score = 0.0
    elif energy.edge_bps > 0 and realized_edge and realized_edge < 0:
        status = "edge_error"
        validated = False
        score = 0.3
    else:
        status = "confirmed"
        validated = True
        score = 1.0
    
    # Calculate reality gap (simplified)
    empirical_prob = 1.0 if outcome_yes else 0.0
    reality_gap = abs(energy.p_true - empirical_prob)
    
    return KalshiValidationResult(
        status=status,
        validated=validated,
        score=score,
        reality_gap=reality_gap,
        realized_edge=realized_edge,
        pnl_contracts=realized_edge,
        settlement_correct=settlement_correct,
        rck_constraints_met=True,  # TODO: Check actual drawdown constraints
    )
