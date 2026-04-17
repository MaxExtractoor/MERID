"""
Unit tests for ``core.merid_metrics`` (canonical Brier / calibration metrics).

Legacy tests imported a shadow ``merid_metrics`` package; the implementation
lives in ``core/merid_metrics.py``.
"""

from __future__ import annotations

import numpy as np
import pytest

from core.merid_metrics import (
    BrierDecomposition,
    BrierResult,
    compute_brier,
    compute_bss,
    brier_decomposition,
    get_merid_metrics,
    plot_reliability_diagram,
)


def _arr(y_true, y_prob) -> tuple[np.ndarray, np.ndarray]:
    return np.asarray(y_true, dtype=float), np.asarray(y_prob, dtype=float)


def _decomp_dict(yt, yp, n_bins: int = 10) -> dict:
    br: BrierResult = brier_decomposition(yt, yp, n_bins=n_bins)
    return br.to_dict()


class TestMurphyBrierRegression:
    """Guards the decomposition path MERID relies on for dashboards and evaluation."""

    def test_brier_decomposition_matches_compute_with_bins(self) -> None:
        """``brier_decomposition()`` must agree with ``compute_with_bins`` (single source of truth)."""
        yt, yp = _arr(
            [0, 0, 1, 1, 0, 1, 0, 1],
            [0.25, 0.35, 0.65, 0.75, 0.45, 0.55, 0.2, 0.8],
        )
        br = brier_decomposition(yt, yp, n_bins=10)
        d = BrierDecomposition.compute_with_bins(yt, yp, n_bins=10)
        assert br.brier_score == pytest.approx(d["brier_score"])
        assert br.reliability == pytest.approx(d["reliability"])
        assert br.resolution == pytest.approx(d["resolution"])
        assert br.uncertainty == pytest.approx(d["uncertainty"])

    def test_murphy_identity_large_sample(self) -> None:
        """BS ≈ REL − RES + UNC (Murphy) should close for large n; catches binning regressions."""
        rng = np.random.default_rng(42)
        n = 2_000
        y_true = rng.integers(0, 2, size=n).astype(float)
        y_prob = rng.uniform(0.01, 0.99, size=n)
        d = BrierDecomposition.compute_with_bins(y_true, y_prob, n_bins=20)
        murphy = d["reliability"] - d["resolution"] + d["uncertainty"]
        assert d["brier_score"] == pytest.approx(murphy, abs=5e-4)


class TestSyntheticEdgeCases:
    """Synthetic forecasts — behaviour checks."""

    def test_perfect_forecasts(self) -> None:
        y_true = [0, 0, 1, 1]
        y_prob = [0.1, 0.2, 0.8, 0.9]
        yt, yp = _arr(y_true, y_prob)
        d = _decomp_dict(yt, yp)
        assert d["brier_score"] < 0.1
        assert d.get("brier_skill_score") is not None and d["brier_skill_score"] > 0.5

    def test_climatology_forecasts(self) -> None:
        y_true = [0, 0, 1, 1]
        baseline = 0.5
        y_prob = [baseline] * 4
        yt, yp = _arr(y_true, y_prob)
        bline = np.full_like(yp, baseline)
        bss = compute_bss(yt, yp, bline)
        assert abs(bss) < 0.001

    def test_worst_case_forecasts(self) -> None:
        y_true = [0, 0, 1, 1]
        y_prob = [0.9, 0.8, 0.2, 0.1]
        yt, yp = _arr(y_true, y_prob)
        d = _decomp_dict(yt, yp)
        assert d["brier_score"] > 0.2
        assert d.get("brier_skill_score") is not None and d["brier_skill_score"] < 0

    def test_decomposition_murphy_identity(self) -> None:
        y_true = [0, 0, 1, 1, 0, 1]
        y_prob = [0.2, 0.3, 0.7, 0.8, 0.4, 0.6]
        yt, yp = _arr(y_true, y_prob)
        bs, rel, res, unc = BrierDecomposition.compute(yt, yp, n_bins=5)
        # Binning / floating noise — implementation logs if mismatch exceeds 1e-10
        assert abs(bs - (rel - res + unc)) < 0.002


class TestMetricProperties:
    """Bounds and identities."""

    def test_brier_score_bounds(self) -> None:
        y_true = [0, 1, 0, 1]
        y_prob = [0.0, 1.0, 0.0, 1.0]
        bs = compute_brier(*_arr(y_true, y_prob))
        assert abs(bs - 0.0) < 0.001

        y_prob_bad = [1.0, 0.0, 1.0, 0.0]
        bs = compute_brier(*_arr(y_true, y_prob_bad))
        assert abs(bs - 1.0) < 0.001

    def test_bss_vs_baseline(self) -> None:
        y_true = [0, 0, 1, 1]
        baseline = 0.5
        y_prob = [0.1, 0.2, 0.8, 0.9]
        yt, yp = _arr(y_true, y_prob)
        bline = np.full_like(yp, baseline)
        bss = compute_bss(yt, yp, bline)
        assert bss > 0.5

        y_prob_clim = [baseline] * 4
        bss = compute_bss(yt, np.asarray(y_prob_clim, dtype=float), bline)
        assert abs(bss) < 0.001

        y_prob_worse = [0.9, 0.8, 0.2, 0.1]
        bss = compute_bss(yt, np.asarray(y_prob_worse, dtype=float), bline)
        assert bss < 0

    def test_symmetry_properties(self) -> None:
        y_true = [0, 1, 0, 1]
        y_prob = [0.2, 0.7, 0.3, 0.8]
        y_true_swapped = [1, 0, 1, 0]
        y_prob_swapped = [1 - p for p in y_prob]
        bs_original = compute_brier(*_arr(y_true, y_prob))
        bs_swapped = compute_brier(
            np.asarray(y_true_swapped, dtype=float),
            np.asarray(y_prob_swapped, dtype=float),
        )
        assert abs(bs_original - bs_swapped) < 0.001


class TestReliabilityDiagram:
    """plot_reliability_diagram returns JSON-serializable bin data."""

    def test_reliability_structure(self) -> None:
        y_true = [0, 0, 1, 1, 0, 1]
        y_prob = [0.2, 0.3, 0.7, 0.8, 0.4, 0.6]
        yt, yp = _arr(y_true, y_prob)
        out = plot_reliability_diagram(yt, yp, n_bins=5)
        assert "bin_centers" in out and "observed_frequencies" in out
        assert len(out["observed_frequencies"]) == len(out["bin_centers"])
        for o in out["observed_frequencies"]:
            assert 0.0 <= o <= 1.0


class TestIntegration:
    """evaluate_model-style path on MERIDMetrics."""

    def test_evaluate_model_raw_keys(self) -> None:
        y_true = [0, 0, 1, 1, 0, 1, 0, 1]
        y_prob = [0.2, 0.3, 0.7, 0.8, 0.4, 0.6, 0.25, 0.75]
        yt, yp = _arr(y_true, y_prob)
        baseline = np.full_like(yp, 0.5)
        m = get_merid_metrics()
        results = m.evaluate_model(yt, yp, baseline=baseline, n_bins=10)
        assert "raw" in results
        raw = results["raw"]
        for key in ("brier_score", "brier_skill_score", "quality_category"):
            assert key in raw


class TestReferenceCsvOptional:
    """Optional reference CSV (not shipped in repo) — skip if absent."""

    def test_optional_weather_csv(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent.parent
        csv_path = root / "weather_forecasts.csv"
        if not csv_path.is_file():
            pytest.skip("weather_forecasts.csv not in repository")
        # Minimal smoke: load and compute Brier if pandas available
        try:
            import pandas as pd
        except ImportError:
            pytest.skip("pandas not installed")
        df = pd.read_csv(csv_path)
        assert len(df) > 0
        # column names vary; skip detailed assertions without a fixed schema
