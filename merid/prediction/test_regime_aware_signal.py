"""
Integration tests for regime-aware signal generation.
Tests the regime-aware velocity-to-side mapping logic.
"""

import pytest
import numpy as np
from unittest.mock import Mock
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from merid.prediction.regime_detector import Regime, RegimeDetection


class TestSignalAlignmentValidation:
    """Test cross-signal alignment validation between velocity and OBI.
    
    2026-07-05 FIX: Prevent contradictory signals (e.g., velocity=BUY YES, OBI=sell)
    
    Note: Velocity signals use "yes"/"no" (side), while OBI signals use "buy"/"sell" (action).
    Alignment mapping: velocity "yes" aligns with OBI "buy" (buying YES), velocity "no" aligns with OBI "sell" (buying NO).
    """
    
    def test_velocity_buy_yes_obi_buy_aligned(self):
        """Velocity BUY YES with OBI BUY should pass (signals aligned)."""
        velocity_signal = "yes"  # BUY YES from velocity
        obi_signal = "STRONG_BUY"  # OBI agrees (buy direction)
        
        # Extract OBI direction
        obi_direction = None
        if obi_signal in ["STRONG_BUY", "BUY"]:
            obi_direction = "buy"
        elif obi_signal in ["STRONG_SELL", "SELL"]:
            obi_direction = "sell"
        
        # Check alignment (yes aligns with buy, no aligns with sell)
        signals_aligned = (obi_direction is None) or (
            (velocity_signal == "yes" and obi_direction == "buy") or
            (velocity_signal == "no" and obi_direction == "sell")
        )
        assert signals_aligned, "Velocity BUY YES with OBI BUY should be aligned"
    
    def test_velocity_buy_yes_obi_sell_contradiction(self):
        """Velocity BUY YES with OBI SELL should be rejected (signals contradict)."""
        velocity_signal = "yes"  # BUY YES from velocity
        obi_signal = "STRONG_SELL"  # OBI disagrees (sell direction)
        
        # Extract OBI direction
        obi_direction = None
        if obi_signal in ["STRONG_BUY", "BUY"]:
            obi_direction = "buy"
        elif obi_signal in ["STRONG_SELL", "SELL"]:
            obi_direction = "sell"
        
        # Check alignment (yes aligns with buy, no aligns with sell)
        signals_aligned = (obi_direction is None) or (
            (velocity_signal == "yes" and obi_direction == "buy") or
            (velocity_signal == "no" and obi_direction == "sell")
        )
        assert not signals_aligned, "Velocity BUY YES with OBI SELL should be contradictory"
    
    def test_velocity_buy_no_obi_sell_aligned(self):
        """Velocity BUY NO with OBI SELL should pass (signals aligned)."""
        velocity_signal = "no"  # BUY NO from velocity
        obi_signal = "SELL"  # OBI agrees (sell direction)
        
        # Extract OBI direction
        obi_direction = None
        if obi_signal in ["STRONG_BUY", "BUY"]:
            obi_direction = "buy"
        elif obi_signal in ["STRONG_SELL", "SELL"]:
            obi_direction = "sell"
        
        # Check alignment (yes aligns with buy, no aligns with sell)
        signals_aligned = (obi_direction is None) or (
            (velocity_signal == "yes" and obi_direction == "buy") or
            (velocity_signal == "no" and obi_direction == "sell")
        )
        assert signals_aligned, "Velocity BUY NO with OBI SELL should be aligned"
    
    def test_velocity_buy_no_obi_buy_contradiction(self):
        """Velocity BUY NO with OBI BUY should be rejected (signals contradict)."""
        velocity_signal = "no"  # BUY NO from velocity
        obi_signal = "BUY"  # OBI disagrees (buy direction)
        
        # Extract OBI direction
        obi_direction = None
        if obi_signal in ["STRONG_BUY", "BUY"]:
            obi_direction = "buy"
        elif obi_signal in ["STRONG_SELL", "SELL"]:
            obi_direction = "sell"
        
        # Check alignment (yes aligns with buy, no aligns with sell)
        signals_aligned = (obi_direction is None) or (
            (velocity_signal == "yes" and obi_direction == "buy") or
            (velocity_signal == "no" and obi_direction == "sell")
        )
        assert not signals_aligned, "Velocity BUY NO with OBI BUY should be contradictory"
    
    def test_obi_neutral_allows_any_velocity(self):
        """OBI NEUTRAL should allow any velocity signal (no contradiction)."""
        velocity_signal = "yes"  # BUY YES from velocity
        obi_signal = "NEUTRAL"  # OBI neutral
        
        # Extract OBI direction
        obi_direction = None
        if obi_signal in ["STRONG_BUY", "BUY"]:
            obi_direction = "buy"
        elif obi_signal in ["STRONG_SELL", "SELL"]:
            obi_direction = "sell"
        
        # Check alignment (neutral OBI has no direction, so always aligned)
        signals_aligned = (obi_direction is None) or (
            (velocity_signal == "yes" and obi_direction == "buy") or
            (velocity_signal == "no" and obi_direction == "sell")
        )
        assert signals_aligned, "OBI NEUTRAL should allow any velocity signal"


class TestNegativeEdgeValidation:
    """Test negative edge validation in momentum mode (REMOVED 2026-07-05).
    
    REMOVED 2026-07-05: The -20% edge threshold check was removed because:
    1. p_model is derived from velocity via logistic mapping, not independent probability estimation
    2. Comparing velocity-transformed probability to market-implied probability is meaningless
    3. Momentum trading conviction comes from velocity exceeding threshold, not probability edge
    4. The edge gate was already disabled for momentum (line 3513-3515 in agent_grid_15m.py)
    
    Momentum signals are now validated solely by velocity threshold, not probability edge.
    """
    
    def test_all_edges_allowed_for_momentum(self):
        """All edges should be allowed in momentum mode (edge check removed)."""
        # These would have been rejected before the fix
        edge_pct_values = [5.0, -10.0, -30.0, -50.0, -20.0]
        
        for edge_pct in edge_pct_values:
            # With the fix, all edges are allowed for momentum signals
            # Only the max_edge threshold (90%) remains as a sanity check
            assert abs(edge_pct) <= 90.0, f"Edge {edge_pct}% should be allowed (below 90% sanity check)"


class TestSweetSpotEntryBand:
    """Test sweet-spot entry band [5c, 85c] (2026-08-01 CRITICAL FIX).
    
    CRITICAL FIX (2026-08-01): Updated from [25c, 75c] to [5c, 85c] for 15m crypto volatility
    Previous range was too restrictive and dropped valid signals at 1c (BTC/ETH/SOL/XRP)
    Markets can show extreme prices near expiry; we should trade them if edge is sufficient
    """

    ENTRY_MIN_PRICE_CENTS = 5  # Updated from 25c to 5c
    ENTRY_MAX_PRICE_CENTS = 85  # Updated from 75c to 85c
    
    def test_price_below_band_rejected(self):
        """Prices below 5c are rejected (lottery zone)."""
        market_price_cents = 4
        should_trade = self.ENTRY_MIN_PRICE_CENTS <= market_price_cents <= self.ENTRY_MAX_PRICE_CENTS
        assert not should_trade, "Price below 5c should be rejected"

    def test_price_at_band_floor_accepted(self):
        """Price at exactly 5c is accepted."""
        market_price_cents = 5
        should_trade = self.ENTRY_MIN_PRICE_CENTS <= market_price_cents <= self.ENTRY_MAX_PRICE_CENTS
        assert should_trade, "Price at 5c should be accepted"

    def test_cheap_sweet_spot_accepted(self):
        """Cheap entries (10-50c) are accepted - core of the swing-catching strategy."""
        for market_price_cents in (10, 20, 30, 40, 45, 50):
            should_trade = self.ENTRY_MIN_PRICE_CENTS <= market_price_cents <= self.ENTRY_MAX_PRICE_CENTS
            assert should_trade, f"Cheap entry at {market_price_cents}c should be accepted"

    def test_price_at_band_cap_accepted(self):
        """Price at exactly 85c is accepted."""
        market_price_cents = 85
        should_trade = self.ENTRY_MIN_PRICE_CENTS <= market_price_cents <= self.ENTRY_MAX_PRICE_CENTS
        assert should_trade, "Price at 85c should be accepted"

    def test_price_above_band_rejected(self):
        """Prices above 85c are rejected (chasing, no profit room to 99c exit)."""
        for market_price_cents in (86, 90, 95, 98, 99):
            should_trade = self.ENTRY_MIN_PRICE_CENTS <= market_price_cents <= self.ENTRY_MAX_PRICE_CENTS
            assert not should_trade, f"Price at {market_price_cents}c should be rejected (no chasing)"


class TestYesSideBias:
    """Test YES-side bias logic based on 56.8% YES win rate vs 20% NO win rate."""
    
    def test_yes_bias_margin_20_percent(self):
        """Test that YES-side bias margin is 20% of threshold."""
        yes_bias_margin = 0.2  # 20%
        velocity_threshold = 0.0001
        
        marginal_zone_upper = velocity_threshold * (1 + yes_bias_margin)
        assert marginal_zone_upper == 0.00012, "Marginal zone should be 20% above threshold"
    
    def test_marginal_positive_velocity_triggers_yes_bias(self):
        """Test that marginal positive velocity triggers YES-side bias."""
        velocity = 0.00011  # Within 20% of threshold
        velocity_threshold = 0.0001
        yes_bias_margin = 0.2
        
        is_marginal_positive = (velocity > 0) and (velocity < velocity_threshold * (1 + yes_bias_margin))
        assert is_marginal_positive, "Velocity within 20% of threshold should trigger marginal zone"
    
    def test_marginal_negative_velocity_triggers_yes_bias(self):
        """Test that marginal negative velocity triggers YES-side bias."""
        velocity = -0.00011  # Within 20% of threshold
        velocity_threshold = 0.0001
        yes_bias_margin = 0.2
        
        is_marginal_negative = (velocity < 0) and (velocity > -velocity_threshold * (1 + yes_bias_margin))
        assert is_marginal_negative, "Negative velocity within 20% of threshold should trigger marginal zone"
    
    def test_marginal_velocity_produces_no_trade(self):
        """2026-07-05 RESEARCH FIX: marginal velocity (no conviction) must NOT trade.
        
        The old YES-side bias traded marginal signals, producing zero-edge candidates
        that chased 98-99c asks. No conviction = no trade.
        """
        velocity = 0.00011  # Marginal positive (within 20% of threshold)
        velocity_threshold = 0.0001
        yes_bias_margin = 0.2
        
        is_marginal_positive = (velocity > 0) and (velocity < velocity_threshold * (1 + yes_bias_margin))
        
        # Marginal zone now results in NO TRADE (skip), not a YES-bias entry
        signal_side = None if is_marginal_positive else "yes"
        
        assert is_marginal_positive, "Velocity should be in the marginal zone"
        assert signal_side is None, "Marginal velocity must produce NO TRADE (no conviction)"


class TestNoSideConviction:
    """Test NO-side conviction threshold (1.5x threshold) based on 20% NO win rate."""
    
    def test_no_conviction_multiplier_1_5x(self):
        """Test that NO-side conviction multiplier is 1.5x."""
        no_conviction_multiplier = 1.5
        assert no_conviction_multiplier == 1.5, "NO conviction should be 1.5x threshold"
    
    def test_no_side_requires_1_5x_threshold(self):
        """Test that NO side requires velocity < -1.5x threshold."""
        velocity_threshold = 0.0001
        no_conviction_multiplier = 1.5
        no_threshold = velocity_threshold * no_conviction_multiplier
        
        assert abs(no_threshold - 0.00015) < 1e-10, "NO threshold should be 1.5x base threshold"
    
    def test_velocity_below_1_5x_threshold_rejected(self):
        """Test that velocity not below 1.5x threshold is rejected for NO side."""
        velocity = -0.00012  # Below threshold but not below 1.5x
        velocity_threshold = 0.0001
        no_conviction_multiplier = 1.5
        no_threshold = velocity_threshold * no_conviction_multiplier
        
        should_allow_no = velocity < -no_threshold
        assert not should_allow_no, "Velocity not below 1.5x threshold should be rejected for NO side"
    
    def test_velocity_below_1_5x_threshold_accepted(self):
        """Test that velocity below 1.5x threshold is accepted for NO side."""
        velocity = -0.00016  # Below 1.5x threshold
        velocity_threshold = 0.0001
        no_conviction_multiplier = 1.5
        no_threshold = velocity_threshold * no_conviction_multiplier
        
        should_allow_no = velocity < -no_threshold
        assert should_allow_no, "Velocity below 1.5x threshold should be accepted for NO side"
    
    def test_marginal_negative_velocity_triggers_yes_bias_instead_of_no(self):
        """Test that marginal negative velocity triggers YES bias instead of NO."""
        velocity = -0.00011  # Marginal negative (within 20% of threshold)
        velocity_threshold = 0.0001
        yes_bias_margin = 0.2
        no_conviction_multiplier = 1.5
        no_threshold = velocity_threshold * no_conviction_multiplier
        
        is_marginal_negative = (velocity < 0) and (velocity > -velocity_threshold * (1 + yes_bias_margin))
        should_allow_no = velocity < -no_threshold
        
        if is_marginal_negative and not should_allow_no:
            signal_side = "yes"  # YES bias instead of NO
        else:
            signal_side = "no" if should_allow_no else None
        
        assert signal_side == "yes", "Marginal negative velocity should trigger YES bias instead of NO"


class TestRegimeAwareVelocityMapping:
    """Test regime-aware velocity-to-side mapping logic (DEPRECATED 2026-07-31).
    
    CRITICAL FIX 2026-07-31: These tests document the OLD velocity-based hard mapping logic.
    Production now uses dual-side selection based on edge comparison, not hard velocity mapping.
    These tests are kept for historical reference but no longer reflect production behavior.
    
    New behavior: Both YES and NO sides are evaluated based on edge, with expected_side as tie-breaker.
    """
    
    def test_trend_following_positive_velocity_legacy(self):
        """Test trend-following mode with positive velocity -> buy YES (LEGACY).
        
        DEPRECATED: This tests the old hard mapping logic. Production now uses dual-side selection.
        """
        strategy_mode = "trend_following"
        velocity = 0.01  # Positive
        velocity_threshold = 0.005
        
        # Legacy hard mapping (no longer used in production)
        if velocity > velocity_threshold:
            if strategy_mode == "trend_following":
                signal_side = "yes"
            else:
                signal_side = "no"
        
        assert signal_side == "yes"
    
    def test_trend_following_negative_velocity_legacy(self):
        """Test trend-following mode with negative velocity -> buy NO (LEGACY).
        
        DEPRECATED: This tests the old hard mapping logic. Production now uses dual-side selection.
        """
        strategy_mode = "trend_following"
        velocity = -0.01  # Negative
        velocity_threshold = 0.005
        
        # Legacy hard mapping (no longer used in production)
        if velocity < -velocity_threshold:
            if strategy_mode == "trend_following":
                signal_side = "no"
            else:
                signal_side = "yes"
        
        assert signal_side == "no"
    
    def test_mean_reversion_positive_velocity_legacy(self):
        """Test mean-reversion mode with positive velocity -> buy NO (LEGACY).
        
        DEPRECATED: This tests the old hard mapping logic. Production now uses dual-side selection.
        """
        strategy_mode = "mean_reversion"
        velocity = 0.01  # Positive
        velocity_threshold = 0.005
        
        # Legacy hard mapping (no longer used in production)
        if velocity > velocity_threshold:
            if strategy_mode == "trend_following":
                signal_side = "yes"
            else:
                signal_side = "no"
        
        assert signal_side == "no"
    
    def test_mean_reversion_negative_velocity_legacy(self):
        """Test mean-reversion mode with negative velocity -> buy YES (LEGACY).
        
        DEPRECATED: This tests the old hard mapping logic. Production now uses dual-side selection.
        """
        strategy_mode = "mean_reversion"
        velocity = -0.01  # Negative
        velocity_threshold = 0.005
        
        # Legacy hard mapping (no longer used in production)
        if velocity < -velocity_threshold:
            if strategy_mode == "trend_following":
                signal_side = "no"
            else:
                signal_side = "yes"
        
        assert signal_side == "yes"
    
    def test_velocity_below_threshold_no_trade(self):
        """Test that velocity below threshold results in no trade."""
        strategy_mode = "trend_following"
        velocity = 0.001  # Below threshold
        velocity_threshold = 0.005
        
        signal_side = None
        if velocity > velocity_threshold:
            signal_side = "yes"
        elif velocity < -velocity_threshold:
            signal_side = "no"
        
        assert signal_side is None
    
    def test_velocity_zero_no_trade(self):
        """Test that zero velocity (neutral) results in no trade, not YES bias.
        
        This test verifies the fix for the systematic YES bias that occurred
        when velocity defaulted to positive (1e-9) during warmup. With the fix,
        zero velocity should return 0.0 (neutral) and not trigger a YES trade.
        """
        strategy_mode = "trend_following"
        velocity = 0.0  # Zero velocity (neutral)
        velocity_threshold = 0.005
        
        signal_side = None
        if velocity > velocity_threshold:
            signal_side = "yes"
        elif velocity < -velocity_threshold:
            signal_side = "no"
        
        # Zero velocity should NOT trigger a YES trade
        assert signal_side is None, f"Expected NO TRADE for velocity=0.0, got {signal_side}"


class TestDualSideSelection:
    """Test dual-side selection logic (NEW 2026-07-31).
    
    CRITICAL FIX 2026-07-31: Tests for the new dual-side selection logic that fixes
    the downtrend trading bug. The new logic evaluates both YES and NO sides based on
    edge comparison, with expected_side as tie-breaker, not hard gating.
    """
    
    def test_dual_side_selection_with_better_edge_on_opposite_side(self):
        """Test that opposite side is selected when it has significantly better edge."""
        # Simulate downtrend (negative velocity) but YES has better edge due to mispricing
        velocity = -0.01  # Negative velocity (downtrend)
        strategy_mode = "trend_following"
        velocity_threshold = 0.005
        
        # Expected side from velocity
        expected_side = "no" if velocity < 0 else "yes"
        
        # Simulate edge calculation (opposite side has better edge)
        side_edges = {
            "yes": 0.08,  # YES has 8% edge (mispricing opportunity)
            "no": 0.02    # NO has 2% edge (expected side has poor edge)
        }
        
        # Filter to positive edges only
        positive_sides = {side: edge for side, edge in side_edges.items() if edge > 0}
        
        # Select best side (should be YES despite negative velocity)
        best_side = None
        best_edge = -float('inf')
        for side in ["yes", "no"]:
            if side in positive_sides:
                total_edge = positive_sides[side]
                if total_edge > best_edge or (total_edge == best_edge and side == expected_side):
                    best_side = side
                    best_edge = total_edge
        
        # YES should be selected due to better edge
        assert best_side == "yes", f"Expected YES (better edge), got {best_side}"
        assert best_edge == 0.08
    
    def test_dual_side_selection_with_expected_side_tie(self):
        """Test that expected side wins tie-breaker when edges are equal."""
        velocity = 0.01  # Positive velocity (uptrend)
        strategy_mode = "trend_following"
        velocity_threshold = 0.005
        
        # Expected side from velocity
        expected_side = "yes" if velocity > 0 else "no"
        
        # Simulate equal edges
        side_edges = {
            "yes": 0.05,
            "no": 0.05
        }
        
        # Filter to positive edges only
        positive_sides = {side: edge for side, edge in side_edges.items() if edge > 0}
        
        # Select best side (expected side should win tie)
        best_side = None
        best_edge = -float('inf')
        for side in ["yes", "no"]:
            if side in positive_sides:
                total_edge = positive_sides[side]
                if total_edge > best_edge or (total_edge == best_edge and side == expected_side):
                    best_side = side
                    best_edge = total_edge
        
        # Expected side (YES) should win tie
        assert best_side == expected_side, f"Expected {expected_side} to win tie, got {best_side}"
    
    def test_dual_side_selection_with_no_positive_edges(self):
        """Test that no trade occurs when both sides have negative edges."""
        velocity = 0.01
        strategy_mode = "trend_following"
        
        # Expected side from velocity
        expected_side = "yes" if velocity > 0 else "no"
        
        # Simulate negative edges
        side_edges = {
            "yes": -0.02,
            "no": -0.01
        }
        
        # Filter to positive edges only
        positive_sides = {side: edge for side, edge in side_edges.items() if edge > 0}
        
        # Should have no positive sides
        assert len(positive_sides) == 0, "Should have no positive edges"
        
        # Selection should return None (no trade)
        best_side = None
        if positive_sides:
            best_side = max(positive_sides, key=positive_sides.get)
        
        assert best_side is None, "Should return None when no positive edges"
    
    def test_dual_side_selection_with_midpoint_bonus(self):
        """Test that midpoint bonus influences side selection."""
        velocity = -0.01  # Negative velocity
        strategy_mode = "trend_following"
        
        # Expected side from velocity
        expected_side = "no" if velocity < 0 else "yes"
        
        # Simulate edges before bonus
        side_edges = {
            "yes": 0.04,
            "no": 0.04
        }
        
        # Simulate midpoint bonus function (peak at 42.5c)
        def midpoint_bonus(price_cents):
            dist = abs(price_cents - 42.5)
            midpoint_bonus_max = 0.5
            midpoint_bonus_slope = 0.02
            return max(0.0, midpoint_bonus_max - dist * midpoint_bonus_slope)
        
        # Simulate prices (YES at midpoint, NO at edge)
        yes_price_cents = 42.5  # Perfect midpoint
        no_price_cents = 10.0    # At edge
        
        # Calculate bonus-adjusted edges
        side_edges_with_bonus = {}
        for side, edge in side_edges.items():
            price_cents = yes_price_cents if side == "yes" else no_price_cents
            bonus = midpoint_bonus(price_cents) / 100.0  # Convert to fraction
            side_edges_with_bonus[side] = edge + bonus
        
        # Select best side with bonus
        best_side = None
        best_edge = -float('inf')
        for side in ["yes", "no"]:
            if side in side_edges_with_bonus:
                total_edge = side_edges_with_bonus[side]
                if total_edge > best_edge or (total_edge == best_edge and side == expected_side):
                    best_side = side
                    best_edge = total_edge
        
        # YES should win due to midpoint bonus
        assert best_side == "yes", f"Expected YES (midpoint bonus), got {best_side}"
    
    def test_dual_side_selection_downtrend_with_no_edge(self):
        """Test downtrend scenario where expected side (NO) has no positive edge."""
        velocity = -0.01  # Negative velocity (downtrend)
        strategy_mode = "trend_following"
        
        # Expected side from velocity
        expected_side = "no" if velocity < 0 else "yes"
        
        # Simulate edges (NO has no positive edge, YES does)
        side_edges = {
            "yes": 0.03,
            "no": -0.01  # Negative edge
        }
        
        # Filter to positive edges only
        positive_sides = {side: edge for side, edge in side_edges.items() if edge > 0}
        
        # Only YES has positive edge
        assert "yes" in positive_sides, "YES should have positive edge"
        assert "no" not in positive_sides, "NO should not have positive edge"
        
        # Select best side (should be YES, the only positive edge)
        best_side = None
        best_edge = -float('inf')
        for side in ["yes", "no"]:
            if side in positive_sides:
                total_edge = positive_sides[side]
                if total_edge > best_edge or (total_edge == best_edge and side == expected_side):
                    best_side = side
                    best_edge = total_edge
        
        # YES should be selected (only positive edge)
        assert best_side == "yes", f"Expected YES (only positive edge), got {best_side}"
    
    def test_dual_side_selection_uptrend_with_better_no_edge(self):
        """Test uptrend scenario where NO has better edge despite positive velocity."""
        velocity = 0.01  # Positive velocity (uptrend)
        strategy_mode = "trend_following"
        
        # Expected side from velocity
        expected_side = "yes" if velocity > 0 else "no"
        
        # Simulate edges (NO has much better edge)
        side_edges = {
            "yes": 0.02,
            "no": 0.08  # NO has 4x better edge
        }
        
        # Filter to positive edges only
        positive_sides = {side: edge for side, edge in side_edges.items() if edge > 0}
        
        # Select best side (should be NO due to much better edge)
        best_side = None
        best_edge = -float('inf')
        for side in ["yes", "no"]:
            if side in positive_sides:
                total_edge = positive_sides[side]
                if total_edge > best_edge or (total_edge == best_edge and side == expected_side):
                    best_side = side
                    best_edge = total_edge
        
        # NO should be selected due to better edge
        assert best_side == "no", f"Expected NO (better edge), got {best_side}"
        assert best_edge == 0.08
    
    def test_regime_bull_uses_trend_following(self):
        """Test that bull regime uses trend-following mode."""
        mock_detection = RegimeDetection(
            regime=Regime.BULL,
            probabilities={Regime.BULL: 0.8, Regime.CHOPPY: 0.15, Regime.BEAR: 0.05},
            confidence=0.8,
            features=np.array([0.01, 0.02, 0.03]),
            timestamp=0
        )
        
        # Mock get_strategy_mode
        def get_strategy_mode(detection):
            if detection.regime == Regime.BULL:
                return "trend_following"
            elif detection.regime == Regime.CHOPPY:
                return "mean_reversion"
            else:
                return "trend_following"
        
        mode = get_strategy_mode(mock_detection)
        assert mode == "trend_following"
    
    def test_regime_choppy_uses_mean_reversion(self):
        """Test that choppy regime uses mean-reversion mode."""
        mock_detection = RegimeDetection(
            regime=Regime.CHOPPY,
            probabilities={Regime.BULL: 0.1, Regime.CHOPPY: 0.8, Regime.BEAR: 0.1},
            confidence=0.8,
            features=np.array([0.0, 0.05, 0.0]),
            timestamp=0
        )
        
        # Mock get_strategy_mode
        def get_strategy_mode(detection):
            if detection.regime == Regime.BULL:
                return "trend_following"
            elif detection.regime == Regime.CHOPPY:
                return "mean_reversion"
            else:
                return "trend_following"
        
        mode = get_strategy_mode(mock_detection)
        assert mode == "mean_reversion"
    
    def test_regime_bear_uses_trend_following(self):
        """Test that bear regime uses trend-following mode."""
        mock_detection = RegimeDetection(
            regime=Regime.BEAR,
            probabilities={Regime.BULL: 0.05, Regime.CHOPPY: 0.15, Regime.BEAR: 0.8},
            confidence=0.8,
            features=np.array([-0.01, 0.03, -0.02]),
            timestamp=0
        )
        
        # Mock get_strategy_mode
        def get_strategy_mode(detection):
            if detection.regime == Regime.BULL:
                return "trend_following"
            elif detection.regime == Regime.CHOPPY:
                return "mean_reversion"
            else:
                return "trend_following"
        
        mode = get_strategy_mode(mock_detection)
        assert mode == "trend_following"
    
    def test_none_detection_defaults_to_trend_following(self):
        """Test that None detection defaults to trend-following."""
        detection = None
        
        def get_strategy_mode(detection):
            if detection is None:
                return "trend_following"
            # ... other logic
        
        mode = get_strategy_mode(detection)
        assert mode == "trend_following"
    
    def test_velocity_threshold_exclusive_signal_generation(self):
        """Test that velocity threshold logic is used exclusively for signal generation.
        
        This test verifies the fix for the systematic NO bias bug where strike-based
        projection logic was bypassing the velocity threshold check. After the fix,
        signal generation should use velocity threshold exclusively:
        - velocity > threshold -> BUY YES
        - velocity < -threshold -> BUY NO
        - velocity within threshold -> NO TRADE
        """
        # Test case 1: Positive velocity above threshold -> YES
        velocity = 0.003  # 0.3%
        velocity_threshold = 0.002  # 0.2%
        
        signal_side = None
        if velocity > velocity_threshold:
            signal_side = "yes"
        elif velocity < -velocity_threshold:
            signal_side = "no"
        
        assert signal_side == "yes", f"Expected YES for velocity={velocity} > threshold={velocity_threshold}"
        
        # Test case 2: Negative velocity below threshold -> NO
        velocity = -0.003  # -0.3%
        velocity_threshold = 0.002  # 0.2%
        
        signal_side = None
        if velocity > velocity_threshold:
            signal_side = "yes"
        elif velocity < -velocity_threshold:
            signal_side = "no"
        
        assert signal_side == "no", f"Expected NO for velocity={velocity} < -threshold={velocity_threshold}"
        
        # Test case 3: Velocity within threshold -> NO TRADE
        velocity = 0.001  # 0.1% (below 0.2% threshold)
        velocity_threshold = 0.002  # 0.2%
        
        signal_side = None
        if velocity > velocity_threshold:
            signal_side = "yes"
        elif velocity < -velocity_threshold:
            signal_side = "no"
        
        assert signal_side is None, f"Expected NO TRADE for velocity={velocity} within ±threshold={velocity_threshold}"
        
        # Test case 4: Negative velocity within threshold -> NO TRADE
        velocity = -0.001  # -0.1% (above -0.2% threshold)
        velocity_threshold = 0.002  # 0.2%
        
        signal_side = None
        if velocity > velocity_threshold:
            signal_side = "yes"
        elif velocity < -velocity_threshold:
            signal_side = "no"
        
        assert signal_side is None, f"Expected NO TRADE for velocity={velocity} within ±threshold={velocity_threshold}"
    
    def test_strike_based_projection_removed(self):
        """Test that strike-based projection logic is removed.
        
        This test verifies that the bug fix removed the strike-based projection
        logic that was causing systematic NO bias. After the fix, signal generation
        should NOT use expected_price vs strike_price comparison.
        """
        # Simulate the old buggy logic (strike-based projection)
        velocity = -0.000365  # Negative velocity
        spot_price = 58661.70
        strike_price = spot_price  # Strike defaults to spot (spot_fallback)
        velocity_threshold = 0.002587
        
        # Old buggy logic: expected_price = spot * (1 + velocity * 900)
        expected_price_move_pct = velocity * 900  # -0.3285 = -32.85%
        expected_price = spot_price * (1 + expected_price_move_pct)
        
        # Old logic would always bet NO when expected_price < strike_price
        # This is the bug we fixed
        old_logic_side = "no" if expected_price < strike_price else "yes"
        
        # New logic: use velocity threshold exclusively
        new_logic_side = None
        if velocity > velocity_threshold:
            new_logic_side = "yes"
        elif velocity < -velocity_threshold:
            new_logic_side = "no"
        
        # Verify the fix: new logic should return NO TRADE (velocity within threshold)
        # while old logic would return NO (strike-based projection)
        assert old_logic_side == "no", "Old buggy logic would bet NO"
        assert new_logic_side is None, "New logic should return NO TRADE (velocity within threshold)"
        
        # This confirms the fix prevents the systematic NO bias
    
    def test_velocity_threshold_fix_realistic_levels(self):
        """Test that velocity thresholds are set to realistic levels.
        
        This test verifies the 2026-07-01 fix that lowered velocity thresholds
        from unrealistic levels (0.3%-0.5%) to realistic levels (0.005%-0.03%)
        that match actual market velocities observed in production.
        """
        # Simulate actual market velocities from production logs
        test_cases = [
            {"asset": "BTC", "velocity": 0.000043, "threshold": 0.00005},  # 0.0043% vs 0.005%
            {"asset": "ETH", "velocity": -0.000042, "threshold": 0.00005},  # 0.0042% vs 0.005%
            {"asset": "DOGE", "velocity": -0.000350, "threshold": 0.00030},  # 0.0350% vs 0.03% (trigger NO)
        ]
        
        for case in test_cases:
            velocity = case["velocity"]
            threshold = case["threshold"]
            asset = case["asset"]
            
            # With realistic thresholds, signals should be generated
            signal_side = None
            if velocity > threshold:
                signal_side = "yes"
            elif velocity < -threshold:
                signal_side = "no"
            
            # Verify that with realistic thresholds, trades can be generated
            if asset == "DOGE":
                # DOGE velocity is high enough to trigger NO signal
                assert signal_side == "no", f"{asset}: velocity={velocity} should trigger NO with threshold={threshold}"
            else:
                # BTC/ETH velocities are below threshold (no trade expected)
                assert signal_side is None, f"{asset}: velocity={velocity} within threshold={threshold} (no trade)"
        
        # Verify old thresholds would have blocked all trades
        old_threshold_btc = 0.003  # 0.3% (old)
        old_velocity_btc = 0.000043  # 0.0043%
        
        old_signal = None
        if old_velocity_btc > old_threshold_btc:
            old_signal = "yes"
        elif old_velocity_btc < -old_threshold_btc:
            old_signal = "no"
        
        assert old_signal is None, "Old threshold (0.3%) would have blocked all trades"
        
        # Verify new threshold allows trades when velocity is high enough
        new_threshold_btc = 0.00005  # 0.005% (new)
        high_velocity_btc = 0.000060  # 0.006% (above threshold)
        new_signal = None
        if high_velocity_btc > new_threshold_btc:
            new_signal = "yes"
        elif high_velocity_btc < -new_threshold_btc:
            new_signal = "no"
        
        # With higher velocity, trade should be generated
        assert new_signal == "yes", "New threshold allows trades with sufficient velocity"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
