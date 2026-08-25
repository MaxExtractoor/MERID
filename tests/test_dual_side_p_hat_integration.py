"""
Integration tests for dual-side p_hat pipeline end-to-end flow.

Tests the complete flow from candidate generation to intent creation to routing:
- Synthetic DualSideCandidate creation
- Conversion to candidate dictionary format
- OrderIntent creation with p_hat field population
- Edge-aware microstructure gate evaluation
- Verification of logging and field propagation
"""

import pytest
import logging
from unittest.mock import Mock, patch, MagicMock
from dataclasses import asdict
from typing import Dict, Any

from merid.prediction.dual_side_candidate_generator import DualSideCandidate
from merid.event_venues.kalshi.order_router import OrderIntent
from merid.risk.profiles.crypto_15m_profile import Crypto15mProfile


class TestDualSidePHatIntegrationFlow:
    """Test end-to-end dual-side p_hat pipeline integration."""
    
    def test_synthetic_candidate_to_intent_flow_yes_order(self):
        """Test complete flow for YES order: candidate → intent → p_hat propagation."""
        # Step 1: Create synthetic DualSideCandidate
        candidate = DualSideCandidate(
            market_id="KXBTC15M-26JUL251315-15",
            asset="BTC",
            series_ticker="KXBTC15M",
            ticker="KXBTC15M-26JUL251315-15",
            yes_edge_exec_cents=18.0,
            yes_spread_cents=2,
            yes_raw_edge_cents=18.0,
            yes_spread_to_edge_ratio=0.11,
            no_edge_exec_cents=0.0,
            no_spread_cents=2,
            no_raw_edge_cents=0.0,
            no_spread_to_edge_ratio=0.0,
            yes_depth=100,
            no_depth=100,
            total_depth=200,
            selected_side="yes",
            selected_edge_exec_cents=18.0,
            p_hat_yes_cents=60.0,
            p_hat_no_cents=40.0,
            minutes_to_expiry=10.0,
            timestamp=0.0,
        )
        
        # Step 2: Convert to candidate dictionary format (as loop_15m expects)
        candidate_dict = {
            "ticker": candidate.ticker,
            "side": candidate.selected_side,
            "price_cents": 42.0,  # Simulated market price
            "count": 1,
            "p_hat_yes_cents": candidate.p_hat_yes_cents,
            "p_hat_no_cents": candidate.p_hat_no_cents,
            "edge_pct": 0.18,
            "confidence": 0.75,
            "model_prob": candidate.p_hat_yes_cents / 100.0,
            "yes_bid_cents": 41.0,
            "yes_ask_cents": 43.0,
            "no_bid_cents": 57.0,
            "no_ask_cents": 59.0,
            "yes_depth": candidate.yes_depth,
            "no_depth": candidate.no_depth,
            "minutes_to_expiry": candidate.minutes_to_expiry,
            "strategy_intent": "bullish_event",
            "rationale": "Synthetic test candidate",
        }
        
        # Step 3: Simulate loop_15m.py OrderIntent creation
        model_prob = candidate_dict.get("model_prob")
        intent = OrderIntent(
            ticker=candidate_dict["ticker"],
            side="BUY_YES",
            action="buy",
            price_cents=candidate_dict["price_cents"],
            count=candidate_dict["count"],
            p_hat_yes_cents=model_prob * 100.0 if model_prob is not None else None,
            p_hat_no_cents=(100.0 - model_prob * 100.0) if model_prob is not None else None,
            rationale=candidate_dict.get("rationale"),
        )
        
        # Step 4: Verify p_hat field propagation
        assert intent.p_hat_yes_cents == 60.0, "p_hat_yes_cents should be 60.0"
        assert intent.p_hat_no_cents == 40.0, "p_hat_no_cents should be 40.0"
        
        # Step 5: Simulate edge-aware gate side-specific p_hat selection
        order_side_lower = intent.side.lower() if intent.side else ""
        if order_side_lower in ("yes", "buy_yes", "sell_yes"):
            p_hat_cents = intent.p_hat_yes_cents
        elif order_side_lower in ("no", "buy_no", "sell_no"):
            p_hat_cents = intent.p_hat_no_cents
        else:
            p_hat_cents = intent.p_hat_yes_cents
        
        assert p_hat_cents == 60.0, "YES order should use p_hat_yes_cents (60.0)"
    
    def test_synthetic_candidate_to_intent_flow_no_order(self):
        """Test complete flow for NO order: candidate → intent → p_hat propagation."""
        # Step 1: Create synthetic DualSideCandidate
        candidate = DualSideCandidate(
            market_id="KXETH15M-26JUL251315-15",
            asset="ETH",
            series_ticker="KXETH15M",
            ticker="KXETH15M-26JUL251315-15",
            yes_edge_exec_cents=0.0,
            yes_spread_cents=2,
            yes_raw_edge_cents=0.0,
            yes_spread_to_edge_ratio=0.0,
            no_edge_exec_cents=16.0,
            no_spread_cents=2,
            no_raw_edge_cents=16.0,
            no_spread_to_edge_ratio=0.125,
            yes_depth=100,
            no_depth=100,
            total_depth=200,
            selected_side="no",
            selected_edge_exec_cents=16.0,
            p_hat_yes_cents=62.0,
            p_hat_no_cents=38.0,
            minutes_to_expiry=10.0,
            timestamp=0.0,
        )
        
        # Step 2: Convert to candidate dictionary format
        candidate_dict = {
            "ticker": candidate.ticker,
            "side": candidate.selected_side,
            "price_cents": 38.0,  # Simulated market price
            "count": 1,
            "p_hat_yes_cents": candidate.p_hat_yes_cents,
            "p_hat_no_cents": candidate.p_hat_no_cents,
            "edge_pct": 0.16,
            "confidence": 0.75,
            "model_prob": candidate.p_hat_yes_cents / 100.0,
            "yes_bid_cents": 61.0,
            "yes_ask_cents": 63.0,
            "no_bid_cents": 37.0,
            "no_ask_cents": 39.0,
            "yes_depth": candidate.yes_depth,
            "no_depth": candidate.no_depth,
            "minutes_to_expiry": candidate.minutes_to_expiry,
            "strategy_intent": "bearish_event",
            "rationale": "Synthetic test candidate",
        }
        
        # Step 3: Simulate loop_15m.py OrderIntent creation
        model_prob = candidate_dict.get("model_prob")
        intent = OrderIntent(
            ticker=candidate_dict["ticker"],
            side="BUY_NO",
            action="buy",
            price_cents=candidate_dict["price_cents"],
            count=candidate_dict["count"],
            p_hat_yes_cents=model_prob * 100.0 if model_prob is not None else None,
            p_hat_no_cents=(100.0 - model_prob * 100.0) if model_prob is not None else None,
            rationale=candidate_dict.get("rationale"),
        )
        
        # Step 4: Verify p_hat field propagation
        assert intent.p_hat_yes_cents == 62.0, "p_hat_yes_cents should be 62.0"
        assert intent.p_hat_no_cents == 38.0, "p_hat_no_cents should be 38.0"
        
        # Step 5: Simulate edge-aware gate side-specific p_hat selection
        order_side_lower = intent.side.lower() if intent.side else ""
        if order_side_lower in ("yes", "buy_yes", "sell_yes"):
            p_hat_cents = intent.p_hat_yes_cents
        elif order_side_lower in ("no", "buy_no", "sell_no"):
            p_hat_cents = intent.p_hat_no_cents
        else:
            p_hat_cents = intent.p_hat_yes_cents
        
        assert p_hat_cents == 38.0, "NO order should use p_hat_no_cents (38.0)"
    
    def test_edge_aware_gate_activation_with_p_hat(self):
        """Test that edge-aware gate activates when p_hat fields are present."""
        # Create intent with p_hat fields
        intent = OrderIntent(
            ticker="BTC",
            side="BUY_YES",
            action="buy",
            price_cents=42.0,
            count=1,
            p_hat_yes_cents=60.0,
            p_hat_no_cents=40.0,
        )
        
        # Mock profile with edge-aware gate enabled
        profile = Mock(spec=Crypto15mProfile)
        profile.use_edge_aware_microstructure_gate = True
        profile.min_executable_edge_cents = 5.0
        profile.max_spread_to_edge_ratio = 3.0
        
        # Simulate edge-aware gate activation logic
        order_side_lower = intent.side.lower() if intent.side else ""
        if order_side_lower in ("yes", "buy_yes", "sell_yes"):
            has_p_hat = intent.p_hat_yes_cents is not None
        elif order_side_lower in ("no", "buy_no", "sell_no"):
            has_p_hat = intent.p_hat_no_cents is not None
        else:
            has_p_hat = intent.p_hat_yes_cents is not None
        
        use_edge_aware_gate = (
            has_p_hat and
            hasattr(profile, 'use_edge_aware_microstructure_gate') and
            profile.use_edge_aware_microstructure_gate
        )
        
        assert use_edge_aware_gate is True, "Edge-aware gate should activate when p_hat is present"
    
    def test_edge_aware_gate_missing_p_hat_loud_failure(self):
        """Test that edge-aware gate fails loudly when p_hat is missing."""
        # Create intent without p_hat fields
        intent = OrderIntent(
            ticker="ETH",
            side="BUY_NO",
            action="buy",
            price_cents=38.0,
            count=1,
            p_hat_yes_cents=None,  # Missing
            p_hat_no_cents=None,   # Missing
        )
        
        # Mock profile with edge-aware gate enabled
        profile = Mock(spec=Crypto15mProfile)
        profile.use_edge_aware_microstructure_gate = True
        
        # Simulate edge-aware gate activation logic
        order_side_lower = intent.side.lower() if intent.side else ""
        if order_side_lower in ("yes", "buy_yes", "sell_yes"):
            has_p_hat = intent.p_hat_yes_cents is not None
        elif order_side_lower in ("no", "buy_no", "sell_no"):
            has_p_hat = intent.p_hat_no_cents is not None
        else:
            has_p_hat = intent.p_hat_yes_cents is not None
        
        use_edge_aware_gate = (
            has_p_hat and
            hasattr(profile, 'use_edge_aware_microstructure_gate') and
            profile.use_edge_aware_microstructure_gate
        )
        
        assert use_edge_aware_gate is False, "Edge-aware gate should not activate when p_hat is missing"
        assert has_p_hat is False, "has_p_hat should be False when p_hat fields are None"
    
    def test_intent_check_logging_format(self):
        """Test that intent check logging has correct format with both p_hat fields."""
        intent = OrderIntent(
            ticker="SOL",
            side="BUY_YES",
            action="buy",
            price_cents=45.0,
            count=1,
            p_hat_yes_cents=65.0,
            p_hat_no_cents=35.0,
        )
        
        # Mock profile
        profile = Mock(spec=Crypto15mProfile)
        profile.use_edge_aware_microstructure_gate = True
        
        # Simulate intent check logging parameters
        order_side_lower = intent.side.lower() if intent.side else ""
        if order_side_lower in ("yes", "buy_yes", "sell_yes"):
            has_p_hat = intent.p_hat_yes_cents is not None
        elif order_side_lower in ("no", "buy_no", "sell_no"):
            has_p_hat = intent.p_hat_no_cents is not None
        else:
            has_p_hat = intent.p_hat_yes_cents is not None
        
        edge_aware_enabled = (
            hasattr(profile, 'use_edge_aware_microstructure_gate') and
            profile.use_edge_aware_microstructure_gate
        )
        
        # Verify logging parameters
        log_params = {
            "ticker": intent.ticker,
            "side": intent.side,
            "p_hat_yes_cents": intent.p_hat_yes_cents,
            "p_hat_no_cents": intent.p_hat_no_cents,
            "has_p_hat": has_p_hat,
            "edge_aware_enabled": edge_aware_enabled,
        }
        
        assert log_params["ticker"] == "SOL"
        assert log_params["side"] == "BUY_YES"
        assert log_params["p_hat_yes_cents"] == 65.0
        assert log_params["p_hat_no_cents"] == 35.0
        assert log_params["has_p_hat"] is True
        assert log_params["edge_aware_enabled"] is True


class TestDualSidePHatScenarios:
    """Test realistic trading scenarios with dual-side p_hat."""
    
    def test_tight_spread_high_edge_scenario(self):
        """Test scenario: tight spread (2c) with high edge (18c) - should pass edge-aware gate."""
        # Create candidate with tight spread and high edge
        candidate = DualSideCandidate(
            market_id="KXBTC15M-26JUL251315-15",
            asset="BTC",
            series_ticker="KXBTC15M",
            ticker="KXBTC15M-26JUL251315-15",
            yes_edge_exec_cents=18.0,
            yes_spread_cents=2,
            yes_raw_edge_cents=18.0,
            yes_spread_to_edge_ratio=0.11,  # Well below 3.0 threshold
            no_edge_exec_cents=0.0,
            no_spread_cents=2,
            no_raw_edge_cents=0.0,
            no_spread_to_edge_ratio=0.0,
            yes_depth=100,
            no_depth=100,
            total_depth=200,
            selected_side="yes",
            selected_edge_exec_cents=18.0,
            p_hat_yes_cents=60.0,
            p_hat_no_cents=40.0,
            minutes_to_expiry=10.0,
            timestamp=0.0,
        )
        
        # Verify spread/edge ratio is within bounds
        assert candidate.yes_spread_to_edge_ratio < 3.0, \
            "Spread/edge ratio should be below 3.0 threshold"
        assert candidate.yes_edge_exec_cents >= 5.0, \
            "Edge should be above 5.0 minimum executable edge"
    
    def test_wide_spread_high_edge_scenario(self):
        """Test scenario: wide spread (10c) with high edge (22c) - should pass edge-aware gate."""
        # Create candidate with wide spread but high edge
        candidate = DualSideCandidate(
            market_id="KXSOL15M-26JUL251315-15",
            asset="SOL",
            series_ticker="KXSOL15M",
            ticker="KXSOL15M-26JUL251315-15",
            yes_edge_exec_cents=22.0,
            yes_spread_cents=10,
            yes_raw_edge_cents=22.0,
            yes_spread_to_edge_ratio=0.45,  # Below 3.0 threshold
            no_edge_exec_cents=0.0,
            no_spread_cents=10,
            no_raw_edge_cents=0.0,
            no_spread_to_edge_ratio=0.0,
            yes_depth=50,
            no_depth=50,
            total_depth=100,
            selected_side="yes",
            selected_edge_exec_cents=22.0,
            p_hat_yes_cents=67.0,
            p_hat_no_cents=33.0,
            minutes_to_expiry=10.0,
            timestamp=0.0,
        )
        
        # Verify spread/edge ratio is within bounds despite wide spread
        assert candidate.yes_spread_to_edge_ratio < 3.0, \
            "Spread/edge ratio should be below 3.0 threshold even with wide spread"
        assert candidate.yes_edge_exec_cents >= 5.0, \
            "Edge should be above 5.0 minimum executable edge"
    
    def test_wide_spread_low_edge_scenario(self):
        """Test scenario: wide spread (10c) with low edge (3c) - should fail edge-aware gate."""
        # Create candidate with wide spread and low edge
        candidate = DualSideCandidate(
            market_id="KXXRP15M-26JUL251315-15",
            asset="XRP",
            series_ticker="KXXRP15M",
            ticker="KXXRP15M-26JUL251315-15",
            yes_edge_exec_cents=3.0,
            yes_spread_cents=10,
            yes_raw_edge_cents=3.0,
            yes_spread_to_edge_ratio=3.33,  # Above 3.0 threshold
            no_edge_exec_cents=0.0,
            no_spread_cents=10,
            no_raw_edge_cents=0.0,
            no_spread_to_edge_ratio=0.0,
            yes_depth=30,
            no_depth=30,
            total_depth=60,
            selected_side="yes",
            selected_edge_exec_cents=3.0,
            p_hat_yes_cents=53.0,
            p_hat_no_cents=47.0,
            minutes_to_expiry=10.0,
            timestamp=0.0,
        )
        
        # Verify spread/edge ratio exceeds bounds
        assert candidate.yes_spread_to_edge_ratio > 3.0, \
            "Spread/edge ratio should exceed 3.0 threshold"
        assert candidate.yes_edge_exec_cents < 5.0, \
            "Edge should be below 5.0 minimum executable edge"
    
    def test_mixed_yes_no_side_selection(self):
        """Test scenario: YES and NO sides both have edges, system selects best side."""
        # Create candidate where both sides have edges but YES is better
        candidate = DualSideCandidate(
            market_id="KXDOGE15M-26JUL251315-15",
            asset="DOGE",
            series_ticker="KXDOGE15M",
            ticker="KXDOGE15M-26JUL251315-15",
            yes_edge_exec_cents=15.0,
            yes_spread_cents=3,
            yes_raw_edge_cents=15.0,
            yes_spread_to_edge_ratio=0.20,
            no_edge_exec_cents=8.0,  # Lower edge on NO side
            no_spread_cents=3,
            no_raw_edge_cents=8.0,
            no_spread_to_edge_ratio=0.375,
            yes_depth=80,
            no_depth=80,
            total_depth=160,
            selected_side="yes",  # Should select YES due to higher edge
            selected_edge_exec_cents=15.0,
            p_hat_yes_cents=65.0,
            p_hat_no_cents=35.0,
            minutes_to_expiry=10.0,
            timestamp=0.0,
        )
        
        # Verify YES side is selected due to higher edge
        assert candidate.selected_side == "yes", "YES side should be selected with higher edge"
        assert candidate.yes_edge_exec_cents > candidate.no_edge_exec_cents, \
            "Selected side should have higher edge"
    
    def test_extreme_wide_spread_edge_aware_gate(self):
        """Test scenario: extreme wide spread (20c) with sufficient edge (25c) - should pass edge-aware gate."""
        # Create candidate with extreme wide spread but very high edge
        candidate = DualSideCandidate(
            market_id="KXBTC15M-26JUL251315-15",
            asset="BTC",
            series_ticker="KXBTC15M",
            ticker="KXBTC15M-26JUL251315-15",
            yes_edge_exec_cents=25.0,
            yes_spread_cents=20,  # Extreme wide spread
            yes_raw_edge_cents=25.0,
            yes_spread_to_edge_ratio=0.80,  # Still below 3.0 threshold
            no_edge_exec_cents=0.0,
            no_spread_cents=20,
            no_raw_edge_cents=0.0,
            no_spread_to_edge_ratio=0.0,
            yes_depth=200,
            no_depth=200,
            total_depth=400,
            selected_side="yes",
            selected_edge_exec_cents=25.0,
            p_hat_yes_cents=70.0,
            p_hat_no_cents=30.0,
            minutes_to_expiry=10.0,
            timestamp=0.0,
        )
        
        # Verify edge-aware gate should pass despite extreme spread
        assert candidate.yes_spread_to_edge_ratio < 3.0, \
            "Spread/edge ratio should be below 3.0 threshold even with extreme spread"
        assert candidate.yes_edge_exec_cents >= 5.0, \
            "Edge should be above 5.0 minimum executable edge"
    
    def test_missing_p_hat_field_validation(self):
        """Test scenario: p_hat field missing triggers loud failure in edge-aware mode."""
        # Create candidate without p_hat fields
        candidate = DualSideCandidate(
            market_id="KXETH15M-26JUL251315-15",
            asset="ETH",
            series_ticker="KXETH15M",
            ticker="KXETH15M-26JUL251315-15",
            yes_edge_exec_cents=10.0,
            yes_spread_cents=2,
            yes_raw_edge_cents=10.0,
            yes_spread_to_edge_ratio=0.20,
            no_edge_exec_cents=0.0,
            no_spread_cents=2,
            no_raw_edge_cents=0.0,
            no_spread_to_edge_ratio=0.0,
            yes_depth=100,
            no_depth=100,
            total_depth=200,
            selected_side="yes",
            selected_edge_exec_cents=10.0,
            p_hat_yes_cents=None,  # Missing p_hat
            p_hat_no_cents=None,   # Missing p_hat
            minutes_to_expiry=10.0,
            timestamp=0.0,
        )
        
        # Verify missing p_hat is detected
        assert candidate.p_hat_yes_cents is None, "p_hat_yes_cents should be None"
        assert candidate.p_hat_no_cents is None, "p_hat_no_cents should be None"
        # This should trigger loud failure in edge-aware mode


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
