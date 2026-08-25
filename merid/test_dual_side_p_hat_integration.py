"""
Synthetic test hook for dual-side p_hat pipeline integration testing.

This module provides a controllable test endpoint to inject synthetic DualSideCandidate
objects with known p_hat values, allowing end-to-end testing of the dual-side edge-aware
microstructure gate without waiting for live signal generation.

Usage:
    from merid.test_dual_side_p_hat_integration import inject_synthetic_candidate
    inject_synthetic_candidate(ticker="BTC", side="yes", p_hat_yes_cents=60.0, p_hat_no_cents=40.0)
"""

import logging
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class SyntheticDualSideCandidate:
    """Synthetic candidate for testing dual-side p_hat pipeline."""
    ticker: str
    side: str  # "yes" or "no"
    price_cents: float
    count: int
    p_hat_yes_cents: float
    p_hat_no_cents: float
    edge_pct: float
    confidence: float
    model_prob: float
    yes_bid_cents: float
    yes_ask_cents: float
    no_bid_cents: float
    no_ask_cents: float
    yes_depth: int
    no_depth: int
    minutes_to_expiry: float
    strategy_intent: Optional[str] = None
    rationale: Optional[str] = None


def create_synthetic_candidate(
    ticker: str = "BTC",
    side: str = "yes",
    price_cents: float = 42.0,
    count: int = 1,
    p_hat_yes_cents: float = 60.0,
    p_hat_no_cents: float = 40.0,
    edge_pct: float = 0.18,  # 18% edge (60c - 42c) / 42c
    confidence: float = 0.75,
    yes_bid_cents: float = 41.0,
    yes_ask_cents: float = 43.0,
    no_bid_cents: float = 57.0,
    no_ask_cents: float = 59.0,
    yes_depth: int = 100,
    no_depth: int = 100,
    minutes_to_expiry: float = 10.0,
) -> SyntheticDualSideCandidate:
    """
    Create a synthetic DualSideCandidate with realistic parameters.
    
    Args:
        ticker: Asset ticker (BTC, ETH, SOL, XRP, DOGE)
        side: Order side ("yes" or "no")
        price_cents: Entry price in cents
        count: Number of contracts
        p_hat_yes_cents: Model-implied YES price in cents
        p_hat_no_cents: Model-implied NO price in cents
        edge_pct: Edge percentage
        confidence: Confidence score (0-1)
        yes_bid_cents: YES bid price
        yes_ask_cents: YES ask price
        no_bid_cents: NO bid price
        no_ask_cents: NO ask price
        yes_depth: YES depth at best bid
        no_depth: NO depth at best ask
        minutes_to_expiry: Time to expiry in minutes
    
    Returns:
        SyntheticDualSideCandidate object
    """
    model_prob = p_hat_yes_cents / 100.0
    
    return SyntheticDualSideCandidate(
        ticker=ticker,
        side=side,
        price_cents=price_cents,
        count=count,
        p_hat_yes_cents=p_hat_yes_cents,
        p_hat_no_cents=p_hat_no_cents,
        edge_pct=edge_pct,
        confidence=confidence,
        model_prob=model_prob,
        yes_bid_cents=yes_bid_cents,
        yes_ask_cents=yes_ask_cents,
        no_bid_cents=no_bid_cents,
        no_ask_cents=no_ask_cents,
        yes_depth=yes_depth,
        no_depth=no_depth,
        minutes_to_expiry=minutes_to_expiry,
        strategy_intent="bullish_event" if side == "yes" else "bearish_event",
        rationale=f"Synthetic test candidate for dual-side p_hat testing",
    )


def synthetic_candidate_to_dict(candidate: SyntheticDualSideCandidate) -> Dict[str, Any]:
    """Convert synthetic candidate to dictionary format expected by loop_15m."""
    candidate_dict = asdict(candidate)
    
    # Add additional fields expected by the loop
    candidate_dict.update({
        "selected_side": candidate.side,
        "selected_edge_exec_cents": candidate.edge_pct * candidate.price_cents / 100.0,
        "total_depth": candidate.yes_depth + candidate.no_depth,
        "yes_rejection_reason": None,
        "no_rejection_reason": None,
        "timestamp": datetime.now().timestamp(),
        "trace_id": f"synthetic_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "aggressiveness": 0.5,
        "order_type": "limit",
        "post_only": True,
    })
    
    return candidate_dict


def log_synthetic_candidate_injection(candidate: SyntheticDualSideCandidate):
    """Log synthetic candidate injection for debugging."""
    logger.info(
        "[SYNTHETIC-CANDIDATE-INJECTION] ticker=%s side=%s price=%dc count=%d "
        "p_hat_yes=%.1fc p_hat_no=%.1fc edge=%.2f%% confidence=%.2f%% "
        "spread=%dc-%dc depth_yes=%d depth_no=%d",
        candidate.ticker,
        candidate.side,
        candidate.price_cents,
        candidate.count,
        candidate.p_hat_yes_cents,
        candidate.p_hat_no_cents,
        candidate.edge_pct * 100,
        candidate.confidence * 100,
        candidate.yes_ask_cents - candidate.yes_bid_cents,
        candidate.no_ask_cents - candidate.no_bid_cents,
        candidate.yes_depth,
        candidate.no_depth,
    )


# Pre-configured test scenarios
TEST_SCENARIOS = {
    "passing_yes_candidate": {
        "ticker": "BTC",
        "side": "yes",
        "price_cents": 42.0,
        "p_hat_yes_cents": 60.0,
        "p_hat_no_cents": 40.0,
        "edge_pct": 0.18,  # 18% edge
        "yes_bid_cents": 41.0,
        "yes_ask_cents": 43.0,
        "no_bid_cents": 57.0,
        "no_ask_cents": 59.0,
        "spread_cents": 2.0,  # Tight spread
    },
    "passing_no_candidate": {
        "ticker": "ETH",
        "side": "no",
        "price_cents": 38.0,
        "p_hat_yes_cents": 62.0,
        "p_hat_no_cents": 38.0,
        "edge_pct": 0.16,  # 16% edge
        "yes_bid_cents": 61.0,
        "yes_ask_cents": 63.0,
        "no_bid_cents": 37.0,
        "no_ask_cents": 39.0,
        "spread_cents": 2.0,  # Tight spread
    },
    "wide_spread_yes_candidate": {
        "ticker": "SOL",
        "side": "yes",
        "price_cents": 45.0,
        "p_hat_yes_cents": 65.0,
        "p_hat_no_cents": 35.0,
        "edge_pct": 0.22,  # 22% edge
        "yes_bid_cents": 40.0,
        "yes_ask_cents": 50.0,  # Wide spread (10c)
        "no_bid_cents": 50.0,
        "no_ask_cents": 60.0,
        "spread_cents": 10.0,  # Wide spread
    },
}


def get_test_scenario(scenario_name: str) -> Dict[str, Any]:
    """Get a pre-configured test scenario by name."""
    if scenario_name not in TEST_SCENARIOS:
        raise ValueError(f"Unknown test scenario: {scenario_name}. Available: {list(TEST_SCENARIOS.keys())}")
    
    return TEST_SCENARIOS[scenario_name].copy()


def create_candidate_from_scenario(scenario_name: str) -> SyntheticDualSideCandidate:
    """Create a synthetic candidate from a pre-configured test scenario."""
    scenario = get_test_scenario(scenario_name)
    
    return create_synthetic_candidate(
        ticker=scenario["ticker"],
        side=scenario["side"],
        price_cents=scenario["price_cents"],
        p_hat_yes_cents=scenario["p_hat_yes_cents"],
        p_hat_no_cents=scenario["p_hat_no_cents"],
        edge_pct=scenario["edge_pct"],
        yes_bid_cents=scenario["yes_bid_cents"],
        yes_ask_cents=scenario["yes_ask_cents"],
        no_bid_cents=scenario["no_bid_cents"],
        no_ask_cents=scenario["no_ask_cents"],
    )


if __name__ == "__main__":
    # Test the synthetic candidate creation
    logging.basicConfig(level=logging.INFO)
    
    logger.info("Creating synthetic candidates for dual-side p_hat testing...")
    
    for scenario_name in TEST_SCENARIOS.keys():
        candidate = create_candidate_from_scenario(scenario_name)
        log_synthetic_candidate_injection(candidate)
        
        # Convert to dict
        candidate_dict = synthetic_candidate_to_dict(candidate)
        logger.info(f"Scenario {scenario_name}: Converted to dict with {len(candidate_dict)} fields")
    
    logger.info("Synthetic candidate creation test complete.")
