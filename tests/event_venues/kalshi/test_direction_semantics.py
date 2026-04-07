"""Unit tests for Kalshi direction semantics module."""

import pytest
from merid.event_venues.kalshi.direction_semantics import (
    kalshi_is_yes_winner,
    parse_kalshi_crypto_direction,
    determine_kalshi_side,
    get_strike_from_market,
)


class TestKalshiIsYesWinner:
    """Tests for settlement logic per Kalshi's official specification."""

    def test_up_market_yes_wins_at_strike(self):
        """UP market: YES wins when RTI equals strike."""
        assert kalshi_is_yes_winner(50000.0, 50000.0, "up") is True

    def test_up_market_yes_wins_above_strike(self):
        """UP market: YES wins when RTI is above strike."""
        assert kalshi_is_yes_winner(50100.0, 50000.0, "up") is True

    def test_up_market_no_wins_below_strike(self):
        """UP market: NO wins when RTI is below strike."""
        assert kalshi_is_yes_winner(49900.0, 50000.0, "up") is False

    def test_down_market_yes_wins_below_strike(self):
        """DOWN market: YES wins when RTI is below strike."""
        assert kalshi_is_yes_winner(49900.0, 50000.0, "down") is True

    def test_down_market_no_wins_at_strike(self):
        """DOWN market: NO wins when RTI equals strike."""
        assert kalshi_is_yes_winner(50000.0, 50000.0, "down") is False

    def test_down_market_no_wins_above_strike(self):
        """DOWN market: NO wins when RTI is above strike."""
        assert kalshi_is_yes_winner(50100.0, 50000.0, "down") is False

    def test_invalid_direction_raises(self):
        """Invalid direction should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid direction"):
            kalshi_is_yes_winner(50000.0, 50000.0, "sideways")

    def test_case_insensitive(self):
        """Direction should be case-insensitive."""
        assert kalshi_is_yes_winner(50100.0, 50000.0, "UP") is True
        assert kalshi_is_yes_winner(49900.0, 50000.0, "DOWN") is True


class TestParseKalshiCryptoDirection:
    """Tests for direction parsing from market metadata."""

    def test_explicit_up_in_title(self):
        """Explicit 'up' in title should return 'up'."""
        direction = parse_kalshi_crypto_direction(
            "KXBTC15M-25DEC262200",
            "Bitcoin price up?"
        )
        assert direction == "up"

    def test_explicit_down_in_title(self):
        """Explicit 'down' in title should return 'down'."""
        direction = parse_kalshi_crypto_direction(
            "KXBTC15M-25DEC262200",
            "Bitcoin price down?"
        )
        assert direction == "down"

    def test_above_implies_up(self):
        """'above' language should imply 'up'."""
        direction = parse_kalshi_crypto_direction(
            "KXBTC15M-25DEC262200",
            "Bitcoin price at or above $50,000?"
        )
        assert direction == "up"

    def test_below_implies_down(self):
        """'below' language should imply 'down'."""
        direction = parse_kalshi_crypto_direction(
            "KXBTC15M-25DEC262200",
            "Bitcoin price below $50,000?"
        )
        assert direction == "down"

    def test_over_implies_up(self):
        """'over' language should imply 'up'."""
        direction = parse_kalshi_crypto_direction(
            "KXBTC15M-25DEC262200",
            "Bitcoin price over $50,000?"
        )
        assert direction == "up"

    def test_under_implies_down(self):
        """'under' language should imply 'down'."""
        direction = parse_kalshi_crypto_direction(
            "KXBTC15M-25DEC262200",
            "Bitcoin price under $50,000?"
        )
        assert direction == "down"

    def test_no_clear_direction_returns_none(self):
        """Markets without clear direction should return None."""
        direction = parse_kalshi_crypto_direction(
            "KXBTC15M-25DEC262200",
            "Bitcoin event happens?"
        )
        assert direction is None

    def test_case_insensitive_parsing(self):
        """Direction parsing should be case-insensitive."""
        direction = parse_kalshi_crypto_direction(
            "KXBTC15M-25DEC262200",
            "Bitcoin price ABOVE $50,000?"
        )
        assert direction == "up"


class TestDetermineKalshiSide:
    """Tests for forecast-to-side conversion logic."""

    def test_bullish_up_market_yes(self):
        """Bullish forecast + up market → YES."""
        assert determine_kalshi_side("bullish", "up") == "yes"

    def test_bullish_down_market_no(self):
        """Bullish forecast + down market → NO."""
        assert determine_kalshi_side("bullish", "down") == "no"

    def test_bearish_up_market_no(self):
        """Bearish forecast + up market → NO."""
        assert determine_kalshi_side("bearish", "up") == "no"

    def test_bearish_down_market_yes(self):
        """Bearish forecast + down market → YES."""
        assert determine_kalshi_side("bearish", "down") == "yes"

    def test_invalid_forecast_raises(self):
        """Invalid forecast direction should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid forecast_direction"):
            determine_kalshi_side("neutral", "up")

    def test_invalid_market_direction_raises(self):
        """Invalid market direction should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid market_direction"):
            determine_kalshi_side("bullish", "sideways")

    def test_case_insensitive_forecast(self):
        """Forecast direction should be case-insensitive."""
        assert determine_kalshi_side("BULLISH", "up") == "yes"
        assert determine_kalshi_side("BEARISH", "down") == "yes"

    def test_case_insensitive_market(self):
        """Market direction should be case-insensitive."""
        assert determine_kalshi_side("bullish", "UP") == "yes"
        assert determine_kalshi_side("bearish", "DOWN") == "yes"


class TestGetStrikeFromMarket:
    """Tests for strike price extraction from market objects."""

    def test_dict_with_strike_price(self):
        """Extract strike from dict with 'strike_price' key."""
        market = {"strike_price": 50000.0}
        assert get_strike_from_market(market) == 50000.0

    def test_dict_with_strike(self):
        """Extract strike from dict with 'strike' key."""
        market = {"strike": 50000.0}
        assert get_strike_from_market(market) == 50000.0

    def test_object_with_strike_price_attr(self):
        """Extract strike from object with strike_price attribute."""
        class MockMarket:
            strike_price = 50000.0

        assert get_strike_from_market(MockMarket()) == 50000.0

    def test_object_with_strike_attr(self):
        """Extract strike from object with strike attribute."""
        class MockMarket:
            strike = 50000.0

        assert get_strike_from_market(MockMarket()) == 50000.0

    def test_no_strike_returns_none(self):
        """Market without strike should return None."""
        market = {"other_field": 123}
        assert get_strike_from_market(market) is None

    def test_zero_strike_returns_none(self):
        """Zero strike should return None (invalid)."""
        market = {"strike_price": 0.0}
        assert get_strike_from_market(market) is None

    def test_negative_strike_returns_none(self):
        """Negative strike should return None (invalid)."""
        market = {"strike_price": -50000.0}
        assert get_strike_from_market(market) is None

    def test_invalid_strike_type_returns_none(self):
        """Non-numeric strike should return None."""
        market = {"strike_price": "invalid"}
        assert get_strike_from_market(market) is None


class TestMultiAssetScenarios:
    """End-to-end scenarios across all 5 crypto assets."""

    @pytest.mark.parametrize("asset,strike", [
        ("BTC", 50000.0),
        ("ETH", 3000.0),
        ("SOL", 150.0),
        ("XRP", 2.0),
        ("DOGE", 0.15),
    ])
    def test_up_market_settlement_scenarios(self, asset, strike):
        """Test up market settlement for all assets."""
        # Settlement above strike → YES wins
        assert kalshi_is_yes_winner(strike + 10, strike, "up") is True

        # Settlement at strike → YES wins (≥ condition)
        assert kalshi_is_yes_winner(strike, strike, "up") is True

        # Settlement below strike → NO wins
        assert kalshi_is_yes_winner(strike - 10, strike, "up") is False

    @pytest.mark.parametrize("asset,strike", [
        ("BTC", 50000.0),
        ("ETH", 3000.0),
        ("SOL", 150.0),
        ("XRP", 2.0),
        ("DOGE", 0.15),
    ])
    def test_down_market_settlement_scenarios(self, asset, strike):
        """Test down market settlement for all assets."""
        # Settlement below strike → YES wins
        assert kalshi_is_yes_winner(strike - 10, strike, "down") is True

        # Settlement at strike → NO wins (< condition, not ≤)
        assert kalshi_is_yes_winner(strike, strike, "down") is False

        # Settlement above strike → NO wins
        assert kalshi_is_yes_winner(strike + 10, strike, "down") is False
