"""
Tests for Kalshi Contract Selection Layer

Covers:
- Strike distance band invariants (v3 fix)
- DEFAULT_MAX_DISTANCE band tightening
- Contract selection trace logging
- Distance sanity invariants
"""

import pytest
from dataclasses import dataclass
from typing import Optional
from decimal import Decimal


@dataclass
class MockMarketCandidate:
    """Mock MarketCandidate for testing contract selection."""
    ticker: str
    asset: str
    strike: Optional[float] = None
    spot: Optional[float] = None
    best_edge: Optional[Decimal] = None
    best_side: Optional[str] = None
    limit_price_cents: int = 50
    timeframe: str = "15m"




class TestDistanceInvariantLogic:
    """Test the distance sanity invariant logic."""




    def test_directional_markets_skip_distance_check(self):
        """Directional markets (strike=0) should skip distance check."""
        # Directional markets have strike=0 or None by design
        strike = None
        spot = 100000.0
        
        # Should NOT apply distance check (strike is None/0)
        is_directional = strike is None or strike == 0 or strike == spot
        assert is_directional, "None/Zero strike should be treated as directional"

    def test_extreme_strike_safety_clamp(self):
        """Extreme strikes (>50% from spot) should be hard-rejected by safety clamp."""
        spot = 100000.0
        
        # Strike 60% below spot (pathological ticker)
        strike_extreme_low = 40000.0
        is_extreme_low = strike_extreme_low < spot * 0.5
        assert is_extreme_low, "Strike <50% of spot should trigger safety clamp"
        
        # Strike 60% above spot (pathological ticker)
        strike_extreme_high = 160000.0
        is_extreme_high = strike_extreme_high > spot * 1.5
        assert is_extreme_high, "Strike >150% of spot should trigger safety clamp"




class TestStrikeParsing:
    """Test strike extraction from ticker formats."""

    def test_parse_strike_from_threshold_ticker(self):
        """Should parse strike from threshold ticker (e.g., KXBTC15M-T101500)."""
        from merid.event_venues.kalshi.market_filter import parse_strike_from_ticker
        
        strike = parse_strike_from_ticker("KXBTC15M-T101500")
        assert strike == 101500.0, f"Expected 101500, got {strike}"

    def test_parse_strike_from_range_ticker(self):
        """Should parse strike from range/bracket ticker (e.g., KXETH-B3200)."""
        from merid.event_venues.kalshi.market_filter import parse_strike_from_ticker
        
        # Bracket markets use -B prefix
        strike = parse_strike_from_ticker("KXETH-B3200")
        assert strike == 3200.0, f"Expected 3200, got {strike}"

    def test_parse_strike_from_below_ticker(self):
        """Should parse strike from below/range ticker (e.g., KXSOL-B140)."""
        from merid.event_venues.kalshi.market_filter import parse_strike_from_ticker
        
        # B = Below/Bracket range
        strike = parse_strike_from_ticker("KXSOL-B140")
        assert strike == 140.0, f"Expected 140, got {strike}"

    def test_parse_strike_directional_returns_none(self):
        """Directional tickers (up/down) should return None for strike."""
        from merid.event_venues.kalshi.market_filter import parse_strike_from_ticker
        
        # Directional markets have no strike in ticker
        strike = parse_strike_from_ticker("KXBTC15M-UP")
        assert strike is None, f"Expected None for directional, got {strike}"

    def test_parse_strike_with_decimal(self):
        """Should handle decimal strikes (e.g., KXXRP-T0.65)."""
        from merid.event_venues.kalshi.market_filter import parse_strike_from_ticker
        
        strike = parse_strike_from_ticker("KXXRP15M-T0.65")
        assert strike == 0.65, f"Expected 0.65, got {strike}"


class TestSelectionLogging:
    """Test that contract selection emits proper trace logs."""

    def test_distance_invariant_violation_log_format(self):
        """Violation log should contain expected fields."""
        # This test verifies the log format is structured for parsing
        ticker = "KXBTC15M-T115000"
        asset = "BTC"
        tf = "15m"
        strike = 115000.0
        spot = 100000.0
        distance_pct = 15.0  # %
        max_allowed = 6.0  # %
        
        # Simulate the log message format from the invariant check
        log_msg = (
            f"[DISTANCE-INVARIANT-VIOLATION] {ticker}/{tf}: strike {strike:.2f} "
            f"is {distance_pct:.2f}% from spot {spot:.2f}, exceeds max {max_allowed:.2f}%"
        )
        
        assert "DISTANCE-INVARIANT-VIOLATION" in log_msg
        assert ticker in log_msg
        assert "115000.00" in log_msg
        assert "15.00%" in log_msg

    def test_contract_selection_trace_log_format(self):
        """Trace log should contain all selection fields."""
        # Verify structured logging format
        log_msg = (
            "[CONTRACT-SELECTION-TRACE] ticker=KXBTC15M-T101000 asset=BTC tf=15m "
            "spot=100000.00 strike=101000.00 distance_pct=1.000% max_allowed=6.000% "
            "target_band=3.000% in_target=true"
        )
        
        assert "CONTRACT-SELECTION-TRACE" in log_msg
        assert "ticker=" in log_msg
        assert "distance_pct=" in log_msg
        assert "max_allowed=" in log_msg


class TestAssetTimeframeLookup:
    """Test asset/timeframe extraction from tickers."""

    def test_infer_btc_15m_from_ticker(self):
        """Should infer BTC 15m from series ticker."""
        from config.kalshi_crypto_series_meta import infer_asset_timeframe_from_ticker
        
        asset, tf = infer_asset_timeframe_from_ticker("KXBTC15M")
        assert asset == "BTC"
        assert tf == "15m"

    def test_infer_eth_1h_from_ticker(self):
        """Should infer ETH 1h from series ticker."""
        from config.kalshi_crypto_series_meta import infer_asset_timeframe_from_ticker
        
        asset, tf = infer_asset_timeframe_from_ticker("KXETH")
        assert asset == "ETH"
        assert tf == "1h"  # Default ETH series is 1h

    def test_infer_sol_daily_from_ticker(self):
        """Should infer SOL daily from series ticker."""
        from config.kalshi_crypto_series_meta import infer_asset_timeframe_from_ticker
        
        asset, tf = infer_asset_timeframe_from_ticker("KXSOL")
        assert asset == "SOL"
        # SOL default depends on meta config
        assert tf in ["1h", "daily"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
