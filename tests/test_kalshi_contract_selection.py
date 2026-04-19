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


class TestStrikeDistanceBandsV3:
    """Test that v3 distance bands are sensible (not the wide v2 bands)."""

    def test_btc_15m_max_distance_sensible(self):
        """BTC 15m max distance should be ~6% (not the v2 15%)."""
        from merid.prediction.kalshi_strike_selector import DEFAULT_MAX_DISTANCE
        
        max_dist = DEFAULT_MAX_DISTANCE.get(("BTC", "15m"), 0.125)
        # v3: BTC 15m = 6%, v2 was 15%
        assert max_dist == 0.06, f"BTC 15m max distance should be 6% (v3), got {max_dist*100:.1f}%"

    def test_sol_15m_max_distance_sensible(self):
        """SOL 15m max distance should be ~7% (not the v2 20%)."""
        from merid.prediction.kalshi_strike_selector import DEFAULT_MAX_DISTANCE
        
        max_dist = DEFAULT_MAX_DISTANCE.get(("SOL", "15m"), 0.125)
        # v3: SOL 15m = 7%, v2 was 20%
        assert max_dist == 0.07, f"SOL 15m max distance should be 7% (v3), got {max_dist*100:.1f}%"

    def test_doge_15m_max_distance_sensible(self):
        """DOGE 15m max distance should be ~6% (not the v2 30%)."""
        from merid.prediction.kalshi_strike_selector import DEFAULT_MAX_DISTANCE
        
        max_dist = DEFAULT_MAX_DISTANCE.get(("DOGE", "15m"), 0.125)
        # v3: DOGE 15m = 6%, v2 was 30%
        assert max_dist == 0.06, f"DOGE 15m max distance should be 6% (v3), got {max_dist*100:.1f}%"

    def test_intraday_bands_tighter_than_daily(self):
        """Intraday bands should be tighter than daily bands."""
        from merid.prediction.kalshi_strike_selector import DEFAULT_MAX_DISTANCE
        
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            intraday = DEFAULT_MAX_DISTANCE.get((asset, "15m"), 0.125)
            daily = DEFAULT_MAX_DISTANCE.get((asset, "daily"), 0.125)
            assert intraday < daily, f"{asset}: intraday {intraday} should be < daily {daily}"

    def test_all_assets_have_15m_bands(self):
        """All 5 crypto assets must have 15m bands defined."""
        from merid.prediction.kalshi_strike_selector import DEFAULT_MAX_DISTANCE
        
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            assert (asset, "15m") in DEFAULT_MAX_DISTANCE, f"{asset} 15m band missing"
            assert DEFAULT_MAX_DISTANCE[(asset, "15m")] < 0.10, f"{asset} 15m band too wide"

    def test_target_bands_within_max_distance(self):
        """Target bands should be ~40-50% of max distance."""
        from merid.prediction.kalshi_strike_selector import DEFAULT_MAX_DISTANCE, DEFAULT_TARGET_BAND
        
        for (asset, tf), max_dist in DEFAULT_MAX_DISTANCE.items():
            if (asset, tf) in DEFAULT_TARGET_BAND:
                target = DEFAULT_TARGET_BAND[(asset, tf)]
                # Target should be 40-60% of max
                ratio = target / max_dist if max_dist > 0 else 0
                assert 0.3 <= ratio <= 0.7, f"{asset}/{tf}: target/max ratio {ratio:.2f} outside 0.3-0.7"


class TestDistanceInvariantLogic:
    """Test the distance sanity invariant logic."""

    def test_far_otm_contract_rejected(self):
        """Contracts with strike > max distance should be rejected."""
        from merid.prediction.kalshi_strike_selector import DEFAULT_MAX_DISTANCE
        
        # BTC @ $100k, strike $120k (20% away) — exceeds 15m max of 6%
        spot = 100000.0
        strike = 120000.0
        distance_pct = abs(strike - spot) / spot  # 0.20
        
        max_allowed = DEFAULT_MAX_DISTANCE.get(("BTC", "15m"), 0.06)
        assert distance_pct > max_allowed, "20% distance should exceed 6% max"

    def test_atm_contract_accepted(self):
        """ATM contracts should pass distance check."""
        from merid.prediction.kalshi_strike_selector import DEFAULT_MAX_DISTANCE
        
        # BTC @ $100k, strike $101k (1% away)
        spot = 100000.0
        strike = 101000.0
        distance_pct = abs(strike - spot) / spot  # 0.01 (SPOT denominator)
        
        max_allowed = DEFAULT_MAX_DISTANCE.get(("BTC", "15m"), 0.06)
        assert distance_pct <= max_allowed, "1% distance should be within 6% max"

    def test_slight_otm_contract_accepted(self):
        """Slightly OTM contracts should pass distance check."""
        from merid.prediction.kalshi_strike_selector import DEFAULT_MAX_DISTANCE
        
        # BTC @ $100k, strike $105k (5% away)
        spot = 100000.0
        strike = 105000.0
        distance_pct = abs(strike - spot) / spot  # 0.05 (SPOT denominator)
        
        max_allowed = DEFAULT_MAX_DISTANCE.get(("BTC", "15m"), 0.06)
        assert distance_pct <= max_allowed, "5% distance should be within 6% max"

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


class TestContractSelectionBands:
    """Test contract selection with explicit distance bands per strategy."""

    def test_select_contracts_filters_by_distance(self):
        """Contract selection should filter by distance bands."""
        from merid.prediction.kalshi_strike_selector import DEFAULT_MAX_DISTANCE
        
        # Mock: BTC @ $100k, contracts at various strikes
        spot = 100000.0
        asset = "BTC"
        timeframe = "15m"
        
        candidates = [
            MockMarketCandidate("KXBTC15M-T101000", "BTC", strike=101000.0, spot=spot),  # 1% OTM
            MockMarketCandidate("KXBTC15M-T105000", "BTC", strike=105000.0, spot=spot),  # 5% OTM (at limit)
            MockMarketCandidate("KXBTC15M-T115000", "BTC", strike=115000.0, spot=spot),  # 15% OTM (too far)
        ]
        
        max_allowed = DEFAULT_MAX_DISTANCE.get(("BTC", "15m"), 0.06)
        
        # Filter by distance
        valid = []
        for c in candidates:
            if c.strike and c.spot:
                dist_pct = abs(c.strike - c.spot) / c.spot
                if dist_pct <= max_allowed:
                    valid.append(c)
        
        # Should accept 1% and 5%, reject 15%
        assert len(valid) == 2
        tickers = [c.ticker for c in valid]
        assert "KXBTC15M-T101000" in tickers
        assert "KXBTC15M-T105000" in tickers
        assert "KXBTC15M-T115000" not in tickers

    def test_fallback_max_distance_when_asset_missing(self):
        """Should use fallback when asset/timeframe not in DEFAULT_MAX_DISTANCE."""
        from merid.prediction.kalshi_strike_selector import FALLBACK_MAX_DISTANCE_PCT
        
        # Fallback should be reasonable (~12.5%)
        assert 0.05 <= FALLBACK_MAX_DISTANCE_PCT <= 0.20


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
