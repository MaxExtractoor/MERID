"""Yes/No Parity + Price-Band Cycle Diagnostic for 15-minute Kalshi crypto markets.

This module provides per-cycle diagnostic logging to ensure:
- YES and NO pricing obey binary parity (combined value ≈ $1 economically)
- Edge computation is symmetric and correct
- Winner selection respects edge comparison
- All entries respect canonical price band (5c-85c)

Emits structured JSON log lines per cycle for monitoring and regression detection.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class ParityCycleDiagnostic:
    """Per-cycle parity and price-band diagnostic data."""
    cycle_id: str
    market_id: str
    asset: str
    expiry_ts: int
    
    # Orderbook data
    yes_bid: Optional[float]
    yes_ask: Optional[float]
    no_bid: Optional[float]
    no_ask: Optional[float]
    
    # Model and edge data
    model_prob_yes: float
    model_prob_no: float
    edge_yes: float
    edge_no: float
    
    # Decision layer
    winner_side: str  # "yes", "no", or "none"
    strategy_intent: str  # "bullish_event_happens", "bearish_event_happens", "neutral"
    
    # Price-band compliance
    price_band_ok: bool
    band_violation_type: Optional[str]  # "below_lower", "above_upper", or None
    price_cents: Optional[int]
    
    # Parity checks
    parity_ok: bool
    price_parity_ok: bool
    edge_symmetry_ok: bool
    winner_correctness_ok: bool
    
    # Timestamp
    ts: int


class ParityCycleMonitor:
    """Per-cycle parity and price-band monitor for 15m crypto markets."""
    
    def __init__(
        self,
        min_price_cents: int = 10,
        max_price_cents: int = 75,
        prob_eps: float = 1e-3,
        edge_eps: float = 1e-3,
        price_eps: float = 0.01,
    ):
        """Initialize parity cycle monitor.
        
        Args:
            min_price_cents: Minimum valid price in canonical band (default 10c)
            max_price_cents: Maximum valid price in canonical band (default 75c)
            prob_eps: Tolerance for probability parity check
            edge_eps: Tolerance for edge parity check
            price_eps: Tolerance for price parity check (default 1 cent)
        """
        self.min_price_cents = min_price_cents
        self.max_price_cents = max_price_cents
        self.prob_eps = prob_eps
        self.edge_eps = edge_eps
        self.price_eps = price_eps
    
    def check_price_band(
        self,
        price_cents: Optional[int],
    ) -> tuple[bool, Optional[str]]:
        """Check if price is within canonical band.
        
        Args:
            price_cents: Contract price in cents
            
        Returns:
            Tuple of (ok, violation_type) where violation_type is None if ok
        """
        if price_cents is None:
            return False, "missing_price"
        
        if price_cents < self.min_price_cents:
            return False, "below_lower"
        
        if price_cents > self.max_price_cents:
            return False, "above_upper"
        
        return True, None
    
    def check_price_parity(
        self,
        yes_price: Optional[float],
        no_price: Optional[float],
    ) -> bool:
        """Check if YES and NO prices obey binary parity (yes + no ≈ 1).
        
        Args:
            yes_price: YES contract price (0.0-1.0)
            no_price: NO contract price (0.0-1.0)
            
        Returns:
            True if prices obey parity, False otherwise
        """
        if yes_price is None or no_price is None:
            return True  # Can't validate with missing data
        
        combined = yes_price + no_price
        return abs(combined - 1.0) <= self.price_eps
    
    def check_edge_symmetry(
        self,
        model_prob_yes: float,
        market_price_yes: Optional[float],
        market_price_no: Optional[float],
        edge_yes: float,
        edge_no: float,
    ) -> bool:
        """Check if edges are computed symmetrically using canonical formula.
        
        Args:
            model_prob_yes: Model probability of YES
            market_price_yes: Market YES price
            market_price_no: Market NO price
            edge_yes: Computed YES edge
            edge_no: Computed NO edge
            
        Returns:
            True if edges are symmetric, False otherwise
        """
        if market_price_yes is None and market_price_no is None:
            return True  # Can't validate with missing data
        
        # Compute expected edges using canonical formula
        expected_edge_yes = model_prob_yes - (market_price_yes if market_price_yes is not None else 1.0 - market_price_no)
        expected_edge_no = (1.0 - model_prob_yes) - (market_price_no if market_price_no is not None else 1.0 - market_price_yes)
        
        # Check if computed edges match expected (within tolerance)
        yes_ok = abs(edge_yes - expected_edge_yes) <= self.edge_eps
        no_ok = abs(edge_no - expected_edge_no) <= self.edge_eps
        
        return yes_ok and no_ok
    
    def check_winner_correctness(
        self,
        edge_yes: float,
        edge_no: float,
        winner_side: str,
        min_edge: float = 0.0,
    ) -> bool:
        """Check if winner side is correct based on edge comparison.
        
        Args:
            edge_yes: Edge on YES contracts
            edge_no: Edge on NO contracts
            winner_side: Selected winner side ("yes", "no", or "none")
            min_edge: Minimum positive edge threshold
            
        Returns:
            True if winner is correct, False otherwise
        """
        if winner_side == "none":
            # "none" is correct if both edges are non-positive or below threshold
            return edge_yes <= min_edge and edge_no <= min_edge
        
        if winner_side == "yes":
            # YES is correct if it has higher positive edge
            return edge_yes > edge_no + self.edge_eps and edge_yes > min_edge
        
        if winner_side == "no":
            # NO is correct if it has higher positive edge
            return edge_no > edge_yes + self.edge_eps and edge_no > min_edge
        
        return False
    
    def record_cycle_diagnostic(
        self,
        cycle_id: str,
        market_id: str,
        asset: str,
        expiry_ts: int,
        yes_bid: Optional[float],
        yes_ask: Optional[float],
        no_bid: Optional[float],
        no_ask: Optional[float],
        model_prob_yes: float,
        edge_yes: float,
        edge_no: float,
        winner_side: str,
        strategy_intent: str,
        price_cents: Optional[int],
        min_edge: float = 0.02,
    ) -> ParityCycleDiagnostic:
        """Record a complete cycle diagnostic.
        
        Args:
            cycle_id: Cycle identifier
            market_id: Kalshi market ID
            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
            expiry_ts: Expiry timestamp
            yes_bid: YES bid price in cents
            yes_ask: YES ask price in cents
            no_bid: NO bid price in cents
            no_ask: NO ask price in cents
            model_prob_yes: Model probability of YES
            edge_yes: Computed YES edge
            edge_no: Computed NO edge
            winner_side: Selected winner side
            strategy_intent: Strategy intent string
            price_cents: Contract price in cents
            min_edge: Minimum edge threshold (default 2%)
            
        Returns:
            ParityCycleDiagnostic with all check results
        """
        model_prob_no = 1.0 - model_prob_yes
        
        # Convert orderbook prices to fractions for parity checks
        yes_price = None
        no_price = None
        if yes_bid is not None and yes_ask is not None:
            yes_price = (yes_bid + yes_ask) / 2.0 / 100.0
        if no_bid is not None and no_ask is not None:
            no_price = (no_bid + no_ask) / 2.0 / 100.0
        
        # Run checks
        price_band_ok, band_violation_type = self.check_price_band(price_cents)
        price_parity_ok = self.check_price_parity(yes_price, no_price)
        edge_symmetry_ok = self.check_edge_symmetry(
            model_prob_yes, yes_price, no_price, edge_yes, edge_no
        )
        winner_correctness_ok = self.check_winner_correctness(
            edge_yes, edge_no, winner_side, min_edge
        )
        
        # Overall parity OK if all checks pass
        parity_ok = (
            price_parity_ok and
            edge_symmetry_ok and
            winner_correctness_ok
        )
        
        diagnostic = ParityCycleDiagnostic(
            cycle_id=cycle_id,
            market_id=market_id,
            asset=asset,
            expiry_ts=expiry_ts,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
            model_prob_yes=model_prob_yes,
            model_prob_no=model_prob_no,
            edge_yes=edge_yes,
            edge_no=edge_no,
            winner_side=winner_side,
            strategy_intent=strategy_intent,
            price_band_ok=price_band_ok,
            band_violation_type=band_violation_type,
            price_cents=price_cents,
            parity_ok=parity_ok,
            price_parity_ok=price_parity_ok,
            edge_symmetry_ok=edge_symmetry_ok,
            winner_correctness_ok=winner_correctness_ok,
            ts=int(datetime.now(timezone.utc).timestamp()),
        )
        
        # Log diagnostic
        self._log_diagnostic(diagnostic)
        
        return diagnostic
    
    def _log_diagnostic(self, diagnostic: ParityCycleDiagnostic) -> None:
        """Log diagnostic as structured JSON event."""
        log_record = {
            "check": "YES_NO_CYCLE_DIAGNOSTIC",
            "ok": diagnostic.parity_ok,
            "data": asdict(diagnostic),
        }
        
        if diagnostic.parity_ok:
            logger.debug("[YES_NO_DIAGNOSTIC] %s", json.dumps(log_record, indent=2))
        else:
            logger.warning("[YES_NO_DIAGNOSTIC_FAILURE] %s", json.dumps(log_record, indent=2))


# Singleton instance
_parity_cycle_monitor: Optional[ParityCycleMonitor] = None


def get_parity_cycle_monitor() -> ParityCycleMonitor:
    """Get singleton parity cycle monitor instance."""
    global _parity_cycle_monitor
    if _parity_cycle_monitor is None:
        _parity_cycle_monitor = ParityCycleMonitor()
    return _parity_cycle_monitor
