"""Tests for jump-robust realized-vol estimators (rv / bpv / medrv)."""

import math

from merid.prediction.realized_vol import RealizedVolTracker


def _feed(tracker, asset, returns, start=1_000_000.0, dt=1.0, price0=100.0):
    """Feed one tick per second with the given log returns."""
    price = price0
    ts = start
    tracker.record(asset, price, ts)  # seed tick (no return yet)
    for i, r in enumerate(returns):
        ts += dt
        price *= math.exp(r)
        tracker.record(asset, price, ts)
    return ts


def _tracker(estimator):
    return RealizedVolTracker(
        half_life_s=30.0,
        min_samples=8,
        min_span_s=5.0,
        max_sample_age_s=3600.0,
        max_dt_s=30.0,
        estimator=estimator,
    )


def _estimate(tracker, asset, now):
    est = tracker.annualized_vol(asset, now=now)
    assert est is not None
    return est


def test_estimator_selection_and_fallback():
    assert _tracker("medrv")._estimator == "medrv"
    assert _tracker("bpv")._estimator == "bpv"
    assert _tracker("bogus")._estimator == "rv"  # invalid falls back


def test_estimate_reports_estimator_name():
    tr = _tracker("medrv")
    quiet = [0.0002 * (1 if i % 2 else -1) for i in range(20)]
    now = _feed(tr, "BTC", quiet)
    est = _estimate(tr, "BTC", now)
    assert est.estimator == "medrv"
    assert est.asset == "BTC"
    assert est.value > 0


def test_single_jump_inflates_rv_but_not_robust_estimators():
    quiet = [0.0002 * (1 if i % 2 else -1) for i in range(15)]
    jump = [0.0] * 15 + [0.01] + [0.0] * 15  # one 1% print mid-series

    vols = {}
    for est_name in ("rv", "bpv", "medrv"):
        tr = _tracker(est_name)
        now = _feed(tr, "BTC", quiet + jump)
        vols[est_name] = _estimate(tr, "BTC", now).value

    # The jump should dominate the plain RV estimate but be suppressed by
    # the jump-robust variants (same pattern as the 0.5% smoke test).
    assert vols["medrv"] < vols["rv"]
    assert vols["bpv"] < vols["rv"]
    assert vols["medrv"] < vols["bpv"] or vols["bpv"] < vols["rv"]


def test_rv_and_medrv_track_each_other_without_jumps():
    quiet = [0.0003 * math.sin(i) for i in range(30)]
    vals = {}
    for est_name in ("rv", "medrv"):
        tr = _tracker(est_name)
        now = _feed(tr, "ETH", quiet)
        vals[est_name] = _estimate(tr, "ETH", now).value
    # Same order of magnitude on jump-free data (MedRV scale-corrected).
    assert 0.3 < vals["medrv"] / vals["rv"] < 3.0
