"""Integration tests for the Kalshi market filter pipeline.

Focus: distance (spot-band) filtering and dead-zone filtering.

The CT disables the dead-zone filter (min_edge_dead_zone_pct=0.0).  Markets
whose mid-price is near 50¢ must pass through when the dead-zone filter is
off.  Markets without strike/spot price data always pass the distance check
since distance_from_spot_pct returns None in that case.
"""

from __future__ import annotations

from merid.event_venues.kalshi.market_filter import (
    MarketCandidate,
    MarketFilter,
    MarketFilterConfig,
)

# A representative ticker used across tests
_TICKER = "KXETHQ-26APR0316-T1211.99"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_market_no_price_data(
    ticker: str = _TICKER,
    underlying: str = "ETH",
    timeframe: str = "1h",
    mid_price_cents: int = 55,
) -> MarketCandidate:
    """Return a MarketCandidate without strike/spot price data.

    When strike_price or spot_price is absent, distance_from_spot_pct
    returns None and the distance filter is automatically skipped.
    """
    return MarketCandidate(
        ticker=ticker,
        underlying=underlying,
        timeframe=timeframe,
        volume=1000,
        open_interest=500,
        best_bid_cents=50,
        best_ask_cents=60,
        mid_price_cents=mid_price_cents,
        # No strike_price / spot_price → distance check skipped
    )


def _make_near_50_market(
    ticker: str = _TICKER,
    underlying: str = "ETH",
    timeframe: str = "1h",
) -> MarketCandidate:
    """Return a MarketCandidate whose mid is exactly 50¢ (dead-zone centre)."""
    return MarketCandidate(
        ticker=ticker,
        underlying=underlying,
        timeframe=timeframe,
        volume=1000,
        open_interest=500,
        best_bid_cents=48,
        best_ask_cents=52,
        mid_price_cents=50,
    )


def _make_within_spot_band_market(
    ticker: str = _TICKER,
    underlying: str = "ETH",
    timeframe: str = "1h",
    spot_price: float = 1212.0,
    distance_pct: float = 5.0,   # 5% from spot — within 30% ETH-1h band
) -> MarketCandidate:
    """Return a MarketCandidate with strike close to spot."""
    strike = spot_price * (1 + distance_pct / 100.0)
    return MarketCandidate(
        ticker=ticker,
        underlying=underlying,
        timeframe=timeframe,
        volume=1000,
        open_interest=500,
        best_bid_cents=40,
        best_ask_cents=60,
        mid_price_cents=50,
        strike_price=strike,
        spot_price=spot_price,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestDistanceFilteringDisabled:
    """Markets without strike/spot data always pass the distance check."""

    def test_ticker_passes_when_distance_filter_disabled(self):
        """Ticker passes through when no strike/spot data — distance check skipped."""
        cfg = MarketFilterConfig(
            spot_band_pct=0.0,            # disable config-level distance filter
            min_edge_dead_zone_pct=0.0,   # disable dead-zone filter
            min_volume=0,
            min_open_interest=0,
            max_spread_cents=100,
        )
        filt = MarketFilter(cfg)
        # Market has no strike/spot data → distance_from_spot_pct is None
        market = _make_market_no_price_data()
        result = filt.filter_markets([market])
        tickers = [c.ticker for c in result.candidates]
        # Ticker MUST be present — distance check skipped (no price data)
        assert _TICKER in tickers, (
            f"Expected {_TICKER!r} to pass filter pipeline when distance data "
            "is absent (distance check is skipped), but it was rejected."
        )

    def test_ticker_passes_with_strike_within_band(self):
        """Ticker with strike within spot band also passes."""
        cfg = MarketFilterConfig(
            min_edge_dead_zone_pct=0.0,
            min_volume=0,
            min_open_interest=0,
            max_spread_cents=100,
        )
        filt = MarketFilter(cfg)
        market = _make_within_spot_band_market()
        result = filt.filter_markets([market])
        tickers = [c.ticker for c in result.candidates]
        assert _TICKER in tickers, (
            "Market with strike within 30% of spot should pass ETH-1h spot-band filter."
        )


class TestDeadZoneFilteringDisabled:
    """With min_edge_dead_zone_pct=0.0, near-50¢ markets must pass through."""

    def test_ticker_passes_when_dead_zone_disabled(self):
        """Near-50¢ ticker passes through when dead-zone filter is disabled."""
        cfg = MarketFilterConfig(
            spot_band_pct=0.0,
            min_edge_dead_zone_pct=0.0,   # dead-zone disabled
            min_volume=0,
            min_open_interest=0,
            max_spread_cents=100,
        )
        filt = MarketFilter(cfg)
        market = _make_near_50_market()
        result = filt.filter_markets([market])
        tickers = [c.ticker for c in result.candidates]
        assert _TICKER in tickers, (
            f"Expected {_TICKER!r} to pass when dead-zone filtering is disabled."
        )

    def test_ticker_blocked_when_dead_zone_enabled(self):
        """Near-50¢ ticker is rejected when dead-zone filter is active."""
        cfg = MarketFilterConfig(
            spot_band_pct=0.0,
            min_edge_dead_zone_pct=5.0,   # 5¢ dead zone — mid=50 falls inside
            min_volume=0,
            min_open_interest=0,
            max_spread_cents=100,
        )
        filt = MarketFilter(cfg)
        market = _make_near_50_market()
        result = filt.filter_markets([market])
        tickers = [c.ticker for c in result.candidates]
        assert _TICKER not in tickers, (
            f"Expected {_TICKER!r} to be rejected by dead-zone filter."
        )


class TestFilterPipelineIntegration:
    """End-to-end filter pipeline with mixed market batch."""

    def test_only_passing_markets_survive(self):
        """Markets that fail any active filter gate should not appear in output."""
        cfg = MarketFilterConfig(
            spot_band_pct=0.0,
            min_edge_dead_zone_pct=0.0,
            min_volume=100,
            min_open_interest=0,
            max_spread_cents=100,
        )
        filt = MarketFilter(cfg)
        low_volume = MarketCandidate(
            ticker="LOW-VOL",
            underlying="ETH",
            timeframe="1h",
            volume=10,           # below min_volume=100
            open_interest=50,
            best_bid_cents=40,
            best_ask_cents=60,
            mid_price_cents=55,
        )
        high_volume = MarketCandidate(
            ticker="HIGH-VOL",
            underlying="ETH",
            timeframe="1h",
            volume=500,
            open_interest=200,
            best_bid_cents=40,
            best_ask_cents=60,
            mid_price_cents=55,
        )
        result = filt.filter_markets([low_volume, high_volume])
        tickers = [c.ticker for c in result.candidates]
        assert "LOW-VOL" not in tickers
        assert "HIGH-VOL" in tickers

