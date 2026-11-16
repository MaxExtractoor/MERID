"""Two-sided tail recalibration: bounded lift of under-confident claims.

The historical calibrator only *capped* over-confident probabilities
(``min(p_model, observed + buffer)``).  ``adjust_p_yes`` / ``adjust_p_no`` add a
bounded, evidence-gated lift for buckets whose observed win rate sits ABOVE
the model claim (the high-side S-curve under-confidence found in the
2026-11-16 Brier audit).  Lifting requires per-knot effective counts, a
minimum-N gate, a significance margin, empirical-Bayes shrinkage, and a hard
lift cap.  With ``MERID_RECAL_TWO_SIDED`` off, or without per-knot counts,
``adjust_*`` reduces exactly to ``cap_*``.
"""
import os

import pytest

from merid.risk.probability.tail_calibrator import (
    TailProbabilityCalibrator,
    _pava_isotonic,
    _pava_isotonic_full,
)


def _enable(monkeypatch, **over):
    monkeypatch.setenv("MERID_RECAL_TWO_SIDED", "1")
    for k, v in over.items():
        monkeypatch.setenv(k, str(v))


# ── PAVA counts ──────────────────────────────────────────────────────────

def test_pava_full_returns_block_counts():
    xs, ys, ns = _pava_isotonic_full([0.1, 0.2, 0.3], [0, 1, 1])
    # blocks pool to a monotone fit; counts must sum to the observation total
    assert sum(ns) == pytest.approx(3.0)
    assert len(xs) == len(ys) == len(ns)


def test_pava_isotonic_still_two_tuple():
    xs, ys = _pava_isotonic([0.1, 0.2, 0.3], [0, 1, 1])
    assert len(xs) == len(ys)


def test_pava_full_duplicate_price_sums_counts():
    # Two observations at the same price collapse to one knot; n must sum.
    xs, ys, ns = _pava_isotonic_full([0.5, 0.5, 0.7], [0, 1, 1])
    assert len(xs) == len(set(round(x, 9) for x in xs))
    assert sum(ns) == pytest.approx(3.0)


def test_pava_full_monotone_non_decreasing():
    import random
    random.seed(0)
    xs = sorted(random.uniform(0.05, 0.95) for _ in range(60))
    ys = [random.randint(0, 1) for _ in range(60)]
    kx, ky, kn = _pava_isotonic_full(xs, ys)
    assert all(ky[i] <= ky[i + 1] + 1e-12 for i in range(len(ky) - 1))
    assert all(n > 0 for n in kn)


# ── adjust_* falls back to cap when disabled / no counts ─────────────────

def _lift_artifact(with_n=True, observed=0.92, n=200.0):
    d = {
        "yes_held_prices": [0.70],
        "yes_actual_probs": [observed],
        "no_held_prices": [0.30],
        "no_actual_probs": [0.08],
        "buffer": 0.05,
        "n_trades": 400,
    }
    if with_n:
        d["yes_held_n"] = [n]
        d["no_held_n"] = [n]
    return d


def test_adjust_equals_cap_when_flag_off(monkeypatch):
    monkeypatch.setenv("MERID_RECAL_TWO_SIDED", "0")
    cal = TailProbabilityCalibrator.from_dict(_lift_artifact())
    # under-confident: model 0.75, observed 0.92 -> cap leaves 0.75 (no lift)
    assert cal.adjust_p_yes(0.75, 0.70) == pytest.approx(
        cal.cap_p_yes(0.75, 0.70)
    ) == pytest.approx(0.75)


def test_adjust_no_lift_without_per_knot_counts(monkeypatch):
    _enable(monkeypatch)
    cal = TailProbabilityCalibrator.from_dict(_lift_artifact(with_n=False))
    # flag on but artifact lacks yes_held_n -> cap-only, no lift
    assert cal.adjust_p_yes(0.75, 0.70) == pytest.approx(0.75)


def test_adjust_lifts_under_confident_with_evidence(monkeypatch):
    _enable(monkeypatch)
    cal = TailProbabilityCalibrator.from_dict(_lift_artifact(observed=0.92, n=200.0))
    out = cal.adjust_p_yes(0.75, 0.70)
    # capped base 0.75 + bounded lift; must exceed the cap-only result and stay
    # under observed + buffer (0.97)
    assert out > 0.75
    assert out <= 0.92 + 0.05 + 1e-9
    # lift cap default 0.10 -> at most 0.85
    assert out <= 0.75 + 0.10 + 1e-9


def test_adjust_still_caps_over_confident(monkeypatch):
    _enable(monkeypatch)
    # observed 0.30, model claims 0.80 -> cap to 0.35, no lift (gap negative)
    cal = TailProbabilityCalibrator.from_dict(_lift_artifact(observed=0.30, n=500.0))
    assert cal.adjust_p_yes(0.80, 0.70) == pytest.approx(0.35)


def test_lift_blocked_below_min_neff(monkeypatch):
    _enable(monkeypatch, MERID_RECAL_MIN_NEFF=50)
    cal = TailProbabilityCalibrator.from_dict(_lift_artifact(observed=0.92, n=20.0))
    assert cal.adjust_p_yes(0.75, 0.70) == pytest.approx(0.75)


def test_lift_blocked_when_gap_not_significant(monkeypatch):
    _enable(monkeypatch, MERID_RECAL_LIFT_Z=3.0)
    # tiny gap vs large SE -> no lift
    cal = TailProbabilityCalibrator.from_dict(
        _lift_artifact(observed=0.78, n=30.0)
    )
    out = cal.adjust_p_yes(0.75, 0.70)
    assert out == pytest.approx(0.75)


def test_lift_respects_hard_cap(monkeypatch):
    _enable(monkeypatch, MERID_RECAL_LIFT_CAP=0.05)
    cal = TailProbabilityCalibrator.from_dict(_lift_artifact(observed=0.99, n=1000.0))
    out = cal.adjust_p_yes(0.70, 0.70)
    assert out <= 0.70 + 0.05 + 1e-9


def test_lift_shrinks_with_small_n(monkeypatch):
    _enable(monkeypatch, MERID_RECAL_PRIOR_K=50)
    cal_small = TailProbabilityCalibrator.from_dict(
        _lift_artifact(observed=0.92, n=60.0)
    )
    cal_big = TailProbabilityCalibrator.from_dict(
        _lift_artifact(observed=0.92, n=2000.0)
    )
    small = cal_small.adjust_p_yes(0.75, 0.70)
    big = cal_big.adjust_p_yes(0.75, 0.70)
    assert small < big  # weaker evidence -> smaller lift


def test_adjust_no_side_lifts(monkeypatch):
    _enable(monkeypatch)
    # NO-held curve: observed NO win rate 0.60 at held price 0.30, model 0.45
    d = {
        "yes_held_prices": [0.70], "yes_actual_probs": [0.5],
        "yes_held_n": [100.0],
        "no_held_prices": [0.30], "no_actual_probs": [0.60],
        "no_held_n": [200.0],
        "buffer": 0.05, "n_trades": 300,
    }
    cal = TailProbabilityCalibrator.from_dict(d)
    out = cal.adjust_p_no(0.45, 0.30)
    assert out > 0.45
    assert out <= 0.60 + 0.05 + 1e-9


def test_adjust_per_asset_uses_asset_curve_and_n(monkeypatch):
    monkeypatch.setenv("MERID_TAIL_CALIBRATION_MIN_ASSET_OBS", "500")
    _enable(monkeypatch)
    d = {
        "yes_held_prices": [0.70], "yes_actual_probs": [0.50],
        "yes_held_n": [5000.0],
        "no_held_prices": [0.30], "no_actual_probs": [0.5],
        "no_held_n": [5000.0],
        "buffer": 0.05, "n_trades": 10000,
        "per_asset": {
            "DOGE": {
                "yes_held_prices": [0.70], "yes_actual_probs": [0.92],
                "yes_held_n": [300.0],
                "no_held_prices": [0.30], "no_actual_probs": [0.5],
                "no_held_n": [300.0],
                "n": 600,
            }
        },
    }
    cal = TailProbabilityCalibrator.from_dict(d)
    # asset curve observed 0.92 vs pooled 0.50 -> DOGE lifts, pooled caps
    doge = cal.adjust_p_yes(0.75, 0.70, asset="DOGE")
    pooled = cal.adjust_p_yes(0.75, 0.70, asset="BTC")
    assert doge > pooled


def test_adjust_probability_bounds_preserved(monkeypatch):
    _enable(monkeypatch)
    cal = TailProbabilityCalibrator.from_dict(_lift_artifact(observed=0.99, n=5000.0))
    out = cal.adjust_p_yes(0.05, 0.70)  # very low model claim
    assert 0.0 <= out <= 1.0
    out2 = cal.adjust_p_yes(0.99, 0.70)
    assert 0.0 <= out2 <= 1.0


# ── serialization round-trip ─────────────────────────────────────────────

def test_to_dict_round_trip_preserves_n(monkeypatch):
    _enable(monkeypatch)
    cal = TailProbabilityCalibrator.from_dict(_lift_artifact())
    cal2 = TailProbabilityCalibrator.from_dict(cal.to_dict())
    assert cal2.yes_held_n == pytest.approx([200.0])
    assert cal2.adjust_p_yes(0.75, 0.70) == pytest.approx(
        cal.adjust_p_yes(0.75, 0.70)
    )


def test_from_trade_analysis_emits_counts():
    trades = [
        {"side": "YES", "action": "buy", "price": "0.70",
         "market_result": "yes" if i % 4 else "no"}
        for i in range(40)
    ] + [
        {"side": "NO", "action": "buy", "price": "0.30",
         "market_result": "no" if i % 4 else "yes"}
        for i in range(40)
    ]
    cal = TailProbabilityCalibrator.from_trade_analysis(trades)
    assert cal.yes_held_n is not None and len(cal.yes_held_n) == len(cal.yes_held_prices)
    assert cal.no_held_n is not None and len(cal.no_held_n) == len(cal.no_held_prices)
    assert all(n >= 1 for n in cal.yes_held_n)


def test_mismatched_n_length_disables_lift(monkeypatch):
    _enable(monkeypatch)
    d = _lift_artifact()
    d["yes_held_n"] = [200.0, 999.0]  # length 2 vs 1 knot -> ignored
    cal = TailProbabilityCalibrator.from_dict(d)
    assert cal.yes_held_n is None
    assert cal.adjust_p_yes(0.75, 0.70) == pytest.approx(0.75)


def test_lift_env_knobs_have_safe_defaults(monkeypatch):
    # defaults must keep lift conservative even if only the flag is set
    for k in ("MERID_RECAL_MIN_NEFF", "MERID_RECAL_LIFT_CAP",
              "MERID_RECAL_PRIOR_K", "MERID_RECAL_LIFT_Z"):
        monkeypatch.delenv(k, raising=False)
    assert TailProbabilityCalibrator._recal_min_neff() == 12.0
    assert TailProbabilityCalibrator._recal_lift_cap() == 0.10
    assert TailProbabilityCalibrator._recal_prior_k() == 8.0
    assert TailProbabilityCalibrator._recal_lift_z() == 1.0
