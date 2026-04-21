"""Contract for ``FlatTrapFilter`` — the tick-level regime guard.

The filter is a pure function of a recent price series plus a config.
These tests pin:

1. The two anti-patterns it is meant to catch (flat, trap).
2. The fail-open behaviour on sparse data.
3. The observability counters operators rely on.
"""

from __future__ import annotations

import pytest

from merid.event_venues.kalshi.flat_trap_filter import (
    FlatTrapConfig,
    FlatTrapFilter,
    RegimeCheckResult,
)


# ═══════════════════════════════════════════════════════════════════════════
# Fail-open on sparse data
# ═══════════════════════════════════════════════════════════════════════════


class TestSparseData:

    def test_empty_series_is_tradeable(self):
        f = FlatTrapFilter()
        verdict = f.evaluate([])
        assert verdict.tradeable is True
        assert verdict.reason is None

    def test_below_min_ticks_is_tradeable(self):
        """Short series must not cause a fail-closed cascade."""
        f = FlatTrapFilter(FlatTrapConfig(min_ticks=6))
        verdict = f.evaluate([50, 52, 54])
        assert verdict.tradeable is True
        assert verdict.reason is None

    def test_sparse_data_increments_insufficient_counter(self):
        f = FlatTrapFilter()
        f.evaluate([50, 52])
        assert f.metrics["insufficient_data"] == 1
        assert f.metrics["tradeable"] == 1
        assert f.metrics["blocked_flat"] == 0
        assert f.metrics["blocked_trap"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# Flat detection
# ═══════════════════════════════════════════════════════════════════════════


class TestFlatDetection:

    def test_identical_prices_blocked_as_flat(self):
        f = FlatTrapFilter()
        verdict = f.evaluate([50] * 10)
        assert verdict.tradeable is False
        assert verdict.reason == "flat"
        assert verdict.details["price_range"] == 0

    def test_range_exactly_at_threshold_is_flat(self):
        """``<=`` semantics: range == threshold is flat."""
        f = FlatTrapFilter(FlatTrapConfig(min_ticks=6, flat_range_cents=2))
        verdict = f.evaluate([50, 51, 52, 51, 52, 50])  # range == 2
        assert verdict.tradeable is False
        assert verdict.reason == "flat"

    def test_range_one_above_threshold_is_tradeable(self):
        f = FlatTrapFilter(
            FlatTrapConfig(
                min_ticks=6,
                flat_range_cents=2,
                # Disarm the trap guard so this test only exercises the
                # flat boundary.
                trap_reversal_rate=1.1,
                trap_min_reversals=99,
            )
        )
        verdict = f.evaluate([50, 51, 52, 53, 52, 50])  # range == 3
        assert verdict.tradeable is True
        assert verdict.reason is None

    def test_flat_increments_blocked_flat_counter(self):
        f = FlatTrapFilter()
        f.evaluate([50] * 10)
        assert f.metrics["blocked_flat"] == 1
        assert f.metrics["blocked_trap"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# Trap detection
# ═══════════════════════════════════════════════════════════════════════════


class TestTrapDetection:

    def test_alternating_series_blocked_as_trap(self):
        """The canonical whipsaw — every tick reverses."""
        f = FlatTrapFilter(FlatTrapConfig(min_ticks=6, flat_range_cents=0))
        # 50→52→50→52→50→52→50 : 6 nonzero moves, 5 reversals
        verdict = f.evaluate([50, 52, 50, 52, 50, 52, 50])
        assert verdict.tradeable is False
        assert verdict.reason == "trap"
        assert verdict.details["reversals"] == 5

    def test_monotonic_trend_is_tradeable(self):
        """Pure trend: zero reversals, not a trap."""
        f = FlatTrapFilter(FlatTrapConfig(min_ticks=6, flat_range_cents=0))
        verdict = f.evaluate([50, 51, 52, 53, 54, 55, 56])
        assert verdict.tradeable is True
        assert verdict.reason is None
        assert verdict.details["reversals"] == 0

    def test_single_reversal_is_not_enough(self):
        """``trap_min_reversals=2`` must actually gate on count, not just rate."""
        f = FlatTrapFilter(
            FlatTrapConfig(
                min_ticks=6,
                flat_range_cents=0,
                trap_reversal_rate=0.0,  # any reversal would otherwise trip
                trap_min_reversals=2,
            )
        )
        verdict = f.evaluate([50, 51, 52, 53, 52, 51, 50])  # 1 reversal
        assert verdict.tradeable is True
        assert verdict.reason is None

    def test_zero_diffs_do_not_count_as_direction_votes(self):
        """Flat ticks between moves must not break reversal detection."""
        f = FlatTrapFilter(
            FlatTrapConfig(
                min_ticks=4,
                flat_range_cents=0,
                # Threshold just below 0.5 so a 1-in-2 reversal rate trips it.
                # (The code uses strict >, so 0.5 > 0.5 would be false.)
                trap_reversal_rate=0.49,
                trap_min_reversals=1,
            )
        )
        # 50 → 52 (up) → 52 (flat) → 52 (flat) → 50 (down) — one reversal
        # because the two zero diffs in the middle are skipped.
        verdict = f.evaluate([50, 52, 52, 52, 50])
        assert verdict.tradeable is False
        assert verdict.reason == "trap"
        assert verdict.details["reversals"] == 1
        # moves excludes the two zero diffs
        assert verdict.details["moves"] == 2

    def test_trap_increments_blocked_trap_counter(self):
        f = FlatTrapFilter(FlatTrapConfig(min_ticks=6, flat_range_cents=0))
        f.evaluate([50, 52, 50, 52, 50, 52, 50])
        assert f.metrics["blocked_trap"] == 1
        assert f.metrics["blocked_flat"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# Flat takes precedence over trap when both could fire
# ═══════════════════════════════════════════════════════════════════════════


class TestFlatPrecedence:

    def test_flat_beats_trap_when_both_would_fire(self):
        """A 1-cent whipsaw should be classified as flat, not trap.

        The flat guard short-circuits first because a market that
        hasn't moved more than a tick isn't really whipsawing — it's
        just sitting.  This keeps the "reason" field informative for
        operators diagnosing why the scalper is skipping.
        """
        f = FlatTrapFilter(FlatTrapConfig(min_ticks=6, flat_range_cents=1))
        verdict = f.evaluate([50, 51, 50, 51, 50, 51, 50])
        assert verdict.tradeable is False
        assert verdict.reason == "flat"


# ═══════════════════════════════════════════════════════════════════════════
# Metrics + reset
# ═══════════════════════════════════════════════════════════════════════════


class TestMetrics:

    def test_metrics_snapshot_shape_on_fresh_filter(self):
        f = FlatTrapFilter()
        assert set(f.metrics.keys()) == {
            "evaluated",
            "insufficient_data",
            "tradeable",
            "blocked_flat",
            "blocked_trap",
        }
        assert all(v == 0 for v in f.metrics.values())

    def test_every_call_increments_evaluated(self):
        f = FlatTrapFilter()
        for _ in range(5):
            f.evaluate([50, 52, 54, 56, 58, 60])
        assert f.metrics["evaluated"] == 5

    def test_reset_metrics_zeroes_all_counters(self):
        f = FlatTrapFilter()
        f.evaluate([50] * 10)  # blocked_flat
        f.evaluate([50, 52, 50, 52, 50, 52, 50])  # blocked_trap
        assert f.metrics["evaluated"] == 2

        f.reset_metrics()
        assert all(v == 0 for v in f.metrics.values())


# ═══════════════════════════════════════════════════════════════════════════
# Result helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestRegimeCheckResultHelpers:

    def test_ok_is_tradeable(self):
        r = RegimeCheckResult.ok(ticks=10)
        assert r.tradeable is True
        assert r.reason is None
        assert r.details == {"ticks": 10}

    def test_block_is_not_tradeable(self):
        r = RegimeCheckResult.block("flat", price_range=0)
        assert r.tradeable is False
        assert r.reason == "flat"
        assert r.details == {"price_range": 0}
