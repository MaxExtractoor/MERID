"""NO-side tail calibration tests (2026-09-25).

The shipped artifact must carry a REAL per-side NO curve — fit on observed
NO-held outcomes — not the ``1 - p_yes`` dual mirror.  A dual curve makes the
settlement evaluator treat every NO-tail position as uncalibrated
(``no_dual_provisional``), which structurally vetoed every discretionary
salvage exit for NO positions.
"""

import json

import pytest

from merid.event_venues.kalshi.settlement_aligned_exit import (
    SettlementAlignedExitEvaluator,
)
from merid.risk.probability.tail_calibrator import (
    TailProbabilityCalibrator,
    load_tail_calibrator,
)


class TestDualDetection:
    def test_dual_mirror_detected(self):
        # yes 10c -> 0.05, yes 30c -> 0.20 ; dual no curve is the mirror.
        calib = TailProbabilityCalibrator(
            yes_held_prices=[0.10, 0.30],
            yes_actual_probs=[0.05, 0.20],
            no_held_prices=[0.90, 0.70],
            no_actual_probs=[0.95, 0.80],
        )
        assert calib.no_curve_is_dual is True

    def test_real_curve_not_dual(self):
        calib = TailProbabilityCalibrator(
            yes_held_prices=[0.10, 0.30],
            yes_actual_probs=[0.05, 0.20],
            no_held_prices=[0.90, 0.70],
            no_actual_probs=[0.90, 0.75],  # deviates from the mirror
        )
        assert calib.no_curve_is_dual is False

    def test_different_knot_counts_not_dual(self):
        calib = TailProbabilityCalibrator(
            yes_held_prices=[0.10, 0.30, 0.50],
            yes_actual_probs=[0.05, 0.20, 0.50],
            no_held_prices=[0.90, 0.70],
            no_actual_probs=[0.95, 0.80],
        )
        assert calib.no_curve_is_dual is False


class TestShippedArtifact:
    def test_artifact_no_curve_is_real(self):
        calib = load_tail_calibrator()
        assert calib is not None
        assert calib.no_curve_is_dual is False, (
            "data/probability_tail_calibration.json must be re-fit on real "
            "NO-held observations (scripts/refit_tail_calibration.py)"
        )
        assert calib.n_trades >= 200
        assert calib.metadata.get("no_source") == "no_held_observations"

    def test_artifact_curves_monotone_and_bounded(self):
        calib = load_tail_calibrator()
        for xs, ys in (
            (calib.yes_held_prices, calib.yes_actual_probs),
            (calib.no_held_prices, calib.no_actual_probs),
        ):
            assert len(xs) == len(ys) >= 5
            assert xs == sorted(xs)
            assert all(0.0 <= y <= 1.0 for y in ys)
            assert all(0.0 < x < 1.0 for x in xs)

    def test_caps_conservative(self):
        calib = load_tail_calibrator()
        # cap = min(model, observed_wr + buffer): never lifts model prob.
        assert calib.cap_p_no(0.50, 0.30) <= 0.50
        assert calib.cap_p_yes(0.50, 0.30) <= 0.50


class TestApplyTailCalibration:
    def _evaluator(self, calib):
        ev = SettlementAlignedExitEvaluator()
        ev._tail_calibrator = calib
        return ev

    def test_real_no_curve_returns_cap(self):
        calib = TailProbabilityCalibrator(
            yes_held_prices=[0.10, 0.30],
            yes_actual_probs=[0.05, 0.20],
            no_held_prices=[0.25, 0.35],
            no_actual_probs=[0.20, 0.30],
        )
        ev = self._evaluator(calib)
        # NO-held at 30c (tail zone <35c): real cap = min(60, 30+5)=35
        out = ev._apply_tail_calibration(calib, 60, 30, "no")
        assert out == 35

    def test_dual_no_curve_returns_none(self):
        calib = TailProbabilityCalibrator(
            yes_held_prices=[0.10, 0.30],
            yes_actual_probs=[0.05, 0.20],
            no_held_prices=[0.90, 0.70],
            no_actual_probs=[0.95, 0.80],
        )
        assert calib.no_curve_is_dual is True
        ev = self._evaluator(calib)
        assert ev._apply_tail_calibration(calib, 60, 30, "no") is None

    def test_above_floor_passthrough(self):
        calib = TailProbabilityCalibrator(
            yes_held_prices=[0.10],
            yes_actual_probs=[0.05],
            no_held_prices=[0.25],
            no_actual_probs=[0.20],
        )
        ev = self._evaluator(calib)
        # 50c >= 35c floor -> no cap applied
        assert ev._apply_tail_calibration(calib, 60, 50, "no") == 60
