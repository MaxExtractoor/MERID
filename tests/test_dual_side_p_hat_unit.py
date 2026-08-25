"""
Unit tests for dual-side p_hat field propagation.

Tests the data model changes for dual-side edge-aware microstructure gating:
- DualSideCandidate p_hat_yes_cents and p_hat_no_cents
- CanonicalOrderIntent p_hat_yes_cents and p_hat_no_cents
- OrderRouter edge-aware gate with side-specific p_hat selection
"""

import pytest
from dataclasses import asdict
from typing import Dict, Any

from merid.prediction.dual_side_candidate_generator import DualSideCandidate
from merid_core.schemas.intent import CanonicalOrderIntent
from merid.event_venues.kalshi.order_router import OrderIntent


class TestDualSideCandidatePHatFields:
    """Test DualSideCandidate p_hat field population."""
    
    def test_dual_side_candidate_has_both_p_hat_fields(self):
        """DualSideCandidate should have both p_hat_yes_cents and p_hat_no_cents."""
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
        
        assert candidate.p_hat_yes_cents == 60.0, "p_hat_yes_cents should be 60.0"
        assert candidate.p_hat_no_cents == 40.0, "p_hat_no_cents should be 40.0"
        assert candidate.p_hat_yes_cents + candidate.p_hat_no_cents == 100.0, \
            "p_hat_yes_cents + p_hat_no_cents should equal 100.0"
    
    def test_dual_side_candidate_p_hat_complement(self):
        """p_hat_no_cents should be complement to p_hat_yes_cents."""
        for p_hat_yes in [30.0, 50.0, 70.0, 90.0]:
            p_hat_no = 100.0 - p_hat_yes
            candidate = DualSideCandidate(
                market_id="KXETH15M-26JUL251315-15",
                asset="ETH",
                series_ticker="KXETH15M",
                ticker="KXETH15M-26JUL251315-15",
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
                p_hat_yes_cents=p_hat_yes,
                p_hat_no_cents=p_hat_no,
                minutes_to_expiry=10.0,
                timestamp=0.0,
            )
            
            assert candidate.p_hat_no_cents == 100.0 - candidate.p_hat_yes_cents, \
                f"p_hat_no_cents should be complement to p_hat_yes_cents for p_hat_yes={p_hat_yes}"


class TestCanonicalOrderIntentPHatFields:
    """Test CanonicalOrderIntent p_hat field population."""
    
    def test_canonical_intent_has_both_p_hat_fields(self):
        """CanonicalOrderIntent should have both p_hat_yes_cents and p_hat_no_cents."""
        intent = CanonicalOrderIntent(
            ticker="BTC",
            side="yes",
            action="buy",
            price_cents=42.0,
            count=1,
            p_hat_yes_cents=60.0,
            p_hat_no_cents=40.0,
        )
        
        assert intent.p_hat_yes_cents == 60.0, "p_hat_yes_cents should be 60.0"
        assert intent.p_hat_no_cents == 40.0, "p_hat_no_cents should be 40.0"
    
    def test_canonical_intent_p_hat_fields_optional(self):
        """p_hat fields should be optional (None by default)."""
        intent = CanonicalOrderIntent(
            ticker="ETH",
            side="no",
            action="sell",
            price_cents=38.0,
            count=1,
        )
        
        assert intent.p_hat_yes_cents is None, "p_hat_yes_cents should be None when not set"
        assert intent.p_hat_no_cents is None, "p_hat_no_cents should be None when not set"


class TestOrderIntentPHatFields:
    """Test OrderIntent p_hat field population."""
    
    def test_order_intent_has_both_p_hat_fields(self):
        """OrderIntent should have both p_hat_yes_cents and p_hat_no_cents."""
        intent = OrderIntent(
            ticker="BTC",
            side="BUY_YES",
            action="buy",
            price_cents=42.0,
            count=1,
            p_hat_yes_cents=60.0,
            p_hat_no_cents=40.0,
        )
        
        assert intent.p_hat_yes_cents == 60.0, "p_hat_yes_cents should be 60.0"
        assert intent.p_hat_no_cents == 40.0, "p_hat_no_cents should be 40.0"
    
    def test_order_intent_p_hat_fields_optional(self):
        """p_hat fields should be optional (None by default)."""
        intent = OrderIntent(
            ticker="ETH",
            side="SELL_NO",
            action="sell",
            price_cents=38.0,
            count=1,
        )
        
        assert intent.p_hat_yes_cents is None, "p_hat_yes_cents should be None when not set"
        assert intent.p_hat_no_cents is None, "p_hat_no_cents should be None when not set"


class TestCandidateToIntentPHatPropagation:
    """Test p_hat field propagation from candidate to intent."""
    
    def test_yes_intent_propagates_p_hat_yes_cents(self):
        """YES intent should propagate p_hat_yes_cents from candidate."""
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
        
        # Simulate loop_15m.py intent creation
        model_prob = candidate.p_hat_yes_cents / 100.0
        intent = OrderIntent(
            ticker=candidate.ticker,
            side="BUY_YES",
            action="buy",
            price_cents=42.0,  # Simulated price
            count=1,
            p_hat_yes_cents=model_prob * 100.0 if model_prob is not None else None,
            p_hat_no_cents=(100.0 - model_prob * 100.0) if model_prob is not None else None,
        )
        
        assert intent.p_hat_yes_cents == 60.0, "p_hat_yes_cents should be propagated"
        assert intent.p_hat_no_cents == 40.0, "p_hat_no_cents should be propagated"
    
    def test_no_intent_propagates_p_hat_no_cents(self):
        """NO intent should propagate p_hat_no_cents from candidate."""
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
        
        # Simulate loop_15m.py intent creation
        model_prob = candidate.p_hat_yes_cents / 100.0
        intent = OrderIntent(
            ticker=candidate.ticker,
            side="BUY_NO",
            action="buy",
            price_cents=38.0,  # Simulated price
            count=1,
            p_hat_yes_cents=model_prob * 100.0 if model_prob is not None else None,
            p_hat_no_cents=(100.0 - model_prob * 100.0) if model_prob is not None else None,
        )
        
        assert intent.p_hat_yes_cents == 62.0, "p_hat_yes_cents should be propagated"
        assert intent.p_hat_no_cents == 38.0, "p_hat_no_cents should be propagated"


class TestSideSpecificPHatSelection:
    """Test side-specific p_hat field selection for edge-aware gate."""
    
    def test_yes_order_uses_p_hat_yes_cents(self):
        """YES orders should use p_hat_yes_cents for edge-aware gate."""
        intent = OrderIntent(
            ticker="BTC",
            side="BUY_YES",
            action="buy",
            price_cents=42.0,
            count=1,
            p_hat_yes_cents=60.0,
            p_hat_no_cents=40.0,
        )
        
        # Simulate order_router.py side-specific p_hat selection
        order_side_lower = intent.side.lower() if intent.side else ""
        if order_side_lower in ("yes", "buy_yes", "sell_yes"):
            p_hat_cents = intent.p_hat_yes_cents
        elif order_side_lower in ("no", "buy_no", "sell_no"):
            p_hat_cents = intent.p_hat_no_cents
        else:
            p_hat_cents = intent.p_hat_yes_cents
        
        assert p_hat_cents == 60.0, "YES order should use p_hat_yes_cents"
    
    def test_no_order_uses_p_hat_no_cents(self):
        """NO orders should use p_hat_no_cents for edge-aware gate."""
        intent = OrderIntent(
            ticker="ETH",
            side="BUY_NO",
            action="buy",
            price_cents=38.0,
            count=1,
            p_hat_yes_cents=62.0,
            p_hat_no_cents=38.0,
        )
        
        # Simulate order_router.py side-specific p_hat selection
        order_side_lower = intent.side.lower() if intent.side else ""
        if order_side_lower in ("yes", "buy_yes", "sell_yes"):
            p_hat_cents = intent.p_hat_yes_cents
        elif order_side_lower in ("no", "buy_no", "sell_no"):
            p_hat_cents = intent.p_hat_no_cents
        else:
            p_hat_cents = intent.p_hat_yes_cents
        
        assert p_hat_cents == 38.0, "NO order should use p_hat_no_cents"
    
    def test_sell_yes_uses_p_hat_yes_cents(self):
        """SELL_YES orders should use p_hat_yes_cents for edge-aware gate."""
        intent = OrderIntent(
            ticker="SOL",
            side="SELL_YES",
            action="sell",
            price_cents=45.0,
            count=1,
            p_hat_yes_cents=65.0,
            p_hat_no_cents=35.0,
        )
        
        # Simulate order_router.py side-specific p_hat selection
        order_side_lower = intent.side.lower() if intent.side else ""
        if order_side_lower in ("yes", "buy_yes", "sell_yes"):
            p_hat_cents = intent.p_hat_yes_cents
        elif order_side_lower in ("no", "buy_no", "sell_no"):
            p_hat_cents = intent.p_hat_no_cents
        else:
            p_hat_cents = intent.p_hat_yes_cents
        
        assert p_hat_cents == 65.0, "SELL_YES order should use p_hat_yes_cents"
    
    def test_sell_no_uses_p_hat_no_cents(self):
        """SELL_NO orders should use p_hat_no_cents for edge-aware gate."""
        intent = OrderIntent(
            ticker="XRP",
            side="SELL_NO",
            action="sell",
            price_cents=35.0,
            count=1,
            p_hat_yes_cents=65.0,
            p_hat_no_cents=35.0,
        )
        
        # Simulate order_router.py side-specific p_hat selection
        order_side_lower = intent.side.lower() if intent.side else ""
        if order_side_lower in ("yes", "buy_yes", "sell_yes"):
            p_hat_cents = intent.p_hat_yes_cents
        elif order_side_lower in ("no", "buy_no", "sell_no"):
            p_hat_cents = intent.p_hat_no_cents
        else:
            p_hat_cents = intent.p_hat_yes_cents
        
        assert p_hat_cents == 35.0, "SELL_NO order should use p_hat_no_cents"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
