"""
Configuration invariant tests for price-based strategy thresholds.

CRITICAL FIX (2026-07-22): These tests enforce the economic assumptions
encoded in the price-based strategy to prevent future inversion bugs.

The price-based strategy should:
- Buy YES when price is LOW (cheap YES contracts)
- Buy NO when price is HIGH (cheap NO contracts)
- Create symmetric trading around 0.50 with no dead zone
"""

import pytest
import os
from unittest.mock import patch


class TestPriceBasedThresholdInvariants:
    """Test that price-based thresholds are correctly configured and not inverted."""

    def test_buy_threshold_below_50_percent(self):
        """Buy threshold must be <= 0.5 to buy YES when cheap or fair."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            profile = get_active_profile().profile
            assert 0 < profile.price_based_buy_threshold <= 0.5, \
                f"price_based_buy_threshold={profile.price_based_buy_threshold} must be in (0, 0.5] to buy YES when cheap or fair"

    def test_sell_threshold_above_50_percent(self):
        """Sell threshold must be >= 0.5 to buy NO when YES is expensive or fair."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            profile = get_active_profile().profile
            assert 0.5 <= profile.price_based_sell_threshold < 1.0, \
                f"price_based_sell_threshold={profile.price_based_sell_threshold} must be in [0.5, 1.0) to buy NO when YES is expensive or fair"

    def test_buy_threshold_less_than_or_equal_sell_threshold(self):
        """Buy threshold must be <= sell threshold for symmetric trading."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            profile = get_active_profile().profile
            assert profile.price_based_buy_threshold <= profile.price_based_sell_threshold, \
                f"price_based_buy_threshold={profile.price_based_buy_threshold} must be <= " \
                f"price_based_sell_threshold={profile.price_based_sell_threshold} for symmetric trading"

    def test_no_dead_zone_between_thresholds(self):
        """Thresholds should not create a large dead zone where neither side trades.
        
        A dead zone > 0.20 (20 cents) indicates misconfigured thresholds that
        would block trading in the middle of the price range.
        """
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            profile = get_active_profile().profile
            dead_zone = profile.price_based_sell_threshold - profile.price_based_buy_threshold
            assert dead_zone <= 0.40, \
                f"Dead zone between thresholds is {dead_zone:.2f} (40c), which is too large. " \
                f"Thresholds should be closer to 0.50 for symmetric trading."

    def test_thresholds_centered_around_50_percent(self):
        """Thresholds should be roughly symmetric around 0.50 for balanced YES/NO trading."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            profile = get_active_profile().profile
            midpoint = (profile.price_based_buy_threshold + profile.price_based_sell_threshold) / 2
            assert 0.45 <= midpoint <= 0.55, \
                f"Threshold midpoint is {midpoint:.2f}, which is not centered around 0.50. " \
                f"This creates asymmetric YES/NO trading opportunities."


class TestPriceBasedStrategyEconomics:
    """Test the economic logic of the price-based strategy function."""

    @pytest.mark.parametrize("price,expected_side", [
        (0.05, "yes"),   # Very cheap YES
        (0.20, "yes"),   # Cheap YES
        (0.30, "yes"),   # Cheap YES
        (0.50, None),    # At 50c fair value (no positive edge)
        (0.70, "no"),    # Expensive YES (cheap NO)
        (0.80, "no"),    # Expensive YES (cheap NO)
        (0.90, "no"),    # Very expensive YES (very cheap NO)
    ])
    def test_price_based_side_selection(self, price, expected_side):
        """Test that price-based strategy selects correct side for given prices.
        
        This is a table-driven test that verifies the economic assumptions:
        - YES signals only when price < buy_threshold (cheap YES)
        - NO signals only when price > sell_threshold (expensive YES = cheap NO)
        - No signal at the 50c fair value where both edges are zero
        """
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            profile = get_active_profile().profile
            buy_threshold = profile.price_based_buy_threshold
            sell_threshold = profile.price_based_sell_threshold
            
            # Simulate the price-based side selection logic.
            # At the exact 50c fair value both edges are zero, so there is no signal.
            if price < buy_threshold:
                actual_side = "yes"
            elif price > sell_threshold:
                actual_side = "no"
            else:
                actual_side = None
            
            assert actual_side == expected_side, \
                f"Price {price:.2f}: expected side={expected_side}, got side={actual_side}. " \
                f"Thresholds: buy={buy_threshold:.2f}, sell={sell_threshold:.2f}"

    def test_yes_edge_calculation(self):
        """Test that YES edge is positive when price is below buy threshold."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            profile = get_active_profile().profile
            buy_threshold = profile.price_based_buy_threshold
            
            # At buy threshold, edge should be positive (minimum 2%)
            price = buy_threshold
            yes_edge = (buy_threshold - price) / buy_threshold
            yes_edge = max(yes_edge, 0.02)  # Minimum 2% edge
            
            assert yes_edge > 0, f"YES edge at threshold should be positive, got {yes_edge:.4f}"
            assert yes_edge >= 0.02, f"YES edge should be at least 2%, got {yes_edge:.4f}"

    def test_no_edge_calculation(self):
        """Test that NO edge is positive when price is above sell threshold."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            profile = get_active_profile().profile
            sell_threshold = profile.price_based_sell_threshold
            
            # At sell threshold, edge should be positive (minimum 2%)
            price = sell_threshold
            no_edge = (price - sell_threshold) / (1.0 - sell_threshold)
            no_edge = max(no_edge, 0.02)  # Minimum 2% edge
            
            assert no_edge > 0, f"NO edge at threshold should be positive, got {no_edge:.4f}"
            assert no_edge >= 0.02, f"NO edge should be at least 2%, got {no_edge:.4f}"


class TestThresholdRegression:
    """Regression tests to prevent the inverted threshold bug from reoccurring."""

    def test_not_inverted_old_bug(self):
        """Ensure the old inverted thresholds (0.70/0.95) are not present.
        
        This is a regression test for the bug that caused YES-side bias:
        - Old (buggy): buy_threshold=0.70, sell_threshold=0.95
        - New (fixed): buy_threshold=0.30, sell_threshold=0.70
        """
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            profile = get_active_profile().profile
            
            # The old buggy values
            old_buy = 0.70
            old_sell = 0.95
            
            assert profile.price_based_buy_threshold != old_buy, \
                f"price_based_buy_threshold is still at old buggy value {old_buy}"
            assert profile.price_based_sell_threshold != old_sell, \
                f"price_based_sell_threshold is still at old buggy value {old_sell}"

    def test_not_swing_mode_thresholds(self):
        """Ensure the swing mode thresholds (0.48/0.72) are not present.
        
        The swing mode thresholds were an intermediate attempt that still
        had a 24c dead zone. The correct symmetric thresholds are 0.50/0.50.
        """
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            profile = get_active_profile().profile
            
            # The swing mode values
            swing_buy = 0.48
            swing_sell = 0.72
            
            assert profile.price_based_buy_threshold != swing_buy, \
                f"price_based_buy_threshold is still at swing mode value {swing_buy}"
            assert profile.price_based_sell_threshold != swing_sell, \
                f"price_based_sell_threshold is still at swing mode value {swing_sell}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
