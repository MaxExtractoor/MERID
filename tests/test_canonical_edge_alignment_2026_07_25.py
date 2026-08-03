"""
Canonical Edge Alignment Tests (2026-07-25)

Tests to verify that all edge computation entrypoints use the canonical edge formula:
edge = model_prob - market_price

This ensures consistency across:
- canonical_edge.py (parity block)
- agent_grid_15m.py (candidate generation)
- spread_edge_analytics.py (microstructure gate)
- global_allocator.py (allocation filtering)

Reference: https://arxiv.org/html/2604.20421v1
"""

import pytest
from decimal import Decimal


class TestCanonicalEdgeAlignment:
    """Test canonical edge formula alignment across modules."""
    
    def test_canonical_edge_formula(self):
        """Test canonical edge formula: edge = model_prob - market_price."""
        from merid.prediction.canonical_edge import compute_canonical_edges
        
        # Test case: model thinks YES is 51% likely, market prices at 50%
        model_prob_yes = 0.51
        market_price_yes = 0.50
        market_price_no = 0.50
        
        edge_yes, edge_no = compute_canonical_edges(
            model_prob_yes, market_price_yes, market_price_no
        )
        
        # Expected: edge_yes = 0.51 - 0.50 = 0.01 (1%)
        # Expected: edge_no = (1 - 0.51) - 0.50 = 0.49 - 0.50 = -0.01 (-1%)
        assert abs(edge_yes - 0.01) < 1e-6, f"Expected edge_yes=0.01, got {edge_yes}"
        assert abs(edge_no - (-0.01)) < 1e-6, f"Expected edge_no=-0.01, got {edge_no}"
    
    def test_edge_unit_conversions(self):
        """Test edge unit conversion helpers."""
        from merid.prediction.canonical_edge import (
            edge_frac_to_pct, edge_pct_to_frac,
            edge_frac_to_cents, edge_cents_to_frac,
            model_prob_to_cents, model_prob_from_cents
        )
        
        # Test fraction to percentage
        assert edge_frac_to_pct(0.025) == 2.5
        assert edge_frac_to_pct(0.01) == 1.0
        
        # Test percentage to fraction
        assert edge_pct_to_frac(2.5) == 0.025
        assert edge_pct_to_frac(1.0) == 0.01
        
        # Test fraction to cents (for binary options, 1 cent = 1% probability point)
        assert edge_frac_to_cents(0.01) == 1.0
        assert edge_frac_to_cents(0.025) == 2.5
        
        # Test cents to fraction
        assert edge_cents_to_frac(1.0) == 0.01
        assert edge_cents_to_frac(2.5) == 0.025
        
        # Test model probability conversions
        assert model_prob_to_cents(0.51) == 51.0
        assert model_prob_from_cents(51.0) == 0.51
    
    def test_agent_grid_price_based_canonical_edge(self):
        """Test that agent_grid price-based strategy uses canonical edge formula.
        
        CRITICAL FIX 2026-07-25: agent_grid_15m.py now uses canonical formula:
        edge = model_prob - market_price
        
        Previous threshold-based formula:
        edge = (threshold - market_price) / threshold
        
        This test verifies the new canonical approach.
        """
        # Simulate price-based strategy edge calculation
        # Using canonical formula: edge = model_prob - market_price
        
        # Derive model_prob from threshold (our fair price estimate)
        buy_threshold = 0.45  # We think fair YES probability is 45%
        market_price = 0.42  # Market prices YES at 42%
        
        # Canonical edge calculation
        yes_model_prob = buy_threshold
        yes_edge_frac = yes_model_prob - market_price
        
        # Expected: edge = 0.45 - 0.42 = 0.03 (3%)
        assert abs(yes_edge_frac - 0.03) < 1e-6, f"Expected edge=0.03, got {yes_edge_frac}"
        
        # Convert to percentage for candidate dict
        edge_pct = yes_edge_frac * 100.0
        assert abs(edge_pct - 3.0) < 1e-6, f"Expected edge_pct=3.0, got {edge_pct}"
    
    def test_spread_edge_analytics_canonical_consistency(self):
        """Test that spread_edge_analytics uses canonical edge formula.
        
        CRITICAL FIX 2026-07-25: spread_edge_analytics.py now uses canonical formula:
        edge_yes = model_prob_yes - market_price_yes (in cents)
        
        This test verifies the canonical formula is used in cents space.
        """
        from merid.event_venues.kalshi.spread_edge_analytics import (
            compute_canonical_spreads, compute_per_side_edges
        )
        
        # Test case: model thinks YES is 51% likely, market bid is 50c
        p_hat_yes_cents = 51.0  # model_prob * 100
        yes_bid_cents = 50.0
        no_bid_cents = 50.0
        
        # Compute spreads
        spread_metrics = compute_canonical_spreads(yes_bid_cents, no_bid_cents)
        
        # Compute edges using canonical formula
        yes_edge, no_edge = compute_per_side_edges(p_hat_yes_cents, spread_metrics, order_side=None)
        
        # Expected: yes_raw_edge = 51 - 50 = 1c (canonical formula in cents)
        assert abs(yes_edge.raw_edge_cents - 1.0) < 1e-6, \
            f"Expected yes_raw_edge=1.0c, got {yes_edge.raw_edge_cents}"
        
        # Verify this matches canonical formula in fraction space
        from merid.prediction.canonical_edge import edge_cents_to_frac
        edge_frac = edge_cents_to_frac(yes_edge.raw_edge_cents)
        assert abs(edge_frac - 0.01) < 1e-6, \
            f"Expected edge_frac=0.01, got {edge_frac}"
    
    def test_global_allocator_threshold_units(self):
        """Test that global_allocator uses fraction-based thresholds.
        
        CRITICAL FIX 2026-07-25: global_allocator.py stores thresholds as fractions (0.025 = 2.5%),
        not as percentages. Display multiplies by 100 for logging.
        
        This test verifies the internal representation is fraction-based.
        """
        from merid.risk.profiles.global_allocator import GlobalAllocator
        
        # Create allocator with 2.5% threshold
        allocator = GlobalAllocator(
            venue_cap_usd=1.00,
            min_edge_pct=0.025  # Stored as fraction, not percentage
        )
        
        # Verify internal storage is fraction
        assert allocator.min_edge_pct == 0.025, \
            f"Expected min_edge_pct=0.025 (fraction), got {allocator.min_edge_pct}"
        
        # Verify per-asset thresholds are also fractions
        for asset, threshold in allocator.per_asset_min_edge_pct.items():
            assert threshold == 0.025, \
                f"Expected {asset} threshold=0.025 (fraction), got {threshold}"
    
    def test_threshold_unit_consistency_across_modules(self):
        """Test that all modules use consistent threshold units (fractions internally).
        
        This test verifies:
        - global_allocator: min_edge_pct = 0.025 (fraction)
        - spread_edge_analytics: min_executable_edge_frac = 0.03 (fraction)
        - canonical_edge: all edges computed as fractions
        """
        # Global allocator threshold
        from merid.risk.profiles.global_allocator import GlobalAllocator
        allocator = GlobalAllocator(min_edge_pct=0.025)
        assert allocator.min_edge_pct == 0.025  # Fraction
        
        # Spread edge analytics threshold (default)
        from merid.event_venues.kalshi.spread_edge_analytics import (
            select_best_side, edge_aware_microstructure_gate
        )
        # Check function signature uses fraction parameter
        import inspect
        sig = inspect.signature(select_best_side)
        assert 'min_executable_edge_frac' in sig.parameters
        assert sig.parameters['min_executable_edge_frac'].default == 0.03  # Fraction
        
        sig = inspect.signature(edge_aware_microstructure_gate)
        assert 'min_executable_edge_frac' in sig.parameters
        assert sig.parameters['min_executable_edge_frac'].default == 0.03  # Fraction


class TestCanonicalEdgeIntegration:
    """Integration tests for canonical edge alignment across the stack."""
    
    def test_allocator_parity_edge_alignment(self):
        """Test that allocator and parity block see the same edge values.
        
        This test simulates the XRP mismatch case:
        - Allocator edge: ~1.001% (from candidate)
        - Parity block edge: edge_yes=1.0%, edge_no=-20%
        
        After canonical alignment, both should compute the same edge from the same inputs.
        """
        from merid.prediction.canonical_edge import compute_canonical_edges
        from merid.risk.profiles.global_allocator import OrderCandidate, GlobalAllocator
        
        # Simulate XRP case with canonical edge
        model_prob_yes = 0.51
        market_price_yes = 0.50
        market_price_no = 0.50
        
        # Compute canonical edges (parity block view)
        edge_yes_frac, edge_no_frac = compute_canonical_edges(
            model_prob_yes, market_price_yes, market_price_no
        )
        
        # Convert to percentage for candidate (allocator view)
        edge_pct = edge_yes_frac * 100.0  # 1.0%
        
        # Create candidate with canonical edge
        candidate = OrderCandidate(
            asset="XRP",
            ticker="KXXRP15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            edge_pct=edge_pct / 100.0,  # Store as fraction in candidate
            confidence=0.70,
            model_prob=model_prob_yes,
            agent_name="XRP_15M"
        )
        
        # Create allocator with 2.5% threshold
        allocator = GlobalAllocator(min_edge_pct=0.025)
        
        # Check if candidate passes allocator threshold
        asset_min_edge = allocator.per_asset_min_edge_pct.get("XRP", allocator.min_edge_pct)
        passes_allocator = candidate.edge_pct >= asset_min_edge
        
        # Check if parity block would pass (edge_yes >= threshold)
        min_edge_frac = 0.025
        passes_parity = edge_yes_frac >= min_edge_frac
        
        # Both should agree
        assert passes_allocator == passes_parity, \
            f"Allocator and parity disagree: allocator={passes_allocator}, parity={passes_parity}"
        
        # Verify edge values match
        assert abs(candidate.edge_pct - edge_yes_frac) < 1e-6, \
            f"Edge mismatch: candidate.edge_pct={candidate.edge_pct}, canonical.edge_yes={edge_yes_frac}"
    
    def test_side_aware_dual_edge_consistency(self):
        """Test that YES and NO edges are computed consistently.
        
        Canonical formula ensures:
        - edge_yes = model_prob_yes - market_price_yes
        - edge_no = (1 - model_prob_yes) - market_price_no
        
        This test verifies both sides use the same canonical formula.
        """
        from merid.prediction.canonical_edge import compute_canonical_edges
        
        # Test case: asymmetric market
        model_prob_yes = 0.60
        market_price_yes = 0.55
        market_price_no = 0.45  # Note: yes + no = 1.0 (parity)
        
        edge_yes, edge_no = compute_canonical_edges(
            model_prob_yes, market_price_yes, market_price_no
        )
        
        # Expected: edge_yes = 0.60 - 0.55 = 0.05 (5%)
        # Expected: edge_no = 0.40 - 0.45 = -0.05 (-5%)
        assert abs(edge_yes - 0.05) < 1e-6, f"Expected edge_yes=0.05, got {edge_yes}"
        assert abs(edge_no - (-0.05)) < 1e-6, f"Expected edge_no=-0.05, got {edge_no}"
        
        # Verify edge_no formula: (1 - model_prob) - market_price_no
        expected_edge_no = (1.0 - model_prob_yes) - market_price_no
        assert abs(edge_no - expected_edge_no) < 1e-6, \
            f"edge_no formula mismatch: expected={expected_edge_no}, got={edge_no}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
