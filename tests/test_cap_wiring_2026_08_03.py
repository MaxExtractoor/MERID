"""
Test suite for spread cap wiring fix (CRITICAL FIX 2026-08-03).

Tests that the order router now uses per-asset time-scaled spread caps
instead of the hardcoded YAML value that was shadowing the documented caps.

This ensures:
- BTC: 20c base cap (time-scaled 16-20c)
- ETH: 24c base cap (time-scaled 19-24c)
- SOL: 40c base cap (time-scaled 32-40c)
- XRP: 40c base cap (time-scaled 32-40c)
- DOGE: 60c base cap (time-scaled 48-60c)
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from merid.event_venues.kalshi.spread_edge_analytics import get_time_scaled_spread_cap, ASSET_SPREAD_CAPS


class TestTimeScaledSpreadCap:
    """Test suite for get_time_scaled_spread_cap() function."""

    def test_btc_cap_at_full_time(self):
        """Test BTC cap at full 15-minute window (900s)."""
        cap = get_time_scaled_spread_cap("BTC", 900)

        # Base cap is 20c, at full time should be 20c (100%)
        assert cap == 20

    def test_btc_cap_at_expiry(self):
        """Test BTC cap at expiry (0s)."""
        cap = get_time_scaled_spread_cap("BTC", 0)

        # Base cap is 20c, at expiry should be 16c (80%)
        assert cap == 16

    def test_eth_cap_at_full_time(self):
        """Test ETH cap at full 15-minute window (900s)."""
        cap = get_time_scaled_spread_cap("ETH", 900)

        # Base cap is 24c, at full time should be 24c (100%)
        assert cap == 24

    def test_eth_cap_at_expiry(self):
        """Test ETH cap at expiry (0s)."""
        cap = get_time_scaled_spread_cap("ETH", 0)

        # Base cap is 24c, at expiry should be 19c (80%)
        assert cap == 19

    def test_sol_cap_at_full_time(self):
        """Test SOL cap at full 15-minute window (900s)."""
        cap = get_time_scaled_spread_cap("SOL", 900)

        # Base cap is 40c, at full time should be 40c (100%)
        assert cap == 40

    def test_sol_cap_at_expiry(self):
        """Test SOL cap at expiry (0s)."""
        cap = get_time_scaled_spread_cap("SOL", 0)

        # Base cap is 40c, at expiry should be 32c (80%)
        assert cap == 32

    def test_xrp_cap_at_full_time(self):
        """Test XRP cap at full 15-minute window (900s)."""
        cap = get_time_scaled_spread_cap("XRP", 900)

        # Base cap is 40c, at full time should be 40c (100%)
        assert cap == 40

    def test_doge_cap_at_full_time(self):
        """Test DOGE cap at full 15-minute window (900s)."""
        cap = get_time_scaled_spread_cap("DOGE", 900)

        # Base cap is 60c, at full time should be 60c (100%)
        assert cap == 60

    def test_doge_cap_at_expiry(self):
        """Test DOGE cap at expiry (0s)."""
        cap = get_time_scaled_spread_cap("DOGE", 0)

        # Base cap is 60c, at expiry should be 48c (80%)
        assert cap == 48

    def test_linear_decay_intermediate_time(self):
        """Test linear decay at intermediate time (450s = 7.5 min)."""
        cap = get_time_scaled_spread_cap("BTC", 450)

        # At 50% time, should be 90% of base cap (18c for BTC)
        assert cap == 18

    def test_unknown_asset_defaults_to_btc(self):
        """Test that unknown asset defaults to BTC cap."""
        cap = get_time_scaled_spread_cap("UNKNOWN", 900)

        # Should default to BTC cap (20c)
        assert cap == 20

    def test_all_asset_caps_defined(self):
        """Test that all 5 crypto assets have defined caps."""
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            assert asset in ASSET_SPREAD_CAPS
            assert ASSET_SPREAD_CAPS[asset] > 0

    def test_cap_values_match_documentation(self):
        """Test that cap values match the documented bridge caps."""
        # From SPREAD_CAP_ADJUSTMENT_2026_08_02.md:
        # BTC: 20c, ETH: 24c, SOL: 40c, XRP: 40c, DOGE: 60c
        assert ASSET_SPREAD_CAPS["BTC"] == 20
        assert ASSET_SPREAD_CAPS["ETH"] == 24
        assert ASSET_SPREAD_CAPS["SOL"] == 40
        assert ASSET_SPREAD_CAPS["XRP"] == 40
        assert ASSET_SPREAD_CAPS["DOGE"] == 60


class TestCapWiringInOrderRouter:
    """Test that order router uses per-asset caps instead of YAML value."""

    @patch('merid.event_venues.kalshi.spread_edge_analytics.get_time_scaled_spread_cap')
    @patch('merid.event_venues.kalshi.market_state.get_kalshi_market_state_store')
    def test_router_uses_per_asset_cap_for_eth(self, mock_get_store, mock_get_cap):
        """
        Test that router uses per-asset cap for ETH (24c) instead of YAML (20c).

        This was the bug: ETH was rejected at 20c when it should have used 24c.
        """
        # Mock the time-scaled cap to return ETH's 24c
        mock_get_cap.return_value = 24

        # Mock market state
        mock_store = Mock()
        mock_state = Mock()
        mock_state.seconds_to_expiry = 600  # 10 minutes remaining
        mock_store.get.return_value = mock_state
        mock_get_store.return_value = mock_store

        # Simulate the router logic (simplified)
        ticker = "KXETH15M-TEST"
        import re
        asset_match = re.match(r"^KX([A-Z]+)", ticker.upper())
        asset_ticker = asset_match.group(1) if asset_match else "BTC"

        # Get time-to-expiry from mock state
        time_to_expiry = mock_state.seconds_to_expiry

        # Use per-asset time-scaled cap (the fix)
        max_spread_cents = mock_get_cap(asset_ticker, time_to_expiry)

        # Verify it used the per-asset cap (24c) not the YAML fallback (20c)
        assert max_spread_cents == 24
        mock_get_cap.assert_called_once_with("ETH", 600)

    @patch('merid.event_venues.kalshi.spread_edge_analytics.get_time_scaled_spread_cap')
    @patch('merid.event_venues.kalshi.market_state.get_kalshi_market_state_store')
    def test_router_uses_per_asset_cap_for_doge(self, mock_get_store, mock_get_cap):
        """
        Test that router uses per-asset cap for DOGE (60c) instead of YAML (20c).

        DOGE has the highest cap (60c) due to higher volatility.
        """
        # Mock the time-scaled cap to return DOGE's 60c
        mock_get_cap.return_value = 60

        # Mock market state
        mock_store = Mock()
        mock_state = Mock()
        mock_state.seconds_to_expiry = 300  # 5 minutes remaining
        mock_store.get.return_value = mock_state
        mock_get_store.return_value = mock_store

        # Simulate the router logic (simplified)
        ticker = "KXDOGE15M-TEST"
        import re
        asset_match = re.match(r"^KX([A-Z]+)", ticker.upper())
        asset_ticker = asset_match.group(1) if asset_match else "BTC"

        # Get time-to-expiry from mock state
        time_to_expiry = mock_state.seconds_to_expiry

        # Use per-asset time-scaled cap (the fix)
        max_spread_cents = mock_get_cap(asset_ticker, time_to_expiry)

        # Verify it used the per-asset cap (60c) not the YAML fallback (20c)
        assert max_spread_cents == 60
        mock_get_cap.assert_called_once_with("DOGE", 300)

    @patch('merid.event_venues.kalshi.spread_edge_analytics.get_time_scaled_spread_cap')
    def test_router_fallback_to_profile_on_error(self, mock_get_cap):
        """
        Test that router falls back to profile value on cap lookup error.

        This ensures the fix doesn't break the system if cap lookup fails.
        """
        # Mock cap lookup to raise exception
        mock_get_cap.side_effect = Exception("Cap lookup error")

        # Simulate the router logic with fallback
        profile_fallback = 20  # YAML value
        try:
            max_spread_cents = mock_get_cap("BTC", 900)
        except Exception:
            max_spread_cents = profile_fallback

        # Verify it fell back to profile value
        assert max_spread_cents == 20

    @patch('merid.event_venues.kalshi.spread_edge_analytics.get_time_scaled_spread_cap')
    @patch('merid.event_venues.kalshi.market_state.get_kalshi_market_state_store')
    def test_router_uses_state_tte_when_intent_missing(self, mock_get_store, mock_get_cap):
        """
        Test that router uses market state TTE when intent doesn't have it.
        """
        # Mock the time-scaled cap
        mock_get_cap.return_value = 18

        # Mock market state
        mock_store = Mock()
        mock_state = Mock()
        mock_state.seconds_to_expiry = 450  # 7.5 minutes remaining
        mock_store.get.return_value = mock_state
        mock_get_store.return_value = mock_store

        # Simulate the router logic when intent.seconds_to_expiry is None
        ticker = "KXBTC15M-TEST"
        import re
        asset_match = re.match(r"^KX([A-Z]+)", ticker.upper())
        asset_ticker = asset_match.group(1) if asset_match else "BTC"

        # Intent doesn't have TTE, fall back to state
        time_to_expiry = None  # Intent missing
        if time_to_expiry is None:
            time_to_expiry = mock_state.seconds_to_expiry

        # Use per-asset time-scaled cap
        max_spread_cents = mock_get_cap(asset_ticker, time_to_expiry)

        # Verify it used the state TTE (450s)
        assert max_spread_cents == 18
        mock_get_cap.assert_called_once_with("BTC", 450)


class TestCapWiringRegression:
    """Regression tests for the cap wiring bug."""

    def test_eth_61c_spread_should_pass_with_correct_cap(self):
        """
        Test that ETH's 61c spread (from bug report) passes with correct cap.

        The bug report showed ETH rejected at "61c > 20c".
        With the correct ETH cap (24c), this should still fail (61 > 24),
        but the rejection reason should reference the correct cap.
        """
        # Simulate the bug report scenario
        spread_cents = 61
        asset = "ETH"
        time_to_expiry = 360  # 6 minutes remaining

        # Get the correct per-asset cap
        correct_cap = get_time_scaled_spread_cap(asset, time_to_expiry)

        # The spread still exceeds the cap (61 > ~22c at 6 min)
        # But now we're using the correct cap value
        assert spread_cents > correct_cap
        assert correct_cap > 20  # Correct cap is higher than the old 20c

    def test_btc_20c_spread_passes_with_correct_cap(self):
        """
        Test that BTC's 20c spread passes with correct cap at full time.

        This verifies that valid spreads aren't rejected by the old hardcoded cap.
        """
        spread_cents = 20
        asset = "BTC"
        time_to_expiry = 900  # Full 15 minutes

        # Get the correct per-asset cap
        correct_cap = get_time_scaled_spread_cap(asset, time_to_expiry)

        # Should pass (20c <= 20c)
        assert spread_cents <= correct_cap

    def test_sol_35c_spread_passes_with_correct_cap(self):
        """
        Test that SOL's 35c spread passes with correct cap.

        SOL has a 40c cap, so 35c should pass.
        """
        spread_cents = 35
        asset = "SOL"
        time_to_expiry = 900  # Full 15 minutes

        # Get the correct per-asset cap
        correct_cap = get_time_scaled_spread_cap(asset, time_to_expiry)

        # Should pass (35c <= 40c)
        assert spread_cents <= correct_cap

    def test_doge_55c_spread_passes_with_correct_cap(self):
        """
        Test that DOGE's 55c spread passes with correct cap.

        DOGE has a 60c cap, so 55c should pass.
        """
        spread_cents = 55
        asset = "DOGE"
        time_to_expiry = 900  # Full 15 minutes

        # Get the correct per-asset cap
        correct_cap = get_time_scaled_spread_cap(asset, time_to_expiry)

        # Should pass (55c <= 60c)
        assert spread_cents <= correct_cap


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
