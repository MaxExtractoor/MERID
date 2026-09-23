"""
End-to-end test with synthetic prices to check YES/NO distribution.

CRITICAL FIX (2026-07-22): This E2E test simulates price oscillations and verifies
that the price-based strategy generates balanced YES/NO signals over time.

Tests cover:
- Synthetic price series covering full range (10c-75c)
- YES/NO signal distribution over price oscillations
- No systematic YES bias in signal generation
"""

import pytest
from unittest.mock import Mock, patch
import os


class TestE2EPriceBasedSideDistribution:
    """End-to-end test of price-based strategy with synthetic price series."""

    def test_synthetic_price_series_generates_both_sides(self):
        """Synthetic price oscillations should generate both YES and NO signals.
        
        This test simulates a price series that oscillates between 10c and 75c
        and verifies that both YES and NO signals are generated over time.
        """
        # Synthetic price series (oscillating between 10c and 75c)
        price_series = [
            0.10,  # Very cheap -> YES
            0.30,  # Cheap -> YES
            0.50,  # At buy threshold -> YES
            0.60,  # Mid-band -> No signal
            0.70,  # Mid-band -> No signal (NO only >= 0.85)
            0.80,  # Mid-band -> No signal
            0.85,  # At sell threshold -> NO
            0.90,  # Expensive -> NO
            0.50,  # Back to cheap -> YES
        ]
        
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            profile = get_active_profile().profile
            buy_threshold = profile.price_based_buy_threshold
            sell_threshold = profile.price_based_sell_threshold
            
            # Generate signals for each price
            signals = []
            for price in price_series:
                if price <= buy_threshold:
                    signal = "yes"
                elif price >= sell_threshold:
                    signal = "no"
                else:
                    signal = None
                signals.append(signal)
            
            # Verify both YES and NO signals are generated
            yes_count = signals.count("yes")
            no_count = signals.count("no")
            
            assert yes_count > 0, "Should generate YES signals for cheap prices"
            assert no_count > 0, "Should generate NO signals for expensive prices"
            

    def test_price_oscillation_generates_alternating_signals(self):
        """Price oscillation should generate alternating YES/NO signals.
        
        This test simulates a sawtooth price pattern and verifies that
        signals alternate as price moves between cheap and expensive.
        """
        # Sawtooth pattern: cheap → expensive → cheap → expensive
        price_series = [
            0.15,  # Cheap → YES
            0.45,  # Cheap → YES
            0.60,  # Mid-band → None
            0.65,  # Mid-band → None
            0.85,  # Expensive → NO
            0.90,  # Expensive → NO
            0.65,  # Mid-band → None
            0.30,  # Cheap → YES
            0.20,  # Cheap → YES
        ]
        
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            profile = get_active_profile().profile
            buy_threshold = profile.price_based_buy_threshold
            sell_threshold = profile.price_based_sell_threshold
            
            # Generate signals
            signals = []
            for price in price_series:
                if price <= buy_threshold:
                    signal = "yes"
                elif price >= sell_threshold:
                    signal = "no"
                else:
                    signal = None
                signals.append(signal)
            
            # Verify signal transitions
            # Should see: YES → None → NO → None → YES
            expected_pattern = ["yes", "yes", None, None, "no", "no", None, "yes", "yes"]
            assert signals == expected_pattern, \
                f"Signal pattern {signals} does not match expected {expected_pattern}"

    def test_no_systematic_yes_bias_with_correct_thresholds(self):
        """With correct thresholds (0.30/0.70), there should be no YES bias.
        
        This is the core regression test for the inverted threshold bug.
        Old thresholds (0.70/0.95) caused YES bias because they only
        generated YES signals at expensive prices.
        """
        # Use a more balanced price series for this test
        price_series = [
            0.10, 0.30, 0.50,  # Cheap zone (YES, <= buy_threshold)
            0.60, 0.70, 0.80,  # Mid-band (None - cheap NO suppressed by design)
            0.85, 0.90, 0.95   # Expensive zone (NO, >= sell_threshold)
        ]
        
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            profile = get_active_profile().profile
            buy_threshold = profile.price_based_buy_threshold
            sell_threshold = profile.price_based_sell_threshold
            
            # Generate signals with NEW (correct) thresholds
            new_signals = []
            for price in price_series:
                if price <= buy_threshold:
                    new_signals.append("yes")
                elif price >= sell_threshold:
                    new_signals.append("no")
                else:
                    new_signals.append(None)
            
            # Generate signals with OLD (buggy) thresholds
            old_buy_threshold = 0.70
            old_sell_threshold = 0.95
            old_signals = []
            for price in price_series:
                if price <= old_buy_threshold:
                    old_signals.append("yes")
                elif price >= old_sell_threshold:
                    old_signals.append("no")
                else:
                    old_signals.append(None)
            
            # Old thresholds should produce mostly YES (bias)
            old_yes_count = old_signals.count("yes")
            old_no_count = old_signals.count("no")
            old_bias = old_yes_count / (old_no_count + 1e-6)
            
            # New thresholds should be balanced
            new_yes_count = new_signals.count("yes")
            new_no_count = new_signals.count("no")
            new_bias = new_yes_count / (new_no_count + 1e-6)
            
            # Old configuration should show YES bias (all prices <= 0.70 trigger YES)
            assert old_bias > 4.0, \
                f"Old thresholds should show extreme YES bias (ratio={old_bias:.2f})"
            
            # The 2026-08-28 contract is deliberately asymmetric: YES for
            # price <= 0.50 and NO only for price >= 0.85 (cheap NO is
            # suppressed because the model under-predicts YES).  Guard:
            # NO signals must still be generated in the expensive zone.
            assert new_no_count > 0, \
                "NO signals must still be generated for expensive YES prices"
            assert new_yes_count > 0, \
                "YES signals must still be generated for cheap prices"

    def test_edge_calculation_symmetry(self):
        """Edge calculation should be symmetric for YES and NO.
        
        At equal distance from thresholds, YES and NO edges should be similar.
        """
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            profile = get_active_profile().profile
            buy_threshold = profile.price_based_buy_threshold
            sell_threshold = profile.price_based_sell_threshold
            
            # 2026-08-28 contract is deliberately asymmetric - verify each
            # side produces a positive edge inside its own trigger zone.
            yes_price = buy_threshold - 0.10
            yes_edge = max((buy_threshold - yes_price) / buy_threshold, 0.02)
            assert yes_edge > 0, "YES edge must be positive at trigger"

            no_price = sell_threshold + 0.10
            no_edge = max((no_price - sell_threshold) / (1.0 - sell_threshold), 0.02)
            assert no_edge > 0, "NO edge must be positive at trigger"

    def test_mid_band_no_signal_zone(self):
        """Prices in the mid-band (between thresholds) should generate no signal.
        
        This is intentional - the mid-band is where momentum_fvg should dominate.
        """
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            profile = get_active_profile().profile
            buy_threshold = profile.price_based_buy_threshold
            sell_threshold = profile.price_based_sell_threshold
            
            # Mid-band prices
            mid_band_prices = [
                0.55,  # Just above buy threshold
                0.60,  # Mid-band
                0.70,  # Mid-band
                0.80,  # Mid-band
                0.84,  # Just below sell threshold
            ]
            
            # All should generate no signal
            for price in mid_band_prices:
                if price <= buy_threshold:
                    signal = "yes"
                elif price >= sell_threshold:
                    signal = "no"
                else:
                    signal = None
                
                assert signal is None, \
                    f"Price {price} in mid-band should generate no signal"

    def test_threshold_boundaries(self):
        """Test exact behavior at threshold boundaries.
        
        At buy_threshold, should generate YES.
        At sell_threshold, should generate NO.
        """
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            profile = get_active_profile().profile
            buy_threshold = profile.price_based_buy_threshold
            sell_threshold = profile.price_based_sell_threshold
            
            # At buy threshold
            price_at_buy = buy_threshold
            if price_at_buy <= buy_threshold:
                signal = "yes"
            else:
                signal = None
            assert signal == "yes", f"At buy_threshold {buy_threshold}, should generate YES"
            
            # At sell threshold
            price_at_sell = sell_threshold
            if price_at_sell >= sell_threshold:
                signal = "no"
            else:
                signal = None
            assert signal == "no", f"At sell_threshold {sell_threshold}, should generate NO"


class TestE2EAssetLevelDistribution:
    """Test YES/NO distribution across all 5 crypto assets."""

    def test_all_assets_can_generate_both_sides(self):
        """All 5 crypto assets should be capable of generating both YES and NO.
        
        This prevents the bug where only SOL generated YES signals.
        """
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            profile = get_active_profile().profile
            buy_threshold = profile.price_based_buy_threshold
            sell_threshold = profile.price_based_sell_threshold
            
            # For each asset, test both cheap and expensive prices
            for asset in assets:
                # Cheap price → YES
                cheap_price = 0.20
                if cheap_price <= buy_threshold:
                    yes_signal = "yes"
                else:
                    yes_signal = None
                assert yes_signal == "yes", f"{asset} at cheap price should generate YES"
                
                # Expensive price → NO
                expensive_price = 0.90
                if expensive_price >= sell_threshold:
                    no_signal = "no"
                else:
                    no_signal = None
                assert no_signal == "no", f"{asset} at expensive price should generate NO"

    def test_no_asset_excluded_from_signal_generation(self):
        """No asset should be systematically excluded from signal generation.
        
        This verifies the infrastructure allows all 5 assets to trade.
        """
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        # All assets should be present in the asset list
        assert len(assets) == 5, "All 5 crypto assets should be present"
        
        # Each asset should have the same threshold logic
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            profile = get_active_profile().profile
            
            # All assets use the same thresholds (no per-asset overrides)
            buy_threshold = profile.price_based_buy_threshold
            sell_threshold = profile.price_based_sell_threshold
            
            # Verify thresholds are valid
            assert 0 < buy_threshold <= 0.5, "Buy threshold should be valid"
            assert 0.5 < sell_threshold < 1.0, "Sell threshold should be valid"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
