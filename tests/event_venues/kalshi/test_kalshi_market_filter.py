"""Tests for Kalshi Market Selection Filter."""

import time

import pytest

from merid.event_venues.kalshi.market_filter import (
    DEFAULT_FILTER_CONFIG,
    MarketCandidate,
    MarketFilter,
    MarketFilterConfig,
    OverlapGroup,
    FilterResult,
)


# ── Helpers ────────────────────────────────────────────────────────────

def _market(
    ticker: str = "KXBTC-H-55-60",
    underlying: str = "BTC",
    timeframe: str = "hourly",
    volume: int = 100,
    oi: int = 50,
    bid: int = 60,
    ask: int = 65,
    expiry_ts: float = 0.0,
) -> MarketCandidate:
    return MarketCandidate(
        ticker=ticker,
        underlying=underlying,
        timeframe=timeframe,
        volume=volume,
        open_interest=oi,
        best_bid_cents=bid,
        best_ask_cents=ask,
        spread_cents=ask - bid if bid > 0 and ask > 0 else 0,
        mid_price_cents=(bid + ask) // 2 if bid > 0 and ask > 0 else 0,
        expiry_ts=expiry_ts,
    )


# ── MarketCandidate ──────────────────────────────────────────────────

class TestMarketCandidate:
    def test_has_book(self):
        m = _market(bid=50, ask=55)
        assert m.has_book is True

    def test_no_book(self):
        m = _market(bid=0, ask=0)
        assert m.has_book is False

    def test_to_dict(self):
        m = _market()
        d = m.to_dict()
        assert d["ticker"] == "KXBTC-H-55-60"
        assert "volume" in d


# ── Evaluate single market ───────────────────────────────────────────

class TestEvaluate:
    def test_good_market_passes(self):
        filt = MarketFilter()
        m = _market(volume=100, oi=50, bid=60, ask=65)  # mid=62, outside dead zone
        passed, reason = filt.evaluate(m)
        assert passed is True

    def test_low_volume_rejected(self):
        filt = MarketFilter()
        m = _market(volume=5)
        passed, reason = filt.evaluate(m)
        assert not passed
        assert "volume" in reason

    def test_low_oi_rejected(self):
        filt = MarketFilter()
        m = _market(oi=2)
        passed, reason = filt.evaluate(m)
        assert not passed
        assert "OI" in reason

    def test_wide_spread_rejected(self):
        cfg = MarketFilterConfig(max_spread_cents=5)
        filt = MarketFilter(cfg)
        m = _market(bid=40, ask=55)  # 15c spread
        passed, reason = filt.evaluate(m)
        assert not passed
        assert "spread" in reason

    def test_price_too_low_rejected(self):
        cfg = MarketFilterConfig(min_price_cents=15)
        filt = MarketFilter(cfg)
        m = _market(bid=5, ask=10)  # mid=7
        passed, reason = filt.evaluate(m)
        assert not passed
        assert "price" in reason

    def test_price_too_high_rejected(self):
        cfg = MarketFilterConfig(max_price_cents=85)
        filt = MarketFilter(cfg)
        m = _market(bid=90, ask=95)  # mid=92
        passed, reason = filt.evaluate(m)
        assert not passed
        assert "price" in reason

    def test_disallowed_underlying_rejected(self):
        cfg = MarketFilterConfig(allowed_underlyings=["BTC", "ETH"])
        filt = MarketFilter(cfg)
        m = _market(underlying="DOGE")
        passed, reason = filt.evaluate(m)
        assert not passed
        assert "underlying" in reason

    def test_disallowed_timeframe_rejected(self):
        cfg = MarketFilterConfig(allowed_timeframes=["hourly"])
        filt = MarketFilter(cfg)
        m = _market(timeframe="daily")
        passed, reason = filt.evaluate(m)
        assert not passed
        assert "timeframe" in reason


# ── Filter markets ───────────────────────────────────────────────────

class TestFilterMarkets:
    def test_empty_input(self):
        filt = MarketFilter()
        result = filt.filter_markets([])
        assert result.total_input == 0
        assert result.passed == 0

    def test_mixed_pass_fail(self):
        filt = MarketFilter()
        markets = [
            _market(ticker="good1", volume=100, oi=50),
            _market(ticker="low_vol", volume=1, oi=50),
            _market(ticker="good2", volume=200, oi=30),
        ]
        result = filt.filter_markets(markets)
        assert result.total_input == 3
        assert result.passed == 2
        assert result.rejected_volume == 1

    def test_result_to_dict(self):
        filt = MarketFilter()
        result = filt.filter_markets([_market()])
        d = result.to_dict()
        assert "total_input" in d
        assert "candidates" in d


# ── Overlap groups ───────────────────────────────────────────────────

class TestOverlapGroups:
    def test_same_hour_grouped(self):
        filt = MarketFilter(MarketFilterConfig(overlap_window_seconds=3600))
        now = time.time()
        markets = [
            _market(ticker="BTC-H1", underlying="BTC", expiry_ts=now),
            _market(ticker="BTC-H2", underlying="BTC", expiry_ts=now + 1800),
        ]
        groups = filt.group_overlapping(markets)
        assert len(groups) == 1
        assert len(groups[0].markets) == 2

    def test_different_hours_separate(self):
        filt = MarketFilter(MarketFilterConfig(overlap_window_seconds=3600))
        now = time.time()
        markets = [
            _market(ticker="BTC-H1", underlying="BTC", expiry_ts=now),
            _market(ticker="BTC-H2", underlying="BTC", expiry_ts=now + 7200),
        ]
        groups = filt.group_overlapping(markets)
        assert len(groups) == 2

    def test_different_underlyings_separate(self):
        filt = MarketFilter()
        now = time.time()
        markets = [
            _market(ticker="BTC-H1", underlying="BTC", expiry_ts=now),
            _market(ticker="ETH-H1", underlying="ETH", expiry_ts=now),
        ]
        groups = filt.group_overlapping(markets)
        assert len(groups) == 2

    def test_combined_volume(self):
        filt = MarketFilter()
        now = time.time()
        markets = [
            _market(ticker="BTC-H1", underlying="BTC", volume=100, oi=50, expiry_ts=now),
            _market(ticker="BTC-H2", underlying="BTC", volume=200, oi=30, expiry_ts=now + 900),
        ]
        groups = filt.group_overlapping(markets)
        assert groups[0].combined_volume == 300
        assert groups[0].combined_oi == 80

    def test_empty_input(self):
        filt = MarketFilter()
        groups = filt.group_overlapping([])
        assert len(groups) == 0

    def test_overlap_group_to_dict(self):
        g = OverlapGroup(underlying="BTC")
        g.markets.append(_market(ticker="BTC-H1"))
        d = g.to_dict()
        assert d["underlying"] == "BTC"
        assert d["market_count"] == 1


# ── Summary ──────────────────────────────────────────────────────────

class TestSummary:
    def test_summary_structure(self):
        filt = MarketFilter()
        markets = [_market(volume=100, oi=50), _market(volume=5)]
        s = filt.summary(markets)
        assert "filter" in s
        assert "overlap_groups" in s
        assert s["filter"]["total_input"] == 2


# ── Spot band / distance filter ──────────────────────────────────────

class TestSpotBandFilter:
    def test_within_band_passes(self):
        """Market whose strike is within spot_band_pct passes."""
        cfg = MarketFilterConfig(spot_band_pct=12.5)
        filt = MarketFilter(cfg)
        m = _market()
        m.strike_price = 95000.0
        m.spot_price = 100000.0  # 5% away — within ±12.5%
        passed, reason = filt.evaluate(m)
        assert passed is True

    def test_outside_band_rejected(self):
        """Market whose strike is beyond spot_band_pct is rejected."""
        cfg = MarketFilterConfig(spot_band_pct=12.5)
        filt = MarketFilter(cfg)
        m = _market()
        m.strike_price = 80000.0
        m.spot_price = 100000.0  # 20% away — outside ±12.5%
        passed, reason = filt.evaluate(m)
        assert passed is False
        assert "distance" in reason

    def test_missing_spot_skips_distance_check(self):
        """If spot_price is absent the distance check is not applied."""
        cfg = MarketFilterConfig(spot_band_pct=12.5)
        filt = MarketFilter(cfg)
        m = _market()
        m.strike_price = 50000.0
        m.spot_price = None  # no spot available
        passed, reason = filt.evaluate(m)
        assert passed is True

    def test_distance_filter_disabled_when_zero(self):
        """spot_band_pct=0 disables the distance check."""
        cfg = MarketFilterConfig(spot_band_pct=0.0)
        filt = MarketFilter(cfg)
        m = _market()
        m.strike_price = 1000.0
        m.spot_price = 100000.0  # far away — but filter is disabled
        passed, reason = filt.evaluate(m)
        assert passed is True

    def test_distance_from_spot_pct_property(self):
        """distance_from_spot_pct returns correct percentage."""
        m = _market()
        m.strike_price = 105000.0
        m.spot_price = 100000.0
        assert m.distance_from_spot_pct == pytest.approx(5.0)

    def test_distance_property_none_without_spot(self):
        m = _market()
        m.strike_price = 95000.0
        m.spot_price = None
        assert m.distance_from_spot_pct is None


# ── Edge dead-zone filter ────────────────────────────────────────────

class TestEdgeDeadZone:
    def test_coin_flip_market_rejected(self):
        """Market with mid in [47¢, 53¢] is skipped."""
        cfg = MarketFilterConfig(min_edge_dead_zone_pct=3.0)
        filt = MarketFilter(cfg)
        m = _market(bid=49, ask=53)  # mid=51 — within dead zone
        passed, reason = filt.evaluate(m)
        assert passed is False
        assert "dead zone" in reason

    def test_edge_at_boundary_passes(self):
        """Market whose mid is outside the dead-zone boundary passes."""
        cfg = MarketFilterConfig(min_edge_dead_zone_pct=3.0)
        filt = MarketFilter(cfg)
        # mid=45: abs(45-50)=5 >= 3 → outside dead zone, passes
        m = _market(bid=43, ask=47)
        passed, reason = filt.evaluate(m)
        assert passed is True

    def test_dead_zone_disabled_when_zero(self):
        """min_edge_dead_zone_pct=0 disables the dead zone check."""
        cfg = MarketFilterConfig(min_edge_dead_zone_pct=0.0)
        filt = MarketFilter(cfg)
        m = _market(bid=49, ask=53)  # mid=51 — would be dead zone, but disabled
        passed, reason = filt.evaluate(m)
        assert passed is True

    def test_rejected_counts_edge_deadzone(self):
        """Rejections for dead zone are counted separately."""
        filt = MarketFilter()
        markets = [_market(bid=49, ask=53)]  # mid=51 — dead zone
        result = filt.filter_markets(markets)
        assert result.rejected_edge_deadzone == 1
        assert result.passed == 0


# ── Max candidates per asset ─────────────────────────────────────────

class TestMaxCandidatesPerAsset:
    def test_candidates_capped_per_asset(self):
        """At most max_candidates_per_asset markets are returned per underlying."""
        cfg = MarketFilterConfig(max_candidates_per_asset=2)
        filt = MarketFilter(cfg)
        markets = [
            _market(ticker=f"KXBTC-{i}", volume=100, oi=50) for i in range(6)
        ]
        result = filt.filter_markets(markets)
        assert len(result.candidates) == 2
        assert result.capped_per_asset == 4

    def test_cap_applied_per_underlying(self):
        """Cap is applied per underlying independently."""
        cfg = MarketFilterConfig(max_candidates_per_asset=2)
        filt = MarketFilter(cfg)
        btc_markets = [_market(ticker=f"KXBTC-{i}", underlying="BTC") for i in range(4)]
        eth_markets = [_market(ticker=f"KXETH-{i}", underlying="ETH") for i in range(3)]
        result = filt.filter_markets(btc_markets + eth_markets)
        btc_kept = [c for c in result.candidates if c.underlying == "BTC"]
        eth_kept = [c for c in result.candidates if c.underlying == "ETH"]
        assert len(btc_kept) == 2
        assert len(eth_kept) == 2

    def test_nearest_spot_kept_when_distance_available(self):
        """Candidates closest to spot are preferred when spot_price is set."""
        cfg = MarketFilterConfig(max_candidates_per_asset=2)
        filt = MarketFilter(cfg)
        spot = 100000.0
        markets = []
        for strike in [90000, 95000, 105000, 120000]:  # distances: 10%, 5%, 5%, 20%
            m = _market(ticker=f"BTC-{strike}")
            m.strike_price = float(strike)
            m.spot_price = spot
            markets.append(m)
        result = filt.filter_markets(markets)
        assert len(result.candidates) == 2
        # The two closest should be the 5% strikes
        tickers_kept = {c.ticker for c in result.candidates}
        assert "BTC-95000" in tickers_kept
        assert "BTC-105000" in tickers_kept

    def test_cap_zero_means_unlimited(self):
        """max_candidates_per_asset=0 disables the per-asset cap."""
        cfg = MarketFilterConfig(max_candidates_per_asset=0)
        filt = MarketFilter(cfg)
        markets = [_market(ticker=f"KXBTC-{i}") for i in range(10)]
        result = filt.filter_markets(markets)
        assert len(result.candidates) == 10
        assert result.capped_per_asset == 0

    def test_filter_result_to_dict_has_new_counters(self):
        """to_dict() includes new rejection counters."""
        cfg = MarketFilterConfig(max_candidates_per_asset=1)
        filt = MarketFilter(cfg)
        result = filt.filter_markets([_market(ticker="t1"), _market(ticker="t2")])
        d = result.to_dict()
        assert "rejected_distance" in d
        assert "rejected_edge_deadzone" in d
        assert "capped_per_asset" in d


# ── Relative-volume band filter ──────────────────────────────────────

class TestVolumeBandFilter:
    """Validate the relative-volume band gate and its audit metrics.

    The band is expressed as [volume_band_min, volume_band_max] where each
    market's score is market.volume / max(batch.volume).  A score outside
    the band causes the market to be rejected and counted in
    FilterResult.rejected_volume_band.
    """

    def test_band_disabled_by_default(self):
        """Default config (0.0/1.0) passes all markets regardless of relative volume."""
        filt = MarketFilter()  # default config
        markets = [
            _market(ticker="low",  volume=100),
            _market(ticker="mid",  volume=500),
            _market(ticker="high", volume=1000),
        ]
        result = filt.filter_markets(markets)
        assert result.rejected_volume_band == 0
        assert result.passed == 3

    def test_low_volume_tail_rejected(self):
        """Market with relative volume below volume_band_min is rejected."""
        cfg = MarketFilterConfig(volume_band_min=0.4, volume_band_max=0.8)
        filt = MarketFilter(cfg)
        markets = [
            _market(ticker="low",  volume=10),   # rel=0.01 < 0.4 → rejected
            _market(ticker="mid",  volume=600),  # rel=0.6 ∈ [0.4,0.8] → pass
            _market(ticker="high", volume=1000), # rel=1.0 > 0.8 → rejected
        ]
        result = filt.filter_markets(markets)
        assert result.rejected_volume_band == 2
        assert result.passed == 1
        assert result.candidates[0].ticker == "mid"

    def test_high_volume_spike_rejected(self):
        """Market with relative volume above volume_band_max is rejected."""
        cfg = MarketFilterConfig(volume_band_min=0.4, volume_band_max=0.8)
        filt = MarketFilter(cfg)
        markets = [
            _market(ticker="normal", volume=500),  # rel=0.5 ∈ [0.4,0.8]
            _market(ticker="spike",  volume=1000), # rel=1.0 > 0.8 → rejected
        ]
        result = filt.filter_markets(markets)
        assert result.rejected_volume_band == 1
        assert result.passed == 1
        assert result.candidates[0].ticker == "normal"

    def test_all_equal_volume_passes(self):
        """All markets with identical volume have rel=1.0 and pass any max ≥ 1.0."""
        cfg = MarketFilterConfig(volume_band_min=0.4, volume_band_max=1.0)
        filt = MarketFilter(cfg)
        markets = [_market(ticker=f"m{i}", volume=200) for i in range(4)]
        result = filt.filter_markets(markets)
        assert result.rejected_volume_band == 0

    def test_empty_batch_no_crash(self):
        """Empty batch with an active band produces an empty result safely."""
        cfg = MarketFilterConfig(volume_band_min=0.4, volume_band_max=0.8)
        filt = MarketFilter(cfg)
        result = filt.filter_markets([])
        assert result.total_input == 0
        assert result.rejected_volume_band == 0
        assert result.volume_band_block_rate == 0.0

    def test_zero_max_volume_skips_band_check(self):
        """If all markets have zero volume the band check is skipped (no ZeroDivisionError)."""
        cfg = MarketFilterConfig(volume_band_min=0.4, volume_band_max=0.8)
        filt = MarketFilter(cfg)
        # Volumes are all 0; band check would divide by zero → must skip gracefully
        markets = [_market(ticker=f"m{i}", volume=0) for i in range(3)]
        result = filt.filter_markets(markets)
        # No crash; markets may fail other gates (min_volume floor) but not band
        assert result.rejected_volume_band == 0

    def test_volume_band_block_rate_property(self):
        """volume_band_block_rate equals rejected_volume_band / total_input."""
        cfg = MarketFilterConfig(volume_band_min=0.4, volume_band_max=0.8)
        filt = MarketFilter(cfg)
        markets = [
            _market(ticker="a", volume=10),   # rel=0.01 → rejected by band
            _market(ticker="b", volume=600),  # rel=0.6 → pass
            _market(ticker="c", volume=1000), # rel=1.0 → rejected by band
            _market(ticker="d", volume=500),  # rel=0.5 → pass
        ]
        result = filt.filter_markets(markets)
        assert result.rejected_volume_band == 2
        assert result.volume_band_block_rate == pytest.approx(2 / 4)

    def test_to_dict_includes_volume_band_metrics(self):
        """to_dict() exposes rejected_volume_band and volume_band_block_rate."""
        cfg = MarketFilterConfig(volume_band_min=0.4, volume_band_max=0.8)
        filt = MarketFilter(cfg)
        markets = [
            _market(ticker="low",  volume=50),   # rel=0.05 < 0.4 → band reject
            _market(ticker="mid",  volume=600),  # rel=0.6 → pass
            _market(ticker="high", volume=1000), # rel=1.0 > 0.8 → band reject
        ]
        result = filt.filter_markets(markets)
        d = result.to_dict()
        assert "rejected_volume_band" in d
        assert "volume_band_block_rate" in d
        assert d["rejected_volume_band"] == 2
        assert d["volume_band_block_rate"] == pytest.approx(2 / 3, abs=1e-4)

    def test_band_rejection_exclusive_from_other_buckets(self):
        """A market rejected by the band is NOT also counted as a volume-floor reject."""
        cfg = MarketFilterConfig(
            min_volume=50,          # raw floor
            volume_band_min=0.4,    # relative floor
            volume_band_max=0.8,
        )
        filt = MarketFilter(cfg)
        # volume=10: below both the raw floor AND the relative band.
        # Should only increment rejected_volume_band, not rejected_volume.
        markets = [
            _market(ticker="outlier", volume=10),
            _market(ticker="normal",  volume=600),
            _market(ticker="spike",   volume=1000),
        ]
        result = filt.filter_markets(markets)
        # "outlier" (rel=0.01 < 0.4) and "spike" (rel=1.0 > 0.8) hit the band
        assert result.rejected_volume_band == 2
        assert result.rejected_volume == 0   # band check fires first via `continue`

    def test_min_only_band_passes_all_high_volume(self):
        """Setting only a lower bound (volume_band_max=1.0) rejects just the low tail."""
        cfg = MarketFilterConfig(volume_band_min=0.5, volume_band_max=1.0)
        filt = MarketFilter(cfg)
        markets = [
            _market(ticker="thin", volume=10),   # rel=0.01 < 0.5 → reject
            _market(ticker="ok1",  volume=600),  # rel=0.6 → pass
            _market(ticker="ok2",  volume=1000), # rel=1.0 == 1.0 ≤ 1.0 → pass
        ]
        result = filt.filter_markets(markets)
        assert result.rejected_volume_band == 1
        assert result.passed == 2
        assert {c.ticker for c in result.candidates} == {"ok1", "ok2"}

    def test_max_only_band_rejects_spike_keeps_low(self):
        """Setting only an upper bound (volume_band_min=0.0) rejects just the spike."""
        cfg = MarketFilterConfig(volume_band_min=0.0, volume_band_max=0.8)
        filt = MarketFilter(cfg)
        markets = [
            _market(ticker="thin",  volume=10),   # rel=0.01 ≥ 0.0 → pass
            _market(ticker="ok",    volume=600),  # rel=0.6 ≤ 0.8 → pass
            _market(ticker="spike", volume=1000), # rel=1.0 > 0.8 → reject
        ]
        result = filt.filter_markets(markets)
        # thin passes band but may fail raw min_volume floor (100 by default);
        # we care only that the spike is in the band bucket, not the volume bucket
        assert result.rejected_volume_band == 1
        assert "spike" not in {c.ticker for c in result.candidates}

    def test_volume_band_block_rate_is_zero_without_rejections(self):
        """block_rate is exactly 0.0 when no markets are band-rejected."""
        filt = MarketFilter()
        result = filt.filter_markets([_market()])
        assert result.volume_band_block_rate == 0.0
