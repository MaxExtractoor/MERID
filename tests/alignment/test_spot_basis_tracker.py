"""Tests for merid/alignment/spot_basis_tracker.py.

Covers:
- compute_implied_spot pure function (all edge cases)
- SpotBasisTracker._compute_asset_basis (feed status, alignment state machine)
- SpotBasisTracker.get_stats (rolling statistics)
- SpotBasisTracker._state_belongs_to_asset (asset mapping)
- SpotBasisTracker thread lifecycle (start/stop idempotency)
"""
from __future__ import annotations

import time
import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from merid.alignment.spot_basis_tracker import (
    AlignmentState,
    AssetBasis,
    FeedStatus,
    SpotBasisTracker,
    _iter_clusters,
    compute_implied_spot,
)


# ── Fixture helpers ────────────────────────────────────────────────────────────


def _make_state(
    ticker: str,
    strike: float,
    mid: float,          # cents (0–100 scale), may be float
    bid: float = None,   # cents
    ask: float = None,   # cents
    expiry: float = 300.0,
    asset: str = "BTC",
    book_initialized: bool = True,
) -> MagicMock:
    """Build a minimal KalshiMarketState mock for basis tests."""
    s = MagicMock()
    s.ticker = ticker
    s.strike_price = strike
    s.mid_cents = mid
    s.best_bid_cents = bid if bid is not None else (mid - 3 if mid is not None else None)
    s.best_ask_cents = ask if ask is not None else (mid + 3 if mid is not None else None)
    s.book_initialized = book_initialized
    s.seconds_to_expiry = expiry
    s.underlying = asset
    s.last_book_update_ts = time.monotonic()
    return s


def _make_feed(
    spot_price: float,
    age_mono_seconds: float = 0.1,
    symbol: str = "BTC/USD",
) -> MagicMock:
    """Build a mock LivePriceFeed with one asset entry."""
    price_data = MagicMock()
    price_data.price = spot_price

    feed = MagicMock()
    feed.price_cache = {symbol: price_data}
    feed._last_tick_monotonic = {symbol: time.monotonic() - age_mono_seconds}
    return feed


def _make_store(states: list) -> MagicMock:
    """Build a mock KalshiMarketStateStore returning states keyed by ticker."""
    store = MagicMock()
    store.get_all.return_value = {s.ticker: s for s in states}
    return store


# ── compute_implied_spot ───────────────────────────────────────────────────────


class TestComputeImpliedSpot:
    def test_exact_50_prob_at_strike(self):
        """When one market has YES prob exactly 0.50, implied spot == its strike."""
        states = [
            _make_state("T-A", strike=96000.0, mid=70.0),
            _make_state("T-B", strike=97000.0, mid=50.0),  # ← exact 0.50
            _make_state("T-C", strike=98000.0, mid=30.0),
        ]
        result = compute_implied_spot(states, "mid")
        assert result == pytest.approx(97000.0, abs=1.0)

    def test_interpolated_between_two_brackets(self):
        """Linear interpolation between two bracketing strikes is correct."""
        states = [
            _make_state("T-A", strike=96000.0, mid=60.0),  # p=0.60
            _make_state("T-B", strike=98000.0, mid=40.0),  # p=0.40
        ]
        # t = (0.60 - 0.50) / (0.60 - 0.40) = 0.5
        # implied = 96000 + 0.5 * 2000 = 97000
        result = compute_implied_spot(states, "mid")
        assert result == pytest.approx(97000.0, abs=1.0)

    def test_returns_none_all_probs_above_50(self):
        """All YES probs > 0.50 → no lower-side bracket → None."""
        states = [
            _make_state("T-A", strike=94000.0, mid=80.0),
            _make_state("T-B", strike=95000.0, mid=70.0),
            _make_state("T-C", strike=96000.0, mid=60.0),
        ]
        assert compute_implied_spot(states, "mid") is None

    def test_returns_none_all_probs_below_50(self):
        """All YES probs < 0.50 → no upper-side bracket → None."""
        states = [
            _make_state("T-A", strike=97000.0, mid=40.0),
            _make_state("T-B", strike=98000.0, mid=30.0),
        ]
        assert compute_implied_spot(states, "mid") is None

    def test_returns_none_single_market(self):
        """Single market cannot be interpolated → None."""
        assert compute_implied_spot([_make_state("T-A", 97000.0, 55.0)], "mid") is None

    def test_returns_none_empty_list(self):
        assert compute_implied_spot([], "mid") is None

    def test_bid_variant_uses_best_bid_cents(self):
        """'bid' uses best_bid_cents, not mid_cents."""
        states = [
            _make_state("T-A", strike=96000.0, mid=70.0, bid=65.0, ask=75.0),
            _make_state("T-B", strike=98000.0, mid=30.0, bid=25.0, ask=35.0),
        ]
        # bid p: 0.65 and 0.25 → t = (0.65-0.50)/(0.65-0.25)=0.375 → 96750
        result = compute_implied_spot(states, "bid")
        assert result == pytest.approx(96750.0, abs=1.0)

    def test_ask_variant_uses_best_ask_cents(self):
        """'ask' uses best_ask_cents."""
        states = [
            _make_state("T-A", strike=96000.0, mid=70.0, bid=65.0, ask=75.0),
            _make_state("T-B", strike=98000.0, mid=30.0, bid=25.0, ask=35.0),
        ]
        # ask p: 0.75 and 0.35 → t = (0.75-0.50)/(0.75-0.35)=0.625 → 97250
        result = compute_implied_spot(states, "ask")
        assert result == pytest.approx(97250.0, abs=1.0)

    def test_skips_markets_without_strike(self):
        """Markets with strike_price=None are excluded."""
        no_strike = _make_state("T-X", strike=96000.0, mid=60.0)
        no_strike.strike_price = None
        states = [
            no_strike,
            _make_state("T-A", strike=96000.0, mid=60.0),
            _make_state("T-B", strike=98000.0, mid=40.0),
        ]
        assert compute_implied_spot(states, "mid") == pytest.approx(97000.0, abs=1.0)

    def test_skips_markets_not_book_initialized(self):
        """Markets with book_initialized=False are excluded."""
        states = [
            _make_state("T-X", strike=96000.0, mid=60.0, book_initialized=False),
            _make_state("T-A", strike=96000.0, mid=60.0),
            _make_state("T-B", strike=98000.0, mid=40.0),
        ]
        assert compute_implied_spot(states, "mid") == pytest.approx(97000.0, abs=1.0)

    def test_skips_expired_markets_seconds_to_expiry_zero(self):
        """Expired markets (seconds_to_expiry == 0.0) are excluded."""
        states = [
            _make_state("T-X", strike=96000.0, mid=60.0, expiry=0.0),
            _make_state("T-A", strike=96000.0, mid=60.0, expiry=300.0),
            _make_state("T-B", strike=98000.0, mid=40.0, expiry=300.0),
        ]
        assert compute_implied_spot(states, "mid") == pytest.approx(97000.0, abs=1.0)

    def test_clusters_by_expiry_uses_nearest_multistrike_cluster(self):
        """15m single-strike cluster is skipped; 1H multi-strike cluster is used."""
        # Near cluster (15m, 1 strike) — should be skipped
        near_single = _make_state("T-Near", strike=97000.0, mid=50.0, expiry=300.0)

        # Far cluster (1H, 2 strikes) — should be used
        far_a = _make_state("T-Far-A", strike=96000.0, mid=60.0, expiry=3600.0)
        far_b = _make_state("T-Far-B", strike=98000.0, mid=40.0, expiry=3600.0)

        result = compute_implied_spot([near_single, far_a, far_b], "mid")
        assert result == pytest.approx(97000.0, abs=1.0)

    def test_two_near_strikes_same_cluster_are_used(self):
        """When the nearest cluster has 2+ strikes, it is used (not skipped)."""
        states = [
            _make_state("T-A", strike=96000.0, mid=60.0, expiry=300.0),
            _make_state("T-B", strike=98000.0, mid=40.0, expiry=310.0),  # same cluster
        ]
        assert compute_implied_spot(states, "mid") == pytest.approx(97000.0, abs=1.0)


# ── _iter_clusters ─────────────────────────────────────────────────────────────


class TestIterClusters:
    def test_groups_close_expiries_together(self):
        """Markets within 90s of each other form one cluster."""
        states = [
            _make_state("A", 1.0, 50.0, expiry=300.0),
            _make_state("B", 2.0, 50.0, expiry=360.0),  # 60s apart → same cluster
            _make_state("C", 3.0, 50.0, expiry=3600.0), # far → own cluster
        ]
        clusters = list(_iter_clusters(states))
        assert len(clusters) == 2
        assert len(clusters[0]) == 2
        assert len(clusters[1]) == 1

    def test_empty_input_yields_nothing(self):
        assert list(_iter_clusters([])) == []


# ── SpotBasisTracker._compute_asset_basis ──────────────────────────────────────


class TestSpotBasisTrackerComputeAssetBasis:
    def _tracker(self, states, spot_price, spot_age_s=0.1):
        states_list = states if isinstance(states, list) else list(states)
        return SpotBasisTracker(
            store=_make_store(states_list),
            feed=_make_feed(spot_price, age_mono_seconds=spot_age_s),
        )

    def _all_states(self, states):
        return {s.ticker: s for s in states}

    def test_aligned_when_basis_within_threshold(self):
        states = [
            _make_state("T-A", 96000.0, 60.0, asset="BTC", expiry=3600.0),
            _make_state("T-B", 98000.0, 40.0, asset="BTC", expiry=3600.0),
        ]
        tracker = self._tracker(states, spot_price=97000.0)
        feed = _make_feed(97000.0)
        ab = tracker._compute_asset_basis("BTC", self._all_states(states), feed)
        assert ab.alignment == AlignmentState.ALIGNED
        assert ab.basis_mid == pytest.approx(0.0, abs=1.0)
        assert ab.spot_status == FeedStatus.OK

    def test_breach_count_accumulates_then_flips_offside(self):
        """breach_count must reach breach_count_threshold before → OFFSIDE."""
        from config.spot_basis_config import ASSET_THRESHOLDS
        thr = ASSET_THRESHOLDS["BTC"]

        # Basis = +2000 USD (far above 50 USD threshold)
        states = [
            _make_state("T-A", 96000.0, 60.0, asset="BTC", expiry=3600.0),
            _make_state("T-B", 100000.0, 40.0, asset="BTC", expiry=3600.0),
            # implied = 96000 + 0.5*(100000-96000) = 98000 → basis = +1000 vs spot 97000
        ]
        tracker = SpotBasisTracker(
            store=_make_store(states), feed=_make_feed(97000.0)
        )
        feed = _make_feed(97000.0)
        all_s = self._all_states(states)

        n = thr.breach_count_threshold
        for i in range(n - 1):
            ab = tracker._compute_asset_basis("BTC", all_s, feed)
            assert ab.alignment == AlignmentState.ALIGNED, f"tick {i}: premature OFFSIDE"

        ab = tracker._compute_asset_basis("BTC", all_s, feed)
        assert ab.alignment == AlignmentState.OFFSIDE
        assert ab.breach_count == n

    def test_breach_count_decrements_on_recovery(self):
        """Once breach clears, breach_count decrements toward 0."""
        from config.spot_basis_config import ASSET_THRESHOLDS
        thr = ASSET_THRESHOLDS["BTC"]
        states_breach = [
            _make_state("T-A", 96000.0, 60.0, asset="BTC", expiry=3600.0),
            _make_state("T-B", 100000.0, 40.0, asset="BTC", expiry=3600.0),
        ]
        # states_ok: ATM, no breach
        states_ok = [
            _make_state("T-A", 96000.0, 60.0, asset="BTC", expiry=3600.0),
            _make_state("T-B", 98000.0, 40.0, asset="BTC", expiry=3600.0),
        ]
        tracker = SpotBasisTracker(store=_make_store(states_breach), feed=_make_feed(97000.0))
        feed = _make_feed(97000.0)

        # Drive to OFFSIDE
        for _ in range(thr.breach_count_threshold):
            tracker._compute_asset_basis("BTC", {s.ticker: s for s in states_breach}, feed)

        # Recover
        ab = tracker._compute_asset_basis("BTC", {s.ticker: s for s in states_ok}, feed)
        assert ab.breach_count == thr.breach_count_threshold - 1

    def test_stale_feed_when_spot_missing(self):
        """Spot age > SPOT_MISSING_MS → FeedStatus.MISSING → STALE_FEED alignment."""
        states = [
            _make_state("T-A", 96000.0, 60.0, asset="BTC", expiry=3600.0),
            _make_state("T-B", 98000.0, 40.0, asset="BTC", expiry=3600.0),
        ]
        tracker = SpotBasisTracker(
            store=_make_store(states), feed=_make_feed(97000.0, age_mono_seconds=60.0)
        )
        feed = _make_feed(97000.0, age_mono_seconds=60.0)  # 60s old → MISSING
        ab = tracker._compute_asset_basis("BTC", {s.ticker: s for s in states}, feed)
        assert ab.spot_status == FeedStatus.MISSING
        assert ab.alignment == AlignmentState.STALE_FEED

    def test_stale_feed_when_kalshi_book_missing(self):
        """Kalshi book too old → FeedStatus.MISSING → STALE_FEED."""
        old_ts = time.monotonic() - 120.0  # 120s ago → MISSING (threshold = 60s)
        states = [
            _make_state("T-A", 96000.0, 60.0, asset="BTC", expiry=3600.0),
            _make_state("T-B", 98000.0, 40.0, asset="BTC", expiry=3600.0),
        ]
        for s in states:
            s.last_book_update_ts = old_ts

        tracker = SpotBasisTracker(store=_make_store(states), feed=_make_feed(97000.0))
        feed = _make_feed(97000.0)
        ab = tracker._compute_asset_basis("BTC", {s.ticker: s for s in states}, feed)
        assert ab.kalshi_book_status == FeedStatus.MISSING
        assert ab.alignment == AlignmentState.STALE_FEED

    def test_breach_count_reset_on_stale_feed(self):
        """Entering STALE_FEED resets breach_count to 0."""
        from config.spot_basis_config import ASSET_THRESHOLDS
        thr = ASSET_THRESHOLDS["BTC"]
        states = [
            _make_state("T-A", 96000.0, 60.0, asset="BTC", expiry=3600.0),
            _make_state("T-B", 100000.0, 40.0, asset="BTC", expiry=3600.0),
        ]
        tracker = SpotBasisTracker(store=_make_store(states), feed=_make_feed(97000.0))
        feed_ok = _make_feed(97000.0)
        for _ in range(thr.breach_count_threshold):
            tracker._compute_asset_basis("BTC", {s.ticker: s for s in states}, feed_ok)

        feed_missing = _make_feed(97000.0, age_mono_seconds=60.0)
        ab = tracker._compute_asset_basis("BTC", {s.ticker: s for s in states}, feed_missing)
        assert ab.breach_count == 0
        assert ab.alignment == AlignmentState.STALE_FEED


# ── SpotBasisTracker.get_all and tick ─────────────────────────────────────────


class TestSpotBasisTrackerGetAll:
    def test_get_all_returns_all_five_assets_after_tick(self):
        """After _tick(), get_all() returns an entry for every ASSETS element."""
        feed = MagicMock()
        feed.price_cache = {}
        feed._last_tick_monotonic = {}
        store = MagicMock()
        store.get_all.return_value = {}
        tracker = SpotBasisTracker(store=store, feed=feed)
        tracker._tick()
        result = tracker.get_all()
        assert set(result.keys()) == {"BTC", "ETH", "SOL", "XRP", "DOGE"}

    def test_get_returns_none_before_first_tick(self):
        tracker = SpotBasisTracker(store=MagicMock(), feed=MagicMock())
        assert tracker.get("BTC") is None

    def test_start_stop_idempotent(self):
        """Calling start() twice and stop() twice must not raise."""
        feed = MagicMock()
        feed.price_cache = {}
        feed._last_tick_monotonic = {}
        store = MagicMock()
        store.get_all.return_value = {}
        tracker = SpotBasisTracker(store=store, feed=feed)
        tracker.start()
        tracker.start()  # idempotent
        assert tracker._thread is not None and tracker._thread.is_alive()
        tracker.stop()
        tracker.stop()  # idempotent — must not raise


# ── SpotBasisTracker.get_stats ─────────────────────────────────────────────────


class TestSpotBasisTrackerGetStats:
    def test_returns_none_fields_when_no_samples(self):
        tracker = SpotBasisTracker(store=MagicMock(), feed=MagicMock())
        stats = tracker.get_stats()
        for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            assert stats[asset]["sample_count"] == 0
            assert stats[asset]["basis_mean"] is None

    def test_mean_and_median_computed_from_rolling_deque(self):
        tracker = SpotBasisTracker(store=MagicMock(), feed=MagicMock())
        now = time.monotonic()
        tracker._rolling["BTC"].extend([(now - i, float(i)) for i in range(5)])
        stats = tracker.get_stats(window_seconds=3600)
        assert stats["BTC"]["sample_count"] == 5
        assert stats["BTC"]["basis_mean"] == pytest.approx(2.0)
        assert stats["BTC"]["basis_median"] == pytest.approx(2.0)

    def test_window_excludes_old_samples(self):
        tracker = SpotBasisTracker(store=MagicMock(), feed=MagicMock())
        now = time.monotonic()
        # 3 recent samples + 2 old samples
        tracker._rolling["ETH"].extend([
            (now - 10, 1.0),
            (now - 20, 2.0),
            (now - 30, 3.0),
            (now - 7200, 999.0),  # too old
            (now - 5000, 999.0),  # too old
        ])
        stats = tracker.get_stats(window_seconds=3600)
        assert stats["ETH"]["sample_count"] == 3
        assert stats["ETH"]["basis_mean"] == pytest.approx(2.0)


# ── SpotBasisTracker._state_belongs_to_asset ──────────────────────────────────


class TestStateBelongsToAsset:
    def test_matches_by_underlying_field(self):
        s = _make_state("KXETH-T", 3000.0, 50.0, asset="ETH")
        assert SpotBasisTracker._state_belongs_to_asset(s, "KXETH-T", "ETH", "KXETH")
        assert not SpotBasisTracker._state_belongs_to_asset(s, "KXETH-T", "BTC", "KXBTC")

    def test_falls_back_to_ticker_prefix_when_underlying_none(self):
        s = _make_state("KXSOL15M-A", 150.0, 50.0, asset="SOL")
        s.underlying = None  # force prefix fallback
        assert SpotBasisTracker._state_belongs_to_asset(s, "KXSOL15M-A", "SOL", "KXSOL")
        assert not SpotBasisTracker._state_belongs_to_asset(s, "KXSOL15M-A", "ETH", "KXETH")

    def test_empty_prefix_never_matches(self):
        s = _make_state("KXBTC-A", 97000.0, 50.0, asset="BTC")
        s.underlying = None
        assert not SpotBasisTracker._state_belongs_to_asset(s, "KXBTC-A", "BTC", "")


# ── AssetBasis.to_dict ─────────────────────────────────────────────────────────


class TestAssetBasisToDict:
    def test_to_dict_has_all_keys(self):
        ab = AssetBasis(
            asset="BTC",
            spot_price=97000.0,
            spot_status=FeedStatus.OK,
            kalshi_book_status=FeedStatus.OK,
            implied_spot_mid=97050.0,
            implied_spot_bid=96990.0,
            implied_spot_ask=97100.0,
            basis_mid=50.0,
            basis_bid=-10.0,
            basis_ask=100.0,
            alignment=AlignmentState.ALIGNED,
            breach_count=0,
            markets_used=4,
            nearest_expiry_secs=1800.0,
        )
        d = ab.to_dict()
        assert d["spot_status"] == "ok"
        assert d["alignment"] == "aligned"
        assert d["basis_mid"] == 50.0
        assert d["markets_used"] == 4
        expected_keys = {
            "asset", "spot_price", "spot_status", "kalshi_book_status",
            "implied_spot_mid", "implied_spot_bid", "implied_spot_ask",
            "basis_mid", "basis_bid", "basis_ask", "alignment",
            "breach_count", "markets_used", "nearest_expiry_secs", "computed_at",
        }
        assert expected_keys <= set(d.keys())
