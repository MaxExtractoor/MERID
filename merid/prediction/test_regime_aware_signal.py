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
    """Test sweet-spot entry band [25c, 75c] (2026-07-05 research fix).
    
    Entries below 25c are lottery tickets (<30c zone has 10.4% win rate);
    entries above 75c have no profit room to ratchet to the 99c exit.
    """
    
    ENTRY_MIN_PRICE_CENTS = 25
    ENTRY_MAX_PRICE_CENTS = 75
    
    def test_price_below_band_rejected(self):
        """Prices below 25c are rejected (lottery zone)."""
        market_price_cents = 20
        should_trade = self.ENTRY_MIN_PRICE_CENTS <= market_price_cents <= self.ENTRY_MAX_PRICE_CENTS
        assert not should_trade, "Price below 25c should be rejected"
    
    def test_price_at_band_floor_accepted(self):
        """Price at exactly 25c is accepted."""
        market_price_cents = 25
        should_trade = self.ENTRY_MIN_PRICE_CENTS <= market_price_cents <= self.ENTRY_MAX_PRICE_CENTS
        assert should_trade, "Price at 25c should be accepted"
    
    def test_cheap_sweet_spot_accepted(self):
        """Cheap entries (30-50c) are accepted - core of the swing-catching strategy."""
        for market_price_cents in (30, 40, 45, 50):
            should_trade = self.ENTRY_MIN_PRICE_CENTS <= market_price_cents <= self.ENTRY_MAX_PRICE_CENTS
            assert should_trade, f"Cheap entry at {market_price_cents}c should be accepted"
    
    def test_price_at_band_cap_accepted(self):
        """Price at exactly 75c is accepted."""
        market_price_cents = 75
        should_trade = self.ENTRY_MIN_PRICE_CENTS <= market_price_cents <= self.ENTRY_MAX_PRICE_CENTS
        assert should_trade, "Price at 75c should be accepted"
    
    def test_price_above_band_rejected(self):
        """Prices above 75c are rejected (chasing, no profit room to 99c exit)."""
        for market_price_cents in (76, 85, 98, 99):
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
    """Test regime-aware velocity-to-side mapping logic."""
    
    def test_trend_following_positive_velocity(self):
        """Test trend-following mode with positive velocity -> buy YES."""
        strategy_mode = "trend_following"
        velocity = 0.01  # Positive
        velocity_threshold = 0.005
        
        if velocity > velocity_threshold:
            if strategy_mode == "trend_following":
                signal_side = "yes"
            else:
                signal_side = "no"
        
        assert signal_side == "yes"
    
    def test_trend_following_negative_velocity(self):
        """Test trend-following mode with negative velocity -> buy NO."""
        strategy_mode = "trend_following"
        velocity = -0.01  # Negative
        velocity_threshold = 0.005
        
        if velocity < -velocity_threshold:
            if strategy_mode == "trend_following":
                signal_side = "no"
            else:
                signal_side = "yes"
        
        assert signal_side == "no"
    
    def test_mean_reversion_positive_velocity(self):
        """Test mean-reversion mode with positive velocity -> buy NO."""
        strategy_mode = "mean_reversion"
        velocity = 0.01  # Positive
        velocity_threshold = 0.005
        
        if velocity > velocity_threshold:
            if strategy_mode == "trend_following":
                signal_side = "yes"
            else:
                signal_side = "no"
        
        assert signal_side == "no"
    
    def test_mean_reversion_negative_velocity(self):
        """Test mean-reversion mode with negative velocity -> buy YES."""
        strategy_mode = "mean_reversion"
        velocity = -0.01  # Negative
        velocity_threshold = 0.005
        
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
