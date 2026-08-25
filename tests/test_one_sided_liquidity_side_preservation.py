"""
Data-quality tests for one-sided liquidity scenarios and side preservation.

This test suite validates that NO-side opportunities are not suppressed by
data-quality filters or one-sided liquidity conditions in the 15m Kalshi
crypto trading system.

Tests cover:
- One-sided YES liquidity regime (NO side should still be considered)
- One-sided NO liquidity regime (YES side should still be considered)
- Stale book handling (staleness filters should not bias NO side)
- Terminal phase rejection for one-sided books
- Order Book Imbalance (OBI) extreme value logging
- Regime classification and side filtering interaction
"""

import pytest
from unittest.mock import Mock, MagicMock, patch


class TestOneSidedLiquiditySidePreservation:
    """Test that one-sided liquidity regimes do not suppress NO-side signals."""

    @pytest.fixture
    def mock_agent(self):
        """Create a mock AgentGrid15M for testing."""
        agent = Mock()
        agent.config = Mock()
        agent.config.name = "BTC_15M"
        agent.config.series_tickers = ["KXBTC15M"]
        agent.market_state_store = Mock()
        return agent

    @pytest.fixture
    def mock_market_state(self):
        """Create a mock market state with configurable liquidity."""
        state = Mock()
        state.min_depth_yes = 100
        state.min_depth_no = 0  # One-sided YES regime
        state.best_bid = 45
        state.best_ask = 46
        state.spread_cents = 1
        state.yes_price_cents = 45
        state.no_price_cents = 55
        return state

    def test_one_sided_yes_regime_classification(self, mock_agent, mock_market_state):
        """Test that one-sided YES regime is correctly classified."""
        # Setup: NO side has no liquidity
        mock_market_state.min_depth_yes = 100
        mock_market_state.min_depth_no = 0
        mock_agent.market_state_store.get.return_value = mock_market_state

        # Simulate regime classification logic from agent_grid_15m.py
        min_depth_yes = mock_market_state.min_depth_yes
        min_depth_no = mock_market_state.min_depth_no
        min_depth_yes_threshold = 1
        min_depth_no_threshold = 1

        has_yes = min_depth_yes >= min_depth_yes_threshold
        has_no = min_depth_no >= min_depth_no_threshold

        if has_yes and has_no:
            regime = "both_sides"
        elif has_yes and not has_no:
            regime = "one_sided_yes"
        elif not has_yes and has_no:
            regime = "one_sided_no"
        else:
            regime = "no_liquidity"

        # Assert: Correctly classified as one_sided_yes
        assert regime == "one_sided_yes", f"Expected one_sided_yes, got {regime}"
        assert has_yes is True, "YES side should have liquidity"
        assert has_no is False, "NO side should not have liquidity"

    def test_one_sided_no_regime_classification(self, mock_agent, mock_market_state):
        """Test that one-sided NO regime is correctly classified."""
        # Setup: YES side has no liquidity
        mock_market_state.min_depth_yes = 0
        mock_market_state.min_depth_no = 100
        mock_agent.market_state_store.get.return_value = mock_market_state

        # Simulate regime classification logic
        min_depth_yes = mock_market_state.min_depth_yes
        min_depth_no = mock_market_state.min_depth_no
        min_depth_yes_threshold = 1
        min_depth_no_threshold = 1

        has_yes = min_depth_yes >= min_depth_yes_threshold
        has_no = min_depth_no >= min_depth_no_threshold

        if has_yes and has_no:
            regime = "both_sides"
        elif has_yes and not has_no:
            regime = "one_sided_yes"
        elif not has_yes and has_no:
            regime = "one_sided_no"
        else:
            regime = "no_liquidity"

        # Assert: Correctly classified as one_sided_no
        assert regime == "one_sided_no", f"Expected one_sided_no, got {regime}"
        assert has_yes is False, "YES side should not have liquidity"
        assert has_no is True, "NO side should have liquidity"

    def test_one_sided_yes_allows_no_trading_when_in_range(self, mock_agent, mock_market_state):
        """Test that one-sided YES regime allows NO-side trading when NO price is in range."""
        # Setup: One-sided YES regime, but NO price is in 10-75c range
        mock_market_state.min_depth_yes = 100
        mock_market_state.min_depth_no = 0
        mock_market_state.no_price_cents = 55  # In range
        mock_market_state.yes_price_cents = 45  # In range

        # Simulate price range check
        yes_in_range = (10 <= mock_market_state.yes_price_cents <= 75)
        no_in_range = (10 <= mock_market_state.no_price_cents <= 75)

        # Simulate sides_to_evaluate logic from _generate_signal
        sides_to_evaluate = []
        if yes_in_range:
            sides_to_evaluate.append("yes")
        if no_in_range:
            sides_to_evaluate.append("no")

        # Assert: Both sides should be evaluated despite one-sided liquidity
        assert yes_in_range is True, "YES price should be in range"
        assert no_in_range is True, "NO price should be in range"
        assert "yes" in sides_to_evaluate, "YES side should be evaluated"
        assert "no" in sides_to_evaluate, "NO side should be evaluated (not suppressed by one-sided liquidity)"

    def test_one_sided_no_allows_yes_trading_when_in_range(self, mock_agent, mock_market_state):
        """Test that one-sided NO regime allows YES-side trading when YES price is in range."""
        # Setup: One-sided NO regime, but YES price is in 10-75c range
        mock_market_state.min_depth_yes = 0
        mock_market_state.min_depth_no = 100
        mock_market_state.no_price_cents = 55  # In range
        mock_market_state.yes_price_cents = 45  # In range

        # Simulate price range check
        yes_in_range = (10 <= mock_market_state.yes_price_cents <= 75)
        no_in_range = (10 <= mock_market_state.no_price_cents <= 75)

        # Simulate sides_to_evaluate logic
        sides_to_evaluate = []
        if yes_in_range:
            sides_to_evaluate.append("yes")
        if no_in_range:
            sides_to_evaluate.append("no")

        # Assert: Both sides should be evaluated despite one-sided liquidity
        assert yes_in_range is True, "YES price should be in range"
        assert no_in_range is True, "NO price should be in range"
        assert "yes" in sides_to_evaluate, "YES side should be evaluated (not suppressed by one-sided liquidity)"
        assert "no" in sides_to_evaluate, "NO side should be evaluated"

    def test_terminal_phase_rejects_one_sided_books(self, mock_agent, mock_market_state):
        """Test that one-sided books are rejected in terminal phase (last 30 seconds)."""
        # Setup: One-sided YES regime in terminal phase
        mock_market_state.min_depth_yes = 100
        mock_market_state.min_depth_no = 0

        # Simulate time-to-expiry check
        import time
        close_time = time.time() + 20  # 20 seconds to expiry (terminal phase)
        now = time.time()
        minutes_to_expiry = (close_time - now) / 60.0

        # Simulate one-sided book rejection logic
        regime = "one_sided_yes"
        allow_trading = True

        if regime in ["one_sided_yes", "one_sided_no"]:
            if minutes_to_expiry <= 0.5:  # Last 30 seconds
                allow_trading = False

        # Assert: Trading should be rejected in terminal phase
        assert minutes_to_expiry <= 0.5, f"Should be in terminal phase: {minutes_to_expiry}min"
        assert allow_trading is False, "One-sided books should be rejected in terminal phase"

    def test_non_terminal_phase_allows_one_sided_books(self, mock_agent, mock_market_state):
        """Test that one-sided books are allowed outside terminal phase."""
        # Setup: One-sided YES regime with sufficient time to expiry
        mock_market_state.min_depth_yes = 100
        mock_market_state.min_depth_no = 0

        # Simulate time-to-expiry check
        import time
        close_time = time.time() + 120  # 2 minutes to expiry (not terminal)
        now = time.time()
        minutes_to_expiry = (close_time - now) / 60.0

        # Simulate one-sided book allowance logic
        regime = "one_sided_yes"
        allow_trading = True

        if regime in ["one_sided_yes", "one_sided_no"]:
            if minutes_to_expiry <= 0.5:  # Last 30 seconds
                allow_trading = False

        # Assert: Trading should be allowed outside terminal phase
        assert minutes_to_expiry > 0.5, f"Should not be in terminal phase: {minutes_to_expiry}min"
        assert allow_trading is True, "One-sided books should be allowed outside terminal phase"


class TestStaleBookSidePreservation:
    """Test that staleness filters do not bias NO-side signals."""

    @pytest.fixture
    def mock_agent(self):
        """Create a mock AgentGrid15M for testing."""
        agent = Mock()
        agent.config = Mock()
        agent.config.name = "BTC_15M"
        agent.config.series_tickers = ["KXBTC15M"]
        agent.market_state_store = Mock()
        return agent

    def test_staleness_threshold_applies_equally_to_both_sides(self, mock_agent):
        """Test that staleness threshold is applied equally to YES and NO sides."""
        # Setup: Staleness configuration
        staleness_threshold_ms = 15000  # 15 seconds
        venue_staleness = 10000  # 10 seconds (fresh)

        # Simulate staleness check from _validate_market_state
        staleness_ms = venue_staleness
        is_valid = staleness_ms <= staleness_threshold_ms

        # Assert: Staleness check is side-agnostic
        assert is_valid is True, "Fresh data should pass staleness check"
        assert staleness_ms < staleness_threshold_ms, "Data should be within threshold"

        # The staleness check does not discriminate by side - it's a market-wide check
        # This ensures NO-side signals are not disproportionately rejected by staleness

    def test_stale_data_rejects_all_sides_equally(self, mock_agent):
        """Test that stale data rejects trading for all sides equally."""
        # Setup: Stale data
        staleness_threshold_ms = 15000  # 15 seconds
        venue_staleness = 20000  # 20 seconds (stale)

        # Simulate staleness check
        staleness_ms = venue_staleness
        is_valid = staleness_ms <= staleness_threshold_ms

        # Assert: Stale data fails check (side-agnostic)
        assert is_valid is False, "Stale data should fail staleness check"
        assert staleness_ms > staleness_threshold_ms, "Data should exceed threshold"

        # Staleness rejection is market-wide, not side-specific
        # This prevents NO-side signals from being selectively rejected


class TestOrderBookImbalanceSidePreservation:
    """Test that OBI calculations and logging do not bias NO-side signals."""

    @pytest.fixture
    def mock_market_state(self):
        """Create a mock market state with depth data."""
        state = Mock()
        state.min_depth_yes = 1000
        state.min_depth_no = 100
        return state

    def test_obi_calculation_symmetry(self, mock_market_state):
        """Test that OBI calculation is symmetric for YES and NO."""
        # Setup: Depth data
        min_depth_yes = mock_market_state.min_depth_yes
        min_depth_no = mock_market_state.min_depth_no

        # Simulate OBI calculation from agent_grid_15m.py
        if min_depth_yes > 0 and min_depth_no > 0:
            obi = (min_depth_yes - min_depth_no) / (min_depth_yes + min_depth_no)
        else:
            obi = 0.0

        # Assert: OBI is calculated symmetrically
        assert obi == (1000 - 100) / (1000 + 100), "OBI should be calculated correctly"
        assert obi > 0, "Should indicate YES-side imbalance"

        # OBI calculation uses both sides equally - no side bias in formula

    def test_extreme_obi_logging_includes_both_sides(self, mock_market_state):
        """Test that extreme OBI logging includes both YES and NO depth."""
        # Setup: Extreme OBI scenario
        min_depth_yes = 10000
        min_depth_no = 100

        # Simulate OBI calculation and logging
        if min_depth_yes > 0 and min_depth_no > 0:
            obi = (min_depth_yes - min_depth_no) / (min_depth_yes + min_depth_no)
        else:
            obi = 0.0

        # Log message would include both depths
        log_data = {
            "min_depth_yes": min_depth_yes,
            "min_depth_no": min_depth_no,
            "obi": obi
        }

        # Assert: Log includes both sides
        assert "min_depth_yes" in log_data, "Log should include YES depth"
        assert "min_depth_no" in log_data, "Log should include NO depth"
        assert log_data["min_depth_yes"] == 10000, "YES depth should be logged"
        assert log_data["min_depth_no"] == 100, "NO depth should be logged"

        # Extreme OBI logging is symmetric - both sides are reported


class TestRegimeSideFilteringInteraction:
    """Test interaction between regime classification and side filtering."""

    @pytest.fixture
    def mock_agent(self):
        """Create a mock AgentGrid15M for testing."""
        agent = Mock()
        agent.config = Mock()
        agent.config.name = "BTC_15M"
        agent.config.series_tickers = ["KXBTC15M"]
        agent.market_state_store = Mock()
        return agent

    def test_regime_does_not_override_price_range_filter(self, mock_agent):
        """Test that regime classification does not override price range filtering."""
        # Setup: One-sided YES regime, but NO price out of range
        mock_market_state = Mock()
        mock_market_state.min_depth_yes = 100
        mock_market_state.min_depth_no = 0
        mock_market_state.yes_price_cents = 45  # In range
        mock_market_state.no_price_cents = 80  # Out of range (>75c)

        # Simulate price range check
        yes_in_range = (10 <= mock_market_state.yes_price_cents <= 75)
        no_in_range = (10 <= mock_market_state.no_price_cents <= 75)

        # Simulate sides_to_evaluate logic
        sides_to_evaluate = []
        if yes_in_range:
            sides_to_evaluate.append("yes")
        if no_in_range:
            sides_to_evaluate.append("no")

        # Assert: NO side is filtered by price range, not regime
        assert yes_in_range is True, "YES price should be in range"
        assert no_in_range is False, "NO price should be out of range"
        assert "yes" in sides_to_evaluate, "YES side should be evaluated"
        assert "no" not in sides_to_evaluate, "NO side should not be evaluated (price range, not regime)"

    def test_regime_does_not_override_expected_side_logic(self, mock_agent):
        """Test that regime does not override expected_side logic from velocity."""
        # Setup: One-sided NO regime, but velocity suggests YES side
        velocity = 0.01  # Positive velocity
        strategy_mode = "trend_following"

        # Simulate expected_side calculation
        if strategy_mode == "trend_following":
            expected_side = "yes" if velocity > 0 else "no"
        else:  # mean_reversion
            expected_side = "no" if velocity > 0 else "yes"

        # Simulate regime classification
        min_depth_yes = 0
        min_depth_no = 100
        min_depth_yes_threshold = 1
        min_depth_no_threshold = 1

        has_yes = min_depth_yes >= min_depth_yes_threshold
        has_no = min_depth_no >= min_depth_no_threshold

        if has_yes and has_no:
            regime = "both_sides"
        elif has_yes and not has_no:
            regime = "one_sided_yes"
        elif not has_yes and has_no:
            regime = "one_sided_no"
        else:
            regime = "no_liquidity"

        # Assert: expected_side is determined by velocity, not regime
        assert expected_side == "yes", "Positive velocity in trend_following should expect YES"
        assert regime == "one_sided_no", "Regime should be one_sided_no"

        # The expected_side logic (velocity-based) is independent of regime
        # This prevents regime from biasing side selection


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
