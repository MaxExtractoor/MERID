"""Promotion-compiler stage tests — identical gate for all five assets.

Uses a synthetic discovery payload; never touches data/decision_audit.db or
the live registry file.
"""

import importlib.util
import os

import pytest


def _load_compiler():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts", "cell_promotion_compiler.py",
    )
    spec = importlib.util.spec_from_file_location(
        "cell_promotion_compiler", path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_compiler = _load_compiler()

ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")


def _bucket(asset, side, plo, phi, tlo, thi, *, n=80, lcb=4.0,
            folds=(5.0, 5.0, 5.0), n21=40.0, m21=8.0, day_share=0.2,
            in_domain=None):
    if in_domain is None:
        in_domain = (20 <= plo and phi <= 90 and 120 <= tlo and thi <= 600)
    return {
        "bucket": f"{asset}|{side}|{plo:02d}-{phi:02d}|t{tlo}_{thi}|cf_taker_ask",
        "n": n, "n_markets": n, "max_day_share": day_share,
        "mean": lcb + 4.0, "median": lcb + 4.0,
        "lcb10": lcb, "lcb10_plus1c": lcb - 1.0,
        "mean_plus2c": lcb + 2.0,
        "folds": list(folds),
        "n_eff_7d": n21 / 2, "n_eff_21d": n21,
        "mean_7d": m21, "mean_21d": m21,
        "in_domain": in_domain,
        "verdict": "PROMOTES",
    }


def _discovery(rows_by_asset):
    return {
        "per_asset": {
            a: {"buckets": rows_by_asset.get(a, []), "status": "x"}
            for a in ASSETS
        }
    }


@pytest.mark.parametrize("asset", ASSETS)
def test_strong_in_domain_bucket_is_pending_feasibility(asset):
    """A statistically clean in-domain bucket can never auto-promote —
    execution feasibility is UNKNOWN, so it caps at CANDIDATE_PENDING_*."""
    disc = _discovery({asset: [_bucket(asset, "no", 40, 50, 120, 300)]})
    cand, rej = _compiler.compile_candidates(disc, {})
    assert len(cand) == 1 and not rej
    row = cand[0]
    assert row["asset"] == asset
    assert row["promotion_status"] == "CANDIDATE_PENDING_EXECUTION_FEASIBILITY"
    assert row["failed_stage"] == "S3_execution_feasibility"
    assert row["fill_feasibility"] == "FILL_FEASIBILITY_UNKNOWN"


@pytest.mark.parametrize("asset", ASSETS)
def test_late_tail_buckets_are_rejected_at_domain_gate(asset):
    """The 0-10c / <120s 'huge counterfactual' cells must never promote."""
    disc = _discovery({
        asset: [
            _bucket(asset, "no", 0, 10, 0, 120, lcb=40.0, in_domain=False),
            _bucket(asset, "yes", 90, 100, 300, 600, lcb=20.0, in_domain=False),
        ]
    })
    cand, rej = _compiler.compile_candidates(disc, {})
    assert not cand and len(rej) == 2
    assert all(r["failed_stage"] == "S2_domain" for r in rej)
    assert all(r["promotion_status"] == "REJECTED" for r in rej)


@pytest.mark.parametrize("asset", ASSETS)
def test_weak_lcb_bucket_rejected_at_statistics(asset):
    disc = _discovery({
        asset: [_bucket(asset, "no", 40, 50, 120, 300, lcb=-1.0)]
    })
    cand, rej = _compiler.compile_candidates(disc, {})
    assert not cand and rej[0]["failed_stage"] == "S1_statistical"


@pytest.mark.parametrize("asset", ASSETS)
def test_thin_recent_evidence_marks_pending_recency(asset):
    """S1/S2 pass but weak 21d decayed evidence -> PENDING_RECENCY_*, still
    not deployable."""
    disc = _discovery({
        asset: [_bucket(asset, "no", 40, 50, 120, 300, n21=2.0, m21=-1.0)]
    })
    cand, rej = _compiler.compile_candidates(disc, {})
    assert len(cand) == 1
    assert cand[0]["promotion_status"] == "CANDIDATE_PENDING_RECENCY_AND_CALIBRATION"


@pytest.mark.parametrize("asset", ASSETS)
def test_already_live_cell_flagged(asset):
    disc = _discovery({asset: [_bucket(asset, "no", 40, 50, 120, 300)]})
    live = {asset: [f"{asset.lower()}_no_40_50_t120_300"]}
    cand, _rej = _compiler.compile_candidates(disc, live)
    assert cand[0]["already_live"] is True


@pytest.mark.parametrize("asset", ASSETS)
def test_small_sample_never_promotes(asset):
    disc = _discovery({
        asset: [_bucket(asset, "no", 40, 50, 120, 300, n=20, lcb=9.0)]
    })
    cand, rej = _compiler.compile_candidates(disc, {})
    assert not cand and rej[0]["failed_stage"] == "S1_statistical"
