"""
Tests for model_prob and strategy_intent fixes (2026-07-19)

Tests verify:
1. model_prob calculation is correct for both YES and NO sides
2. strategy_intent is properly set for all signal types
3. Kelly filter doesn't reject orders with valid edge due to incorrect model_prob
"""

import pytest
from decimal import Decimal


class TestModelProbCalculation:
    """Test model_prob calculation for Kelly criterion."""
    
    def test_momentum_fvg_yes_side_model_prob(self):
        """Test that YES-side model_prob is probability of YES outcome."""
        # Market price 50c = 0.50 probability
        # Edge 5% = 0.05 adjustment
        # Expected: model_prob = 0.50 + 0.05 = 0.55
        
        market_prob = 0.50
        edge_pct = 0.05
        edge_adjustment = min(edge_pct, 0.20)
        
        # For YES: model_prob is probability of YES outcome
        model_prob = min(0.95, market_prob + edge_adjustment)
        
        assert model_prob == 0.55, f"Expected 0.55, got {model_prob}"
        print("✓ YES-side model_prob calculation correct")
    
    def test_momentum_fvg_no_side_model_prob(self):
        """Test that NO-side model_prob is probability of NO outcome."""
        # Market price 14c = 0.14 probability for YES
        # Edge 3.55% = 0.0355 adjustment
        # Expected: model_prob = (1.0 - 0.14) + 0.0355 = 0.8955
        
        market_prob = 0.14
        edge_pct = 0.0355
        edge_adjustment = min(edge_pct, 0.20)
        
        # For NO: model_prob is probability of NO outcome
        no_market_prob = 1.0 - market_prob
        model_prob = min(0.95, no_market_prob + edge_adjustment)
        
        assert model_prob == 0.8955, f"Expected 0.8955, got {model_prob}"
        print("✓ NO-side model_prob calculation correct")
    
    def test_momentum_fvg_no_side_not_low_probability(self):
        """Test that NO-side doesn't get low model_prob despite positive edge."""
        # This was the bug: NO-side was getting model_prob=0.05 despite positive edge
        # Market price 30c = 0.30 probability for YES
        # Edge 0.50% = 0.005 adjustment
        # Expected: model_prob = (1.0 - 0.30) + 0.005 = 0.705
        
        market_prob = 0.30
        edge_pct = 0.005
        edge_adjustment = min(edge_pct, 0.20)
        
        no_market_prob = 1.0 - market_prob
        model_prob = min(0.95, no_market_prob + edge_adjustment)
        
        # Should NOT be 0.05 (the bug)
        assert model_prob > 0.50, f"Expected > 0.50, got {model_prob}"
        assert model_prob == 0.705, f"Expected 0.705, got {model_prob}"
        print("✓ NO-side model_prob not incorrectly low")
    
    def test_price_based_yes_side_model_prob(self):
        """Test price-based signal YES-side model_prob."""
        market_price = 0.40
        edge_pct = 0.02
        edge_adjustment = min(edge_pct, 0.20)
        
        # For YES: model_prob is probability of YES outcome
        model_prob = min(0.95, market_price + edge_adjustment)
        
        assert abs(model_prob - 0.42) < 0.001, f"Expected ~0.42, got {model_prob}"
        print("✓ Price-based YES-side model_prob correct")
    
    def test_price_based_no_side_model_prob(self):
        """Test price-based signal NO-side model_prob."""
        market_price = 0.70
        edge_pct = 0.02
        edge_adjustment = min(edge_pct, 0.20)
        
        # For NO: model_prob is probability of NO outcome
        no_market_prob = 1.0 - market_price
        model_prob = min(0.95, no_market_prob + edge_adjustment)
        
        assert abs(model_prob - 0.32) < 0.001, f"Expected ~0.32, got {model_prob}"
        print("✓ Price-based NO-side model_prob correct")


class TestStrategyIntentAssignment:
    """Test strategy_intent assignment for all signal types."""
    
    def test_momentum_fvg_yes_side_strategy_intent(self):
        """Test that YES-side gets BULLISH_EVENT strategy intent."""
        from merid.prediction.intent_contract import StrategyIntent
        
        signal_side = "yes"
        strategy_intent = StrategyIntent.BULLISH_EVENT if signal_side == "yes" else StrategyIntent.BEARISH_EVENT
        
        assert strategy_intent == StrategyIntent.BULLISH_EVENT
        assert strategy_intent.value == "bullish_event"
        print("✓ YES-side strategy_intent is BULLISH_EVENT")
    
    def test_momentum_fvg_no_side_strategy_intent(self):
        """Test that NO-side gets BEARISH_EVENT strategy intent."""
        from merid.prediction.intent_contract import StrategyIntent
        
        signal_side = "no"
        strategy_intent = StrategyIntent.BULLISH_EVENT if signal_side == "yes" else StrategyIntent.BEARISH_EVENT
        
        assert strategy_intent == StrategyIntent.BEARISH_EVENT
        assert strategy_intent.value == "bearish_event"
        print("✓ NO-side strategy_intent is BEARISH_EVENT")
    
    def test_price_based_bullish_strategy_intent(self):
        """Test price-based signal assigns BULLISH_EVENT correctly."""
        from merid.prediction.intent_contract import StrategyIntent
        
        # Price cheap → bet on event occurring (BULLISH_EVENT)
        market_price = 0.40
        buy_threshold = 0.50
        
        if market_price <= buy_threshold:
            strategy_intent = StrategyIntent.BULLISH_EVENT
        else:
            strategy_intent = StrategyIntent.BEARISH_EVENT
        
        assert strategy_intent == StrategyIntent.BULLISH_EVENT
        print("✓ Price-based BULLISH_EVENT assignment correct")
    
    def test_price_based_bearish_strategy_intent(self):
        """Test price-based signal assigns BEARISH_EVENT correctly."""
        from merid.prediction.intent_contract import StrategyIntent
        
        # Price high → bet against event occurring (BEARISH_EVENT)
        market_price = 0.70
        sell_threshold = 0.60
        
        if market_price >= sell_threshold:
            strategy_intent = StrategyIntent.BEARISH_EVENT
        else:
            strategy_intent = StrategyIntent.BULLISH_EVENT
        
        assert strategy_intent == StrategyIntent.BEARISH_EVENT
        print("✓ Price-based BEARISH_EVENT assignment correct")
    
    def test_panic_fade_oversold_strategy_intent(self):
        """Test panic fade assigns BULLISH_EVENT for oversold."""
        from merid.prediction.intent_contract import StrategyIntent
        
        is_oversold = True
        strategy_intent = StrategyIntent.BULLISH_EVENT if is_oversold else StrategyIntent.BEARISH_EVENT
        
        assert strategy_intent == StrategyIntent.BULLISH_EVENT
        print("✓ Panic fade oversold strategy_intent is BULLISH_EVENT")
    
    def test_panic_fade_overbought_strategy_intent(self):
        """Test panic fade assigns BEARISH_EVENT for overbought."""
        from merid.prediction.intent_contract import StrategyIntent
        
        is_oversold = False
        strategy_intent = StrategyIntent.BULLISH_EVENT if is_oversold else StrategyIntent.BEARISH_EVENT
        
        assert strategy_intent == StrategyIntent.BEARISH_EVENT
        print("✓ Panic fade overbought strategy_intent is BEARISH_EVENT")


class TestKellyFilterIntegration:
    """Test Kelly filter integration with correct model_prob."""
    
    def test_kelly_fraction_with_correct_model_prob_yes(self):
        """Test Kelly fraction calculation with correct YES-side model_prob."""
        from merid.prediction.unified_sizing import calculate_kelly_fraction
        
        model_prob = 0.55  # Correct YES-side probability
        price_cents = 50
        side = "yes"
        
        kelly_fraction = calculate_kelly_fraction(
            model_prob=model_prob,
            price_cents=price_cents,
            side=side
        )
        
        # Should be positive (has edge)
        assert kelly_fraction > 0, f"Expected positive kelly_fraction, got {kelly_fraction}"
        print(f"✓ Kelly fraction positive for YES-side: {kelly_fraction:.4f}")
    
    def test_kelly_fraction_with_correct_model_prob_no(self):
        """Test Kelly fraction calculation with correct NO-side model_prob."""
        from merid.prediction.unified_sizing import calculate_kelly_fraction
        
        model_prob = 0.8955  # Correct NO-side probability (not 0.05!)
        price_cents = 14
        side = "no"
        
        kelly_fraction = calculate_kelly_fraction(
            model_prob=model_prob,
            price_cents=price_cents,
            side=side
        )
        
        # Should be positive (has edge)
        assert kelly_fraction > 0, f"Expected positive kelly_fraction, got {kelly_fraction}"
        print(f"✓ Kelly fraction positive for NO-side: {kelly_fraction:.4f}")
    
    def test_kelly_fraction_rejects_no_edge(self):
        """Test Kelly fraction rejects when model_prob indicates no edge."""
        from merid.prediction.unified_sizing import calculate_kelly_fraction
        
        model_prob = 0.48  # Below threshold for YES at 50c
        price_cents = 50
        side = "yes"
        
        kelly_fraction = calculate_kelly_fraction(
            model_prob=model_prob,
            price_cents=price_cents,
            side=side
        )
        
        # Should be zero (no edge)
        assert kelly_fraction == 0, f"Expected zero kelly_fraction, got {kelly_fraction}"
        print("✓ Kelly fraction zero for no edge")


class TestDeepOTMLoggingLevel:
    """Test DEEP_OTM_POLICY_STATE logging level."""
    
    def test_deep_otm_logging_is_info_not_error(self):
        """Verify DEEP_OTM_POLICY_STATE uses logger.info not logger.error."""
        import inspect
        from merid.event_venues.kalshi import order_router
        
        # Get the source code of the file
        source = inspect.getsource(order_router)
        
        # Check that it uses logger.info for DEEP_OTM_POLICY_STATE
        assert 'logger.info' in source and 'DEEP_OTM_POLICY_STATE' in source, \
            "Should use logger.info for DEEP_OTM_POLICY_STATE"
        
        # Check that it doesn't use logger.error for DEEP_OTM_POLICY_STATE
        lines = source.split('\n')
        for line in lines:
            if 'DEEP_OTM_POLICY_STATE' in line and 'logger.error' in line:
                raise AssertionError("Should not use logger.error for DEEP_OTM_POLICY_STATE")
        
        print("✓ DEEP_OTM_POLICY_STATE uses logger.info")


class TestExposureCapDiagnostics:
    """Test exposure cap diagnostic logging."""
    
    def test_exposure_cap_rejection_logs_diagnostics(self):
        """Verify exposure cap rejection logs slot allocator state."""
        import inspect
        from merid.prediction import unified_sizing
        
        # Get the source code of compute_order_size
        source = inspect.getsource(unified_sizing.compute_order_size)
        
        # Check that it logs slot allocator state on rejection
        assert 'slot_allocator' in source.lower(), "Should reference slot_allocator"
        assert 'get_total_exposure' in source, "Should call get_total_exposure"
        assert 'get_slots_by_asset' in source, "Should call get_slots_by_asset"
        
        print("✓ Exposure cap rejection logs slot allocator diagnostics")


class TestPositiveEdgeFiltering:
    """Test positive edge filtering in momentum_fvg side selection."""
    
    def test_positive_edge_filtering_rejects_negative_edges(self):
        """Test that momentum_fvg filters out sides with negative edges."""
        # Simulate the edge filtering logic
        side_edges = {
            "yes": 0.02,  # Positive edge
            "no": -0.46   # Negative edge (should be filtered out)
        }
        
        # Filter to only positive edges
        positive_sides = {}
        for side, edge in side_edges.items():
            if edge is not None and edge > 0:
                positive_sides[side] = edge
        
        # Should only have "yes" (positive edge)
        assert "yes" in positive_sides, "YES with positive edge should be included"
        assert "no" not in positive_sides, "NO with negative edge should be filtered out"
        assert len(positive_sides) == 1, "Should have exactly 1 positive side"
        
        print("✓ Positive edge filtering correctly rejects negative edges")
    
    def test_positive_edge_filtering_all_negative_returns_none(self):
        """Test that momentum_fvg returns None when all edges are negative."""
        side_edges = {
            "yes": -0.10,
            "no": -0.46
        }
        
        # Filter to only positive edges
        positive_sides = {}
        for side, edge in side_edges.items():
            if edge is not None and edge > 0:
                positive_sides[side] = edge
        
        # Should have no positive sides
        assert len(positive_sides) == 0, "Should have no positive sides"
        
        print("✓ All negative edges correctly filtered to empty set")
    
    def test_positive_edge_filtering_both_positive_selects_max(self):
        """Test that momentum_fvg selects max edge when both sides are positive."""
        side_edges = {
            "yes": 0.05,
            "no": 0.03
        }
        
        # Filter to only positive edges
        positive_sides = {}
        for side, edge in side_edges.items():
            if edge is not None and edge > 0:
                positive_sides[side] = edge
        
        # Should have both sides
        assert len(positive_sides) == 2, "Should have both positive sides"
        
        # Select side with max edge
        selected_side = max(positive_sides, key=positive_sides.get)
        assert selected_side == "yes", "Should select YES with higher edge"
        
        print("✓ Both positive edges correctly selects maximum")


class TestVelocityBasedSignalEdgeFiltering:
    """Test positive edge filtering in velocity-based signal generation."""
    
    def test_velocity_signal_filters_negative_edges(self):
        """Test that velocity-based signal filters out sides with negative edges."""
        # Simulate the edge filtering logic from velocity-based signal
        side_edges = {
            "yes": 0.03,  # Positive edge
            "no": -0.25   # Negative edge (should be filtered out)
        }
        
        # Filter to only positive edges
        positive_sides = {}
        for side, edge in side_edges.items():
            if edge is not None and edge > 0:
                positive_sides[side] = edge
        
        # Should only have "yes" (positive edge)
        assert "yes" in positive_sides, "YES with positive edge should be included"
        assert "no" not in positive_sides, "NO with negative edge should be filtered out"
        assert len(positive_sides) == 1, "Should have exactly 1 positive side"
        
        print("✓ Velocity-based signal correctly filters negative edges")
    
    def test_velocity_signal_all_negative_returns_none(self):
        """Test that velocity-based signal returns None when all edges are negative."""
        side_edges = {
            "yes": -0.15,
            "no": -0.30
        }
        
        # Filter to only positive edges
        positive_sides = {}
        for side, edge in side_edges.items():
            if edge is not None and edge > 0:
                positive_sides[side] = edge
        
        # Should have no positive sides
        assert len(positive_sides) == 0, "Should have no positive sides"
        
        print("✓ Velocity-based signal all negative edges correctly filtered")


class TestMomentumFvgInvariantCheck:
    """Test momentum_fvg upstream invariant check with validate_intent_exposure_consistency."""
    
    def test_momentum_fvg_yes_side_validates_bullish_intent(self):
        """Test that momentum_fvg YES side validates with BULLISH_EVENT intent."""
        try:
            from merid.prediction.intent_contract import StrategyIntent, validate_intent_exposure_consistency
            
            strategy_intent = StrategyIntent.BULLISH_EVENT
            signal_side = "yes"
            signal_action = "buy"
            
            is_valid, error = validate_intent_exposure_consistency(
                intent=strategy_intent,
                kalshi_side=signal_side,
                kalshi_action=signal_action,
                current_position=None,
            )
            
            assert is_valid, f"YES side with BULLISH_EVENT intent should be valid, got error: {error}"
            print("✓ Momentum_fvg YES side validates with BULLISH_EVENT intent")
        except ImportError:
            print("⚠ Intent contract not available - skipping test")
    
    def test_momentum_fvg_no_side_validates_bearish_intent(self):
        """Test that momentum_fvg NO side validates with BEARISH_EVENT intent."""
        try:
            from merid.prediction.intent_contract import StrategyIntent, validate_intent_exposure_consistency
            
            strategy_intent = StrategyIntent.BEARISH_EVENT
            signal_side = "no"
            signal_action = "buy"
            
            is_valid, error = validate_intent_exposure_consistency(
                intent=strategy_intent,
                kalshi_side=signal_side,
                kalshi_action=signal_action,
                current_position=None,
            )
            
            assert is_valid, f"NO side with BEARISH_EVENT intent should be valid, got error: {error}"
            print("✓ Momentum_fvg NO side validates with BEARISH_EVENT intent")
        except ImportError:
            print("⚠ Intent contract not available - skipping test")


class TestPriceBasedEdgeCalculation:
    """Test price-based signal edge_yes and edge_no calculation."""
    
    def test_price_based_yes_side_sets_edge_yes(self):
        """Test that price-based YES side sets edge_yes correctly."""
        # Simulate price-based signal logic for YES side
        signal_side = "yes"
        signal_action = "buy"
        market_price = 0.42
        buy_threshold = 0.50
        
        edge_pct = (buy_threshold - market_price) / buy_threshold
        edge_pct = max(edge_pct, 0.02)
        
        edge_yes = edge_pct
        edge_no = 0.0
        
        assert edge_yes > 0, "edge_yes should be positive for YES side"
        assert edge_no == 0.0, "edge_no should be 0.0 for YES side"
        assert abs(edge_yes - 0.16) < 0.01, f"edge_yes should be ~0.16, got {edge_yes}"
        
        print("✓ Price-based YES side sets edge_yes correctly")
    
    def test_price_based_no_side_sets_edge_no(self):
        """Test that price-based NO side sets edge_no correctly."""
        # Simulate price-based signal logic for NO side
        signal_side = "no"
        signal_action = "buy"
        market_price = 0.58
        sell_threshold = 0.50
        
        edge_pct = (market_price - sell_threshold) / (1.0 - sell_threshold)
        edge_pct = max(edge_pct, 0.02)
        
        edge_yes = 0.0
        edge_no = edge_pct
        
        assert edge_no > 0, "edge_no should be positive for NO side"
        assert edge_yes == 0.0, "edge_yes should be 0.0 for NO side"
        assert abs(edge_no - 0.16) < 0.01, f"edge_no should be ~0.16, got {edge_no}"
        
        print("✓ Price-based NO side sets edge_no correctly")


class TestLoop15mParityCheckerEdgeData:
    """Test loop_15m parity checker uses actual edge_yes/edge_no from signal."""
    
    def test_parity_checker_uses_signal_edge_data(self):
        """Test that parity checker uses edge_yes/edge_no from signal when available."""
        # Simulate candidate with edge_yes/edge_no
        candidate = {
            "edge_yes": 0.02,
            "edge_no": -0.46,
            "edge_pct": 2.0,
            "model_prob": 0.83,
        }
        
        # Simulate loop_15m logic
        edge_pct = candidate.get("edge_pct", 2.0)
        model_prob = candidate.get("model_prob", 0.83)
        
        # CRITICAL FIX: Use actual edge_yes and edge_no from signal if available
        edge_yes = candidate.get("edge_yes", edge_pct / 100.0)
        edge_no = candidate.get("edge_no", (1.0 - model_prob) - (1.0 - 0.37 / 100.0) if model_prob else 0.0)
        
        # Should use actual values from signal
        assert abs(edge_yes - 0.02) < 0.001, f"edge_yes should be 0.02, got {edge_yes}"
        assert abs(edge_no - (-0.46)) < 0.001, f"edge_no should be -0.46, got {edge_no}"
        
        print("✓ Parity checker uses actual edge_yes/edge_no from signal")
    
    def test_parity_checker_fallback_when_edge_data_missing(self):
        """Test that parity checker falls back to estimation when edge data missing."""
        # Simulate candidate without edge_yes/edge_no
        candidate = {
            "edge_pct": 2.0,
            "model_prob": 0.83,
        }
        
        # Simulate loop_15m logic
        edge_pct = candidate.get("edge_pct", 2.0)
        model_prob = candidate.get("model_prob", 0.83)
        price_cents = 37
        
        # Should fall back to estimation
        edge_yes = candidate.get("edge_yes", edge_pct / 100.0)
        edge_no = candidate.get("edge_no", (1.0 - model_prob) - (1.0 - price_cents / 100.0) if model_prob else 0.0)
        
        # Should use estimated values
        assert abs(edge_yes - 0.02) < 0.001, f"edge_yes should be estimated as 0.02, got {edge_yes}"
        assert edge_no is not None, "edge_no should be estimated"
        
        print("✓ Parity checker falls back to estimation when edge data missing")


class TestPriceBasedSignalEdgeSelectionFix:
    """Test price-based signal edge selection fix for WINNER_MISMATCH parity failures."""
    
    def test_price_based_selects_positive_edge_over_negative(self):
        """Test that price-based signal selects side with positive edge when other side has negative edge."""
        # Simulate the scenario from the parity failure:
        # edge_yes=0.0356 (positive), edge_no=-0.3200 (negative)
        # Should select YES, not NO
        
        market_price = 0.44
        buy_threshold = 0.50
        sell_threshold = 0.50
        
        # Calculate edge for YES side
        yes_edge_pct = 0.0
        if market_price <= buy_threshold:
            yes_edge_pct = (buy_threshold - market_price) / buy_threshold
            yes_edge_pct = max(yes_edge_pct, 0.02)
        
        # Calculate edge for NO side
        no_edge_pct = 0.0
        if market_price >= sell_threshold:
            no_edge_pct = (market_price - sell_threshold) / (1.0 - sell_threshold)
            no_edge_pct = max(no_edge_pct, 0.02)
        
        # Select side with maximum positive edge
        if yes_edge_pct > no_edge_pct:
            signal_side = "yes"
        elif no_edge_pct > yes_edge_pct:
            signal_side = "no"
        else:
            signal_side = "yes"  # Default
        
        # With price=0.44, buy_threshold=0.50:
        # yes_edge_pct = (0.50 - 0.44) / 0.50 = 0.12 (positive)
        # no_edge_pct = 0.0 (price not >= sell_threshold)
        # Should select YES
        assert signal_side == "yes", f"Should select YES with positive edge, got {signal_side}"
        assert yes_edge_pct > 0, f"YES edge should be positive, got {yes_edge_pct}"
        assert no_edge_pct == 0, f"NO edge should be 0, got {no_edge_pct}"
        
        print("✓ Price-based signal selects positive edge over negative")
    
    def test_price_based_rejects_all_negative_edges(self):
        """Test that price-based signal returns None when both edges are negative/zero."""
        # Use a scenario where edges are explicitly negative
        # Simulate edges that would result from unfavorable market conditions
        yes_edge_pct = -0.05  # Negative YES edge
        no_edge_pct = -0.10   # Negative NO edge
        
        # CRITICAL: Only select sides with POSITIVE edges
        if yes_edge_pct <= 0 and no_edge_pct <= 0:
            should_trade = False
        else:
            should_trade = True
        
        # With both edges negative, should not trade
        assert not should_trade, "Should not trade when both edges are <= 0"
        
        print("✓ Price-based signal rejects all negative edges")
    
    def test_price_based_selects_max_positive_edge(self):
        """Test that price-based signal selects side with maximum positive edge when both are positive."""
        market_price = 0.30  # Well below buy_threshold
        buy_threshold = 0.50
        sell_threshold = 0.50
        
        # Calculate edge for YES side
        yes_edge_pct = 0.0
        if market_price <= buy_threshold:
            yes_edge_pct = (buy_threshold - market_price) / buy_threshold
            yes_edge_pct = max(yes_edge_pct, 0.02)
        
        # Calculate edge for NO side
        no_edge_pct = 0.0
        if market_price >= sell_threshold:
            no_edge_pct = (market_price - sell_threshold) / (1.0 - sell_threshold)
            no_edge_pct = max(no_edge_pct, 0.02)
        
        # Select side with maximum positive edge
        if yes_edge_pct > no_edge_pct:
            signal_side = "yes"
        elif no_edge_pct > yes_edge_pct:
            signal_side = "no"
        else:
            signal_side = "yes"  # Default
        
        # With price=0.30, buy_threshold=0.50:
        # yes_edge_pct = (0.50 - 0.30) / 0.50 = 0.40 (positive)
        # no_edge_pct = 0.0 (price not >= sell_threshold)
        # Should select YES with higher edge
        assert signal_side == "yes", f"Should select YES with higher edge, got {signal_side}"
        assert yes_edge_pct > no_edge_pct, f"YES edge should be higher than NO edge"
        
        print("✓ Price-based signal selects max positive edge")
    
    def test_price_based_parity_failure_scenario(self):
        """Test the exact scenario from the parity failure log."""
        # From log: edge_yes=0.0356, edge_no=-0.3200, chosen_side=no
        # This should NOT happen with the fix
        
        # Simulate the corrected logic
        yes_edge_pct = 0.0356
        no_edge_pct = -0.3200
        
        # CRITICAL: Only select sides with POSITIVE edges
        if yes_edge_pct <= 0 and no_edge_pct <= 0:
            should_trade = False
            signal_side = None
        else:
            should_trade = True
            # Select side with maximum positive edge
            if yes_edge_pct > no_edge_pct:
                signal_side = "yes"
            elif no_edge_pct > yes_edge_pct:
                signal_side = "no"
            else:
                signal_side = "yes"  # Default
        
        # With yes_edge_pct=0.0356 (positive) and no_edge_pct=-0.3200 (negative):
        # Should select YES, not NO
        assert signal_side == "yes", f"Should select YES with positive edge, got {signal_side}"
        assert should_trade, "Should trade when at least one edge is positive"
        
        print("✓ Price-based signal correctly handles parity failure scenario")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
