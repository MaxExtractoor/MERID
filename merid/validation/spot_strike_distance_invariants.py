"""
Cross-Layer Invariants: Spot→Strike Distance and Contract Selection

This module enforces invariants for spot→strike distance constraints to prevent
trading on contracts that are too far from the current spot price.

Key Invariants:
- Normalized distance δ = (strike - spot) / spot must be within allowed window
- Allowed δ window per strategy (e.g., |δ| < 0.1 for baseline scalps)
- No trades for contracts outside allowed δ window unless extreme edge
- Contract selection must be consistent with TA/intent mapping
- Deep OTM contracts blocked unless edge is extreme

Usage::

    from merid.validation.spot_strike_distance_invariants import (
        SpotStrikeDistanceInvariantChecker,
        check_spot_strike_distance,
        check_contract_selection_consistency,
        check_deep_otm_block
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from utils.logger import get_logger

logger = get_logger("merid.validation.spot_strike_distance_invariants")


class SpotStrikeDistanceViolation(str, Enum):
    """Types of spot-strike distance violations."""
    DISTANCE_EXCEEDED = "distance_exceeded"
    DEEP_OTM_WITHOUT_EXTREME_EDGE = "deep_otm_without_extreme_edge"
    CONTRACT_SELECTION_MISMATCH = "contract_selection_mismatch"
    INVALID_SPOT_PRICE = "invalid_spot_price"
    INVALID_STRIKE_PRICE = "invalid_strike_price"


@dataclass
class SpotStrikeDistanceCheckResult:
    """Result of spot-strike distance check."""
    is_valid: bool
    violation_type: Optional[SpotStrikeDistanceViolation]
    message: str
    context: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "violation_type": self.violation_type.value if self.violation_type else None,
            "message": self.message,
            "context": self.context,
        }


class SpotStrikeDistanceInvariantChecker:
    """Checks spot-strike distance invariants for contract selection."""
    
    def __init__(
        self,
        max_distance_delta: float = 0.1,  # 10% max distance for baseline strategy
        extreme_edge_threshold: float = 0.15,  # 15% edge required for deep OTM
        deep_otm_threshold_cents: int = 10,  # Contracts below 10c are deep OTM
    ):
        self.max_distance_delta = max_distance_delta
        self.extreme_edge_threshold = extreme_edge_threshold
        self.deep_otm_threshold_cents = deep_otm_threshold_cents
    
    def calculate_normalized_distance(
        self,
        spot_price: float,
        strike_price: float,
    ) -> float:
        """Calculate normalized distance δ = (strike - spot) / spot.
        
        Args:
            spot_price: Current spot price in USD
            strike_price: Contract strike price in USD
            
        Returns:
            Normalized distance δ (can be positive or negative)
        """
        if spot_price <= 0:
            raise ValueError(f"Invalid spot price: {spot_price}")
        
        return (strike_price - spot_price) / spot_price
    
    def check_spot_strike_distance(
        self,
        spot_price: float,
        strike_price: float,
        trade_emitted: bool,
        strategy_type: str = "baseline",
    ) -> SpotStrikeDistanceCheckResult:
        """INVARIANT: Spot→strike distance must be within allowed window for strategy.
        
        For each contract, compute normalized distance δ = (strike - spot) / spot.
        Define allowed windows per strategy (e.g., |δ| < 0.1 for baseline scalps).
        Assert no trades are produced for contracts outside allowed δ window.
        """
        context = {
            "spot_price": spot_price,
            "strike_price": strike_price,
            "trade_emitted": trade_emitted,
            "strategy_type": strategy_type,
            "max_distance_delta": self.max_distance_delta,
        }
        
        # Validate inputs
        if spot_price <= 0:
            return SpotStrikeDistanceCheckResult(
                is_valid=False,
                violation_type=SpotStrikeDistanceViolation.INVALID_SPOT_PRICE,
                message=f"Invalid spot price: {spot_price}",
                context=context,
            )
        
        if strike_price <= 0:
            return SpotStrikeDistanceCheckResult(
                is_valid=False,
                violation_type=SpotStrikeDistanceViolation.INVALID_STRIKE_PRICE,
                message=f"Invalid strike price: {strike_price}",
                context=context,
            )
        
        # Calculate normalized distance
        delta = self.calculate_normalized_distance(spot_price, strike_price)
        context["delta"] = delta
        
        # Check if distance exceeds allowed window
        if abs(delta) > self.max_distance_delta and trade_emitted:
            return SpotStrikeDistanceCheckResult(
                is_valid=False,
                violation_type=SpotStrikeDistanceViolation.DISTANCE_EXCEEDED,
                message=f"Spot-strike distance δ={delta:.4f} exceeds max={self.max_distance_delta} but trade emitted",
                context=context,
            )
        
        return SpotStrikeDistanceCheckResult(
            is_valid=True,
            violation_type=None,
            message=f"Spot-strike distance δ={delta:.4f} within allowed window",
            context=context,
        )
    
    def check_deep_otm_block(
        self,
        contract_price_cents: int,
        edge: float,
        trade_emitted: bool,
    ) -> SpotStrikeDistanceCheckResult:
        """INVARIANT: Deep OTM contracts blocked unless edge is extreme.
        
        Deep OTM contracts (price < threshold) are statistically losing unless
        the model has extreme confidence (edge > extreme_threshold).
        """
        context = {
            "contract_price_cents": contract_price_cents,
            "edge": edge,
            "trade_emitted": trade_emitted,
            "deep_otm_threshold_cents": self.deep_otm_threshold_cents,
            "extreme_edge_threshold": self.extreme_edge_threshold,
        }
        
        # Check if contract is deep OTM
        is_deep_otm = contract_price_cents < self.deep_otm_threshold_cents
        context["is_deep_otm"] = is_deep_otm
        
        if is_deep_otm and trade_emitted:
            # Deep OTM - require extreme edge
            if abs(edge) < self.extreme_edge_threshold:
                return SpotStrikeDistanceCheckResult(
                    is_valid=False,
                    violation_type=SpotStrikeDistanceViolation.DEEP_OTM_WITHOUT_EXTREME_EDGE,
                    message=f"Deep OTM contract (price={contract_price_cents}c < {self.deep_otm_threshold_cents}c) with insufficient edge={edge:.4f} < {self.extreme_edge_threshold}",
                    context=context,
                )
        
        return SpotStrikeDistanceCheckResult(
            is_valid=True,
            violation_type=None,
            message="Deep OTM check passed",
            context=context,
        )
    
    def check_contract_selection_consistency(
        self,
        ta_intent: str,  # "bullish" or "bearish"
        selected_contract_type: str,  # "yes" or "no"
        spot_price: float,
        strike_price: float,
        trade_emitted: bool,
    ) -> SpotStrikeDistanceCheckResult:
        """INVARIANT: Contract selection must be consistent with TA/intent mapping.
        
        Ensures that the mapping from TA/intent to allowed contract set is consistent.
        """
        context = {
            "ta_intent": ta_intent,
            "selected_contract_type": selected_contract_type,
            "spot_price": spot_price,
            "strike_price": strike_price,
            "trade_emitted": trade_emitted,
        }
        
        # Canonical mapping: bullish → YES, bearish → NO
        # (This is the CORRECT mapping per 2026-07-23 fix)
        expected_contract_type = "yes" if ta_intent == "bullish" else "no"
        
        if selected_contract_type != expected_contract_type and trade_emitted:
            return SpotStrikeDistanceCheckResult(
                is_valid=False,
                violation_type=SpotStrikeDistanceViolation.CONTRACT_SELECTION_MISMATCH,
                message=f"TA intent={ta_intent} expects contract_type={expected_contract_type} but selected={selected_contract_type}",
                context=context,
            )
        
        return SpotStrikeDistanceCheckResult(
            is_valid=True,
            violation_type=None,
            message="Contract selection consistent with TA intent",
            context=context,
        )
    
    def check_all_invariants(
        self,
        spot_price: float,
        strike_price: float,
        contract_price_cents: int,
        edge: float,
        ta_intent: str,
        selected_contract_type: str,
        trade_emitted: bool,
        strategy_type: str = "baseline",
    ) -> List[SpotStrikeDistanceCheckResult]:
        """Run all spot-strike distance invariants."""
        results = []
        
        # Check spot-strike distance
        result = self.check_spot_strike_distance(
            spot_price, strike_price, trade_emitted, strategy_type
        )
        results.append(result)
        
        # Check deep OTM block
        result = self.check_deep_otm_block(
            contract_price_cents, edge, trade_emitted
        )
        results.append(result)
        
        # Check contract selection consistency
        result = self.check_contract_selection_consistency(
            ta_intent, selected_contract_type, spot_price, strike_price, trade_emitted
        )
        results.append(result)
        
        return results


# Convenience functions for direct use

def check_spot_strike_distance(
    spot_price: float,
    strike_price: float,
    trade_emitted: bool,
    max_distance_delta: float = 0.1,
    strategy_type: str = "baseline",
) -> SpotStrikeDistanceCheckResult:
    """Check spot-strike distance invariant."""
    checker = SpotStrikeDistanceInvariantChecker(max_distance_delta=max_distance_delta)
    return checker.check_spot_strike_distance(
        spot_price, strike_price, trade_emitted, strategy_type
    )


def check_deep_otm_block(
    contract_price_cents: int,
    edge: float,
    trade_emitted: bool,
    deep_otm_threshold_cents: int = 10,
    extreme_edge_threshold: float = 0.15,
) -> SpotStrikeDistanceCheckResult:
    """Check deep OTM block invariant."""
    checker = SpotStrikeDistanceInvariantChecker(
        deep_otm_threshold_cents=deep_otm_threshold_cents,
        extreme_edge_threshold=extreme_edge_threshold,
    )
    return checker.check_deep_otm_block(contract_price_cents, edge, trade_emitted)


def check_contract_selection_consistency(
    ta_intent: str,
    selected_contract_type: str,
    spot_price: float,
    strike_price: float,
    trade_emitted: bool,
) -> SpotStrikeDistanceCheckResult:
    """Check contract selection consistency invariant."""
    checker = SpotStrikeDistanceInvariantChecker()
    return checker.check_contract_selection_consistency(
        ta_intent, selected_contract_type, spot_price, strike_price, trade_emitted
    )


# Synthetic test data generator for invariant testing

def generate_synthetic_spot_strike_distance_test_cases() -> List[Dict[str, Any]]:
    """Generate synthetic test cases for spot-strike distance invariants.
    
    Returns:
        List of test case dictionaries with controlled spot/strike conditions.
    """
    test_cases = []
    
    # Valid cases
    test_cases.append({
        "spot_price": 65000.0,
        "strike_price": 65000.0,
        "contract_price_cents": 50,
        "edge": 0.10,
        "ta_intent": "bullish",
        "selected_contract_type": "yes",
        "trade_emitted": True,
        "strategy_type": "baseline",
        "expected_valid": True,
        "description": "Spot equals strike (δ=0) - valid",
    })
    
    test_cases.append({
        "spot_price": 65000.0,
        "strike_price": 65500.0,
        "contract_price_cents": 45,
        "edge": 0.10,
        "ta_intent": "bullish",
        "selected_contract_type": "yes",
        "trade_emitted": True,
        "strategy_type": "baseline",
        "expected_valid": True,
        "description": "Spot-strike distance δ=0.0077 < 0.1 - valid",
    })
    
    test_cases.append({
        "spot_price": 65000.0,
        "strike_price": 65000.0,
        "contract_price_cents": 8,
        "edge": 0.20,
        "ta_intent": "bullish",
        "selected_contract_type": "yes",
        "trade_emitted": True,
        "strategy_type": "baseline",
        "expected_valid": True,
        "description": "Deep OTM (8c) but extreme edge (20%) - valid",
    })
    
    # Invalid cases (should trigger violations)
    test_cases.append({
        "spot_price": 65000.0,
        "strike_price": 72000.0,
        "contract_price_cents": 50,
        "edge": 0.10,
        "ta_intent": "bullish",
        "selected_contract_type": "yes",
        "trade_emitted": True,
        "strategy_type": "baseline",
        "expected_valid": False,
        "description": "Spot-strike distance δ=0.107 > 0.1 - violation",
    })
    
    test_cases.append({
        "spot_price": 65000.0,
        "strike_price": 65000.0,
        "contract_price_cents": 8,
        "edge": 0.10,
        "ta_intent": "bullish",
        "selected_contract_type": "yes",
        "trade_emitted": True,
        "strategy_type": "baseline",
        "expected_valid": False,
        "description": "Deep OTM (8c) without extreme edge (10%) - violation",
    })
    
    test_cases.append({
        "spot_price": 65000.0,
        "strike_price": 65000.0,
        "contract_price_cents": 50,
        "edge": 0.10,
        "ta_intent": "bullish",
        "selected_contract_type": "no",
        "trade_emitted": True,
        "strategy_type": "baseline",
        "expected_valid": False,
        "description": "Bullish intent but selected NO contract - violation",
    })
    
    test_cases.append({
        "spot_price": 65000.0,
        "strike_price": 65000.0,
        "contract_price_cents": 50,
        "edge": 0.10,
        "ta_intent": "bearish",
        "selected_contract_type": "yes",
        "trade_emitted": True,
        "strategy_type": "baseline",
        "expected_valid": False,
        "description": "Bearish intent but selected YES contract - violation",
    })
    
    return test_cases
