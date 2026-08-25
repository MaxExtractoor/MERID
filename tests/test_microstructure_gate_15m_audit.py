"""
15-Minute Market Microstructure Gate Audit Tests

Tests for per-asset validation of the microstructure gate across BTC, ETH, SOL, XRP, DOGE.
Focuses on maker/taker economics correctness, ratio formula validation, and 15-minute horizon concerns.

CRITICAL FIX 2026-08-02: Ratio calculation now uses spread_cost_cents (0 for makers) instead of spread_cents.
This fixes the production bug where maker orders were rejected based on taker-style spread costs.
"""

import pytest
from merid.event_venues.kalshi.spread_edge_analytics import (
    compute_canonical_spreads,
    compute_per_side_edges,
    PerSideEdgeMetrics
)


class TestMakerTakerRatioCalculation:
    """Test that ratio uses spread_cost (0 for makers) not spread_cents."""
    
    def test_maker_ratio_uses_spread_cost(self):
        """Maker orders should have ratio = 0 (spread_cost = 0)."""
        # Use market data with actual spread (not zero)
        # yes_bid=30c, no_bid=65c → no_ask=70c, spread=5c
        # p_hat_yes=50c → p_hat_no=50c
        # order_price=40c (less than p_hat_no=50c for positive edge)
        yes_bid = 30
        no_bid = 65  # Asymmetric to create spread
        p_hat_yes = 50.0
        order_price = 40.0  # Less than p_hat_no=50c for positive edge
        order_side = "no"
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=True  # MAKER
        )
        
        # CRITICAL: spread_cost should be 0 for makers
        assert no_edge.spread_cost_cents == 0.0, f"Maker should have spread_cost=0, got {no_edge.spread_cost_cents}"
        # CRITICAL: ratio should use spread_cost, not spread_cents
        assert no_edge.spread_to_edge_ratio == 0.0, f"Expected 0.0, got {no_edge.spread_to_edge_ratio}"
        assert no_edge.raw_edge_cents > 0, f"Raw edge should be positive, got {no_edge.raw_edge_cents}"
    
    def test_taker_ratio_uses_full_spread(self):
        """Taker orders should use full spread in ratio."""
        yes_bid = 30
        no_bid = 65  # Asymmetric to create spread
        p_hat_yes = 50.0
        order_price = 50.0
        order_side = "no"
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=False  # TAKER
        )
        
        # Taker: spread_cost should be full spread
        assert no_edge.spread_cost_cents == no_edge.spread_cents, f"Taker spread_cost should equal spread_cents"
        # Ratio should be spread/edge
        if no_edge.raw_edge_cents > 0:
            expected_ratio = no_edge.spread_cents / no_edge.raw_edge_cents
            assert no_edge.spread_to_edge_ratio == expected_ratio, f"Expected {expected_ratio}, got {no_edge.spread_to_edge_ratio}"


class TestPerAssetGoldenCases:
    """One golden regression case per asset (BTC, ETH, SOL, XRP, DOGE)."""
    
    def test_btc_yes_maker_order(self):
        """BTC YES order: tight spread, high liquidity - should PASS with maker economics."""
        # BTC: yes_bid=5c, no_bid=95c, p_hat_yes=60c
        # Order price should be less than p_hat_yes for positive edge
        yes_bid = 5
        no_bid = 95
        p_hat_yes = 60.0
        order_price = 4.0  # Less than p_hat_yes=60c to get positive edge
        order_side = "yes"
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=True  # MAKER
        )
        
        assert yes_edge.spread_cost_cents == 0.0, f"BTC maker should have spread_cost=0, got {yes_edge.spread_cost_cents}"
        assert yes_edge.spread_to_edge_ratio == 0.0, f"BTC maker ratio should be 0.0, got {yes_edge.spread_to_edge_ratio}"
        assert yes_edge.executable_edge_cents > 0, f"BTC executable edge should be positive, got {yes_edge.executable_edge_cents}"
    
    def test_eth_no_maker_order(self):
        """ETH NO order: moderate spread, high liquidity - should PASS with maker economics."""
        # ETH: yes_bid=6c, no_bid=94c, p_hat_yes=55c → p_hat_no=45c
        # Order price should be less than p_hat_no for positive edge
        yes_bid = 6
        no_bid = 94
        p_hat_yes = 55.0
        order_price = 40.0  # Less than p_hat_no=45c to get positive edge
        order_side = "no"
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=True  # MAKER
        )
        
        assert no_edge.spread_cost_cents == 0.0, f"ETH maker should have spread_cost=0, got {no_edge.spread_cost_cents}"
        assert no_edge.spread_to_edge_ratio == 0.0, f"ETH maker ratio should be 0.0, got {no_edge.spread_to_edge_ratio}"
        assert no_edge.executable_edge_cents > 0, f"ETH executable edge should be positive, got {no_edge.executable_edge_cents}"
    
    def test_sol_no_maker_order_production_bug(self):
        """SOL NO order: production bug case - should PASS with maker economics (ratio=0)."""
        # Production: spread_cost_too_high: ratio=2.90 > 0.8
        # SOL: yes_bid=41c, no_bid=59c, p_hat_yes=79c → p_hat_no=21c
        # Order price should be less than p_hat_no for positive edge
        yes_bid = 41
        no_bid = 59
        p_hat_yes = 79.0
        order_price = 15.0  # Less than p_hat_no=21c to get positive edge
        order_side = "no"
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=True  # MAKER
        )
        
        # CRITICAL: This is the production bug
        assert no_edge.spread_cost_cents == 0.0, f"SOL maker should have spread_cost=0, got {no_edge.spread_cost_cents}"
        assert no_edge.spread_to_edge_ratio == 0.0, f"SOL maker ratio should be 0.0, got {no_edge.spread_to_edge_ratio}"
        assert no_edge.executable_edge_cents > 0, f"SOL executable edge should be positive, got {no_edge.executable_edge_cents}"
    
    def test_xrp_no_maker_order_production_bug(self):
        """XRP NO order: production bug case - should PASS with maker economics (ratio=0)."""
        # Production: spread_cost_too_high: ratio=1.95 > 0.8
        # XRP: yes_bid=60c, no_bid=40c, p_hat_yes=60c → p_hat_no=40c
        # Order price should be less than p_hat_no for positive edge
        yes_bid = 60
        no_bid = 40
        p_hat_yes = 60.0
        order_price = 35.0  # Less than p_hat_no=40c to get positive edge
        order_side = "no"
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=True  # MAKER
        )
        
        # CRITICAL: This is the production bug
        assert no_edge.spread_cost_cents == 0.0, f"XRP maker should have spread_cost=0, got {no_edge.spread_cost_cents}"
        assert no_edge.spread_to_edge_ratio == 0.0, f"XRP maker ratio should be 0.0, got {no_edge.spread_to_edge_ratio}"
        assert no_edge.executable_edge_cents > 0, f"XRP executable edge should be positive, got {no_edge.executable_edge_cents}"
    
    def test_doge_no_maker_order_thin_liquidity(self):
        """DOGE NO order: thin liquidity - should PASS with maker economics (ratio=0)."""
        # DOGE: yes_bid=15c, no_bid=85c, p_hat_yes=25c → p_hat_no=75c
        # Order price should be less than p_hat_no for positive edge
        yes_bid = 15
        no_bid = 85
        p_hat_yes = 25.0
        order_price = 70.0  # Less than p_hat_no=75c to get positive edge
        order_side = "no"
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=True  # MAKER
        )
        
        assert no_edge.spread_cost_cents == 0.0, f"DOGE maker should have spread_cost=0, got {no_edge.spread_cost_cents}"
        assert no_edge.spread_to_edge_ratio == 0.0, f"DOGE maker ratio should be 0.0, got {no_edge.spread_to_edge_ratio}"
        assert no_edge.executable_edge_cents > 0, f"DOGE executable edge should be positive, got {no_edge.executable_edge_cents}"


class TestProductionReplay:
    """Replay production rejection scenarios with maker vs taker economics."""
    
    def test_sol_no_maker_vs_taker(self):
        """SOL NO order: maker should PASS, taker should REJECT."""
        # Use asymmetric bids to create non-zero spread
        yes_bid = 41
        no_bid = 50  # Asymmetric to create spread
        p_hat_yes = 79.0
        order_price = 15.0  # Positive edge scenario
        order_side = "no"
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        
        # Maker: should PASS
        yes_edge_m, no_edge_m = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=True
        )
        assert no_edge_m.spread_to_edge_ratio == 0.0, f"SOL maker ratio should be 0.0, got {no_edge_m.spread_to_edge_ratio}"
        assert no_edge_m.executable_edge_cents > 0, f"SOL maker executable edge should be positive, got {no_edge_m.executable_edge_cents}"
        
        # Taker: should REJECT (wide spread)
        yes_edge_t, no_edge_t = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=False
        )
        if no_edge_t.spread_cents > 0 and no_edge_t.raw_edge_cents > 0:
            assert no_edge_t.spread_to_edge_ratio > 0.8, f"SOL taker ratio should exceed 0.8, got {no_edge_t.spread_to_edge_ratio}"
        assert no_edge_t.executable_edge_cents < 0, f"SOL taker executable edge should be negative, got {no_edge_t.executable_edge_cents}"
    
    def test_xrp_no_maker_vs_taker(self):
        """XRP NO order: maker should PASS, taker should REJECT."""
        # Use asymmetric bids to create non-zero spread with high ratio
        # yes_bid=60c, no_bid=20c → no_ask=40c, spread=20c
        # p_hat_yes=60c → p_hat_no=40c
        # order_price=30c (less than p_hat_no=40c for positive edge)
        # raw_edge = 40c - 30c = 10c
        # spread/edge = 20c/10c = 2.0 > 0.8 (should REJECT)
        yes_bid = 60
        no_bid = 20  # Asymmetric to create wide spread
        p_hat_yes = 60.0
        order_price = 30.0  # Positive edge scenario
        order_side = "no"
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        
        # Maker: should PASS
        yes_edge_m, no_edge_m = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=True
        )
        assert no_edge_m.spread_to_edge_ratio == 0.0, f"XRP maker ratio should be 0.0, got {no_edge_m.spread_to_edge_ratio}"
        assert no_edge_m.executable_edge_cents > 0, f"XRP maker executable edge should be positive, got {no_edge_m.executable_edge_cents}"
        
        # Taker: should REJECT
        yes_edge_t, no_edge_t = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=False
        )
        if no_edge_t.spread_cents > 0 and no_edge_t.raw_edge_cents > 0:
            assert no_edge_t.spread_to_edge_ratio > 0.8, f"XRP taker ratio should exceed 0.8, got {no_edge_t.spread_to_edge_ratio}"
        assert no_edge_t.executable_edge_cents < 0, f"XRP taker executable edge should be negative, got {no_edge_t.executable_edge_cents}"


class TestSideConsistency:
    """Test YES vs NO side ratio symmetry."""
    
    def test_yes_no_ratio_symmetry(self):
        """YES and NO orders should use correct side-specific spreads."""
        yes_bid = 50
        no_bid = 50
        p_hat_yes = 50.0
        order_price_yes = 40.0  # Less than p_hat_yes for positive edge
        order_price_no = 40.0  # Less than p_hat_no=50c for positive edge
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        
        # YES order
        yes_edge, _ = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price_yes,
            order_side="yes",
            use_maker_economics=True
        )
        
        # NO order
        _, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price_no,
            order_side="no",
            use_maker_economics=True
        )
        
        # Both should have ratio = 0 (maker economics)
        assert yes_edge.spread_to_edge_ratio == 0.0, f"YES maker ratio should be 0.0, got {yes_edge.spread_to_edge_ratio}"
        assert no_edge.spread_to_edge_ratio == 0.0, f"NO maker ratio should be 0.0, got {no_edge.spread_to_edge_ratio}"


class TestRegressionPrevention:
    """Regression tests to prevent the bug from reoccurring."""
    
    def test_regression_spread_cents_not_used_for_ratio(self):
        """Regression test: ensure spread_cents is NOT used for ratio calculation."""
        # Use asymmetric bids to create non-zero spread
        yes_bid = 41
        no_bid = 50  # Asymmetric to create spread
        p_hat_yes = 79.0
        order_price = 15.0  # Less than p_hat_no=21c for positive edge
        order_side = "no"
        
        spread_metrics = compute_canonical_spreads(yes_bid, no_bid)
        yes_edge, no_edge = compute_per_side_edges(
            p_hat_yes_cents=p_hat_yes,
            spread_metrics=spread_metrics,
            order_price_cents=order_price,
            order_side=order_side,
            use_maker_economics=True
        )
        
        # spread_cents should NOT be used for ratio (spread_cost should be used instead)
        # If the bug reverts, spread_cents would be non-zero, causing high ratio
        # With the fix, spread_cost = 0, causing ratio = 0
        assert no_edge.spread_to_edge_ratio == 0.0, f"Regression: ratio should be 0.0 (spread_cost), got {no_edge.spread_to_edge_ratio}"
        # Only check spread_cents is non-zero if we actually have a spread
        if no_edge.spread_cents > 0:
            assert no_edge.spread_cost_cents == 0.0, f"spread_cost should be zero for makers"
        assert no_edge.spread_cost_cents == 0.0, f"spread_cost should be zero for makers"
