"""Unit tests for the cell-aware live evidence policy (evidence_policy.py).

Covers bucket boundaries, cell-key generation, hierarchical fallback,
weighted posterior/LCB economics, hard blocks on matched toxic cells,
sparse-cell uplift + escape-lane gating, stale/empty evidence behavior,
uniform behavior across all five live assets, and the escape daily cap.
No live order submission occurs in any test.
"""
from __future__ import annotations

import json
import math
import os
import time

import pytest

from merid.prediction import evidence_policy as ep


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _cell(w, l, n_eff=None, n_raw=None, entry=50.0, recent_w=None, recent_l=None):
    """Synthetic finest-grain cell dict as stored in the v2 artifact."""
    n_eff = float(w + l) if n_eff is None else float(n_eff)
    return {
        "w": float(w), "l": float(l), "n_eff": n_eff,
        "n_raw": int(n_raw if n_raw is not None else w + l),
        "n_markets": int(n_raw if n_raw is not None else w + l),
        "entry_wsum": float(entry) * n_eff,
        "recent_w": float(w if recent_w is None else recent_w),
        "recent_l": float(l if recent_l is None else recent_l),
        "recent_n": int((w if recent_w is None else recent_w)
                        + (l if recent_l is None else recent_l)),
    }


def _artifact(cells, generated_at=None):
    return {
        "version": 2,
        "generated_at": time.time() if generated_at is None else generated_at,
        "window_hours": 48.0,
        "halflife_days_primary": 7,
        "cells": {"7": cells},
    }


def _eval(cells, **kw):
    args = dict(
        asset="SOL", side="no", entry_price_cents=35.0, tte_seconds=450.0,
        fee_frac=0.0, margin_frac=0.03, net_edge_cents=5.0,
    )
    args.update(kw)
    return ep.evaluate(_artifact(cells), **args)


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    """Deterministic env: default knobs, no real escape-cap file."""
    monkeypatch.setenv(
        "MERID_EVIDENCE_ESCAPE_STATE_PATH", str(tmp_path / "escape.json")
    )
    # Sparse-severe tier is an explicit per-test opt-in below; the repo .env
    # enables it for production, which must not leak into these fixtures.
    # Same for hard-block mode: .env runs challenge; these tests assert the
    # veto-mode verdict unless they opt in explicitly.
    monkeypatch.setenv("MERID_EVIDENCE_HARD_SPARSE_TIER", "0")
    monkeypatch.setenv("MERID_EVIDENCE_HARD_SPARSE_EV_C", "10.0")
    monkeypatch.setenv("MERID_EVIDENCE_HARD_BLOCK_MODE", "veto")
    # 2026-10-16: .env pins an evidence epoch for production (pre-epoch rows
    # cannot sustain a hard block); synthetic cells carry no post-epoch
    # mass, so the epoch must default off here — epoch tests opt in below.
    # Same for the rehab-probe state file: never touch production state.
    monkeypatch.setenv("MERID_EVIDENCE_EPOCH_TS", "0")
    monkeypatch.setenv(
        "MERID_EVIDENCE_REHAB_STATE_PATH", str(tmp_path / "rehab.json")
    )
    # 2026-10-17: pinned-fav lane durable counter must never read
    # production state.
    monkeypatch.setenv(
        "MERID_PINNED_FAV_STATE_PATH", str(tmp_path / "pinned_fav.json")
    )
    # 2026-10-22: bounded-lane envs must not leak from the production .env —
    # the lane-floor substitution changes the sparse/empty/challenge bound
    # whenever the candidate sits inside an armed band, and .env arms
    # drift/cheap/pf in production.  Lane tests opt in explicitly below.
    monkeypatch.setenv("MERID_DRIFT_LANE_ENABLED", "0")
    monkeypatch.setenv("MERID_CHEAP_NO_LANE_ENABLED", "0")
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "0")
    monkeypatch.setenv(
        "MERID_DRIFT_LANE_STATE_PATH", str(tmp_path / "drift.json")
    )
    yield


# --------------------------------------------------------------------------
# Bucket boundaries
# --------------------------------------------------------------------------

def test_price_bucket_boundaries():
    assert ep.price_bucket(1) == "01-09"
    assert ep.price_bucket(9) == "01-09"
    assert ep.price_bucket(10) == "10-24"
    assert ep.price_bucket(24) == "10-24"
    assert ep.price_bucket(25) == "25-49"
    assert ep.price_bucket(49) == "25-49"
    assert ep.price_bucket(50) == "50-74"
    assert ep.price_bucket(74) == "50-74"
    assert ep.price_bucket(75) == "75-89"
    assert ep.price_bucket(89) == "75-89"
    assert ep.price_bucket(90) == "90-100"
    assert ep.price_bucket(100) == "90-100"
    assert ep.price_bucket(None) == "unknown"


def test_tte_bucket_boundaries():
    assert ep.tte_bucket(900) == "early"
    assert ep.tte_bucket(601) == "early"
    assert ep.tte_bucket(600) == "mid"
    assert ep.tte_bucket(301) == "mid"
    assert ep.tte_bucket(300) == "late"
    assert ep.tte_bucket(121) == "late"
    assert ep.tte_bucket(120) == "final"
    assert ep.tte_bucket(30) == "final"
    assert ep.tte_bucket(None) == "unknown"


def test_cell_key_format():
    assert ep.cell_key("sol", "NO", 35, 450) == "SOL|no|25-49|mid"
    assert ep.cell_key("BTC", "yes", 77.0, 200.0) == "BTC|yes|75-89|late"


# --------------------------------------------------------------------------
# Hierarchical fallback + posterior
# --------------------------------------------------------------------------

def test_exact_cell_used_when_dense():
    cells = {
        "SOL|no|25-49|mid": _cell(w=40, l=10, entry=35),
        "SOL|no|25-49|early": _cell(w=5, l=45, entry=35),
    }
    d = _eval(cells)
    assert d.evidence_level_used == "asset_side_price_tte"
    assert d.effective_independent_n == pytest.approx(50.0)
    assert d.wins_weighted == pytest.approx(40.0)


def test_falls_back_to_asset_side_price_when_cell_sparse():
    cells = {
        "SOL|no|25-49|mid": _cell(w=2, l=1, entry=35),          # n_eff=3 < 8
        "SOL|no|25-49|early": _cell(w=30, l=10, entry=35),      # price level dense
    }
    d = _eval(cells)
    assert d.evidence_level_used == "asset_side_price"
    assert d.fallback_reason is not None
    assert "fell back" in d.fallback_reason


def test_falls_back_to_side_level_then_sparse():
    # Only price-mismatched evidence exists -> no scored level -> the sparse
    # path gates on the model edge uplift rather than a mismatched posterior.
    cells = {"SOL|no|50-74|late": _cell(w=8, l=12, entry=60)}
    d = _eval(cells, entry_price_cents=35.0)
    assert d.evidence_level_used == "none"
    assert d.code.startswith("SPARSE_MATCHED")
    # Cross-asset same side+price+tte evidence is usable as a scored level.
    d2 = _eval({"BTC|no|25-49|mid": _cell(w=8, l=12, entry=35)}, asset="SOL")
    assert d2.evidence_level_used == "side_price_tte"


def test_sparse_cell_posterior_shrinks_to_parent():
    # Exact cell sparse-ish but usable; parent dense and poor.
    cells = {
        "SOL|no|25-49|mid": _cell(w=9, l=1, entry=35),
        "SOL|no|50-74|mid": _cell(w=20, l=60, entry=62),
    }
    d = _eval(cells)
    # Used level = exact cell (n_eff=10).  Parent prior (asset_side_price,
    # wr=0.25) must pull the posterior well below the cell's raw 90% wr.
    assert d.posterior_mean < 0.75
    assert d.parent_level in ("asset_side_price", "asset_side_tte", "asset_side")


def test_posterior_lcb_is_conservative():
    cells = {"SOL|no|25-49|mid": _cell(w=9, l=1, entry=35)}
    d = _eval(cells)
    assert d.posterior_lcb < d.posterior_mean
    assert 0.0 <= d.posterior_lcb <= 1.0
    assert d.posterior_std > 0.0


# --------------------------------------------------------------------------
# Evidence-as-reserve semantics
# --------------------------------------------------------------------------

def test_pooled_toxic_cohort_does_not_block_cheap_cell():
    # SOL NO history is poor around ~63c but the candidate is at 35c:
    # LCB win prob vs 35c entry is positive EV, so no block.
    cells = {
        "SOL|no|50-74|mid": _cell(w=30, l=70, entry=63),   # pooled ~30% wr
        "SOL|no|25-49|early": _cell(w=3, l=1, entry=30),
    }
    d = _eval(cells, entry_price_cents=35.0)
    assert d.code != "MATCHING_TOXIC_CELL"
    assert d.allowed  # sparse -> escape lane required, not denied
    assert d.escape_required


def test_dense_toxic_cell_hard_blocks():
    cells = {
        "XRP|yes|75-89|late": _cell(w=10, l=90, entry=77),
        "XRP|yes|75-89|mid": _cell(w=4, l=10, entry=77),
    }
    d = _eval(cells, asset="XRP", side="yes", entry_price_cents=77.0,
              tte_seconds=200.0)
    assert not d.allowed
    assert d.code == "MATCHING_TOXIC_CELL"
    assert d.matching_hard_block
    assert d.hard_block_level == "asset_side_price_tte"


def test_sparse_severe_tier_hard_blocks(monkeypatch):
    """2026-10-15: the sparse-severe tier is the production eligibility gate —
    a matched cell with n_eff>=8 and LCB net EV below the severe floor is a
    hard block even under the unreachable dense n_eff bar."""
    monkeypatch.setenv("MERID_EVIDENCE_HARD_SPARSE_TIER", "1")
    monkeypatch.setenv("MERID_EVIDENCE_HARD_SPARSE_EV_C", "6.0")
    # n_eff=12, wr ~14% at ~62c avg entry -> hb_ev ~ -50c: severely toxic.
    cells = {"XRP|yes|50-74|mid": _cell(w=2, l=12, entry=62)}
    d = _eval(cells, asset="XRP", side="yes", entry_price_cents=62.0,
              tte_seconds=400.0)
    assert not d.allowed
    assert d.code == "MATCHING_TOXIC_CELL"
    assert d.matching_hard_block
    assert d.hard_block_level == "asset_side_price_tte"


def test_sparse_severe_tier_respects_floor_and_recent_contradiction(
    monkeypatch,
):
    """Cells between the dense floor and the severe floor, and cells whose
    recent window contradicts the stale posterior, are not hard-blocked."""
    monkeypatch.setenv("MERID_EVIDENCE_HARD_SPARSE_TIER", "1")
    monkeypatch.setenv("MERID_EVIDENCE_HARD_SPARSE_EV_C", "6.0")
    # Mild/non-toxic: 75% wr at 62c -> the LCB-based hb_ev stays well above
    # the -6c severe floor -> margin path, not a hard block.
    mild = {"XRP|yes|50-74|mid": _cell(w=9, l=3, entry=62)}
    d = _eval(mild, asset="XRP", side="yes", entry_price_cents=62.0,
              tte_seconds=400.0)
    assert d.code != "MATCHING_TOXIC_CELL"
    assert not d.matching_hard_block
    # Severe posterior but the recent window wins above breakeven -> spared.
    contra = {"XRP|yes|50-74|mid": _cell(w=2, l=12, entry=62,
                                         recent_w=20, recent_l=4)}
    d = _eval(contra, asset="XRP", side="yes", entry_price_cents=62.0,
              tte_seconds=400.0)
    assert d.code != "MATCHING_TOXIC_CELL"
    assert not d.matching_hard_block


def test_toxic_cell_needs_minimum_samples(monkeypatch):
    monkeypatch.setenv("MERID_EVIDENCE_HARD_MIN_NEFF", "50")
    # Same toxic ratio but only n_eff=40 -> not hard-blockable; falls to
    # soft penalty instead.
    cells = {"XRP|yes|75-89|late": _cell(w=8, l=32, entry=77)}
    d = _eval(cells, asset="XRP", side="yes", entry_price_cents=77.0,
              tte_seconds=200.0)
    assert d.code != "MATCHING_TOXIC_CELL"
    assert not d.allowed  # LCB EV still fails -> soft deny, not a free pass
    # 2026-09-29: adaptive states split the old flat insufficiency into
    # SOFT_PENALTY / CHALLENGE denies; still a deny without enough edge.
    assert d.code in (
        "CELL_EVIDENCE_INSUFFICIENT",
        "SOFT_PENALTY_INSUFFICIENT",
        "CHALLENGE_INSUFFICIENT",
    )


def test_recent_improvement_downgrades_hard_block():
    # Dense toxic history but the recent-window sub-aggregate has flipped
    # above break-even -> drift check suppresses the hard block.
    cells = {
        "XRP|yes|75-89|late": _cell(w=10, l=90, entry=77,
                                    recent_w=9, recent_l=1),
    }
    d = _eval(cells, asset="XRP", side="yes", entry_price_cents=77.0,
              tte_seconds=200.0)
    assert d.code != "MATCHING_TOXIC_CELL"


def test_sparse_cell_uplift_and_escape_flag():
    cells = {"SOL|no|25-49|mid": _cell(w=9, l=1, entry=35)}
    d = _eval(cells)
    assert d.sparse_uplift_cents > 0.0
    assert d.required_margin_cents == pytest.approx(3.0 + d.sparse_uplift_cents)
    assert d.escape_required


def test_dense_cell_no_uplift_no_escape(monkeypatch):
    monkeypatch.setenv("MERID_EVIDENCE_SPARSE_FULL_NEFF", "50")
    cells = {"SOL|no|25-49|mid": _cell(w=45, l=15, entry=35)}
    d = _eval(cells)
    assert d.sparse_uplift_cents == 0.0
    assert not d.escape_required
    assert d.allowed
    assert d.code == "CELL_EVIDENCE_PASS"


def test_lcb_ev_scored_at_candidate_price():
    # Same posterior, cheaper executable price -> higher LCB EV.
    cells = {"SOL|no|25-49|mid": _cell(w=30, l=30, entry=50)}
    d35 = _eval(cells, entry_price_cents=35.0)
    assert d35.lcb_net_ev_cents > 0
    # No price-matched cell at 60c -> sparse path, no posterior EV bound.
    d60 = _eval(cells, entry_price_cents=60.0)
    assert d60.code.startswith("SPARSE_MATCHED")


def test_empty_evidence_requires_uplift_on_model_edge():
    d = _eval({}, net_edge_cents=10.0)
    assert d.code == "EVIDENCE_EMPTY_PASS" and d.allowed and d.escape_required
    d2 = _eval({}, net_edge_cents=0.5)
    assert d2.code == "EVIDENCE_EMPTY_INSUFFICIENT" and not d2.allowed


def test_no_evidence_artifact_cells_key_missing():
    d = ep.evaluate(
        {"version": 1, "generated_at": time.time(), "assets": {}},
        "SOL", "no", 35.0, 450.0, 0.0, 0.03, 5.0,
    )
    assert d.code in ("EVIDENCE_EMPTY_PASS", "EVIDENCE_EMPTY_INSUFFICIENT")


def test_stale_evidence_cannot_hard_block(monkeypatch):
    monkeypatch.setenv("MERID_EVIDENCE_STALE_S", "60")
    cells = {"XRP|yes|75-89|late": _cell(w=10, l=90, entry=77)}
    art = _artifact(cells, generated_at=time.time() - 3600)
    d = ep.evaluate(art, "XRP", "yes", 77.0, 200.0, 0.0, 0.03, 5.0)
    assert d.code != "MATCHING_TOXIC_CELL"
    assert d.evidence_stale


def test_none_price_skips_gate():
    cells = {"SOL|no|25-49|mid": _cell(w=10, l=90, entry=35)}
    d = _eval(cells, entry_price_cents=None)
    assert d.allowed and d.code == "NO_EXECUTABLE_PRICE"


# --------------------------------------------------------------------------
# Escape lane + daily cap
# --------------------------------------------------------------------------

def test_escape_lane_disabled_denies_sparse_pass(monkeypatch):
    monkeypatch.setenv("MERID_EVIDENCE_ESCAPE_LANE", "0")
    cells = {"SOL|no|25-49|mid": _cell(w=9, l=1, entry=35)}
    d = _eval(cells)
    assert not d.allowed and d.code == "ESCAPE_LANE_DISABLED"


def test_escape_cap_exhausted_denies(monkeypatch, tmp_path):
    # Pin the cap — .env overrides (e.g. 24) must not leak into this test.
    monkeypatch.setenv("MERID_EVIDENCE_ESCAPE_DAILY_MAX", "12")
    path = tmp_path / "escape.json"
    today = time.strftime("%Y-%m-%d", time.gmtime())
    path.write_text(json.dumps({"date": today, "count": 12}))
    cells = {"SOL|no|25-49|mid": _cell(w=9, l=1, entry=35)}
    d = _eval(cells)
    assert not d.allowed and d.code == "ESCAPE_CAP_EXHAUSTED"


def test_escape_counter_roundtrip(tmp_path):
    p = str(tmp_path / "esc.json")
    assert ep.escape_fills_today(p) == 0
    assert ep.record_escape_submission(p) == 1
    assert ep.record_escape_submission(p) == 2
    assert ep.escape_fills_today(p) == 2


# --------------------------------------------------------------------------
# Uniform behavior across assets + telemetry surface
# --------------------------------------------------------------------------

@pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP", "DOGE"])
def test_uniform_behavior_across_assets(asset):
    cells = {f"{asset}|no|25-49|mid": _cell(w=9, l=1, entry=35)}
    d = _eval(cells, asset=asset)
    assert d.evidence_level_used == "asset_side_price_tte"
    assert d.allowed and d.escape_required


def test_detail_telemetry_fields():
    cells = {"SOL|no|25-49|mid": _cell(w=20, l=10, entry=35)}
    d = _eval(cells)
    det = d.detail()
    for key in (
        "evidence_policy_version", "cell_key", "evidence_level_used",
        "effective_independent_n", "wins_weighted", "losses_weighted",
        "posterior_mean", "posterior_lcb", "lcb_net_ev_cents",
        "required_margin_cents", "sparse_uplift_cents",
        "matching_hard_block", "escape_required", "evidence_stale",
        "code",
    ):
        assert key in det, key
    assert det["evidence_policy_version"] == "cell_aware_v1"
    assert det["cell_key"] == "SOL|no|25-49|mid"


# --------------------------------------------------------------------------
# Aggregation math (builder semantics): ticker normalization
# --------------------------------------------------------------------------

def test_ticker_normalized_cell_counts():
    # A cell whose raw count is inflated by repeated observations of one
    # market must expose n_eff ~ markets, not rows.  Here: 50 raw rows,
    # all wins, but n_eff=1 (one market) -> posterior barely moves, uplift max.
    cells = {
        "SOL|no|25-49|mid": _cell(w=1.0, l=0.0, n_eff=1.0, n_raw=50,
                                  entry=35),
        "SOL|no|50-74|mid": _cell(w=40, l=40, entry=60),
    }
    d = _eval(cells)
    # n_eff=1 < MIN_CELL_NEFF at every price-matched level -> sparse path;
    # the single-market observation cannot clear the uncertainty reserve.
    assert d.evidence_level_used == "none"
    assert d.code.startswith("SPARSE_MATCHED")
    assert d.cell_n_eff == pytest.approx(1.0)
    assert d.sparse_uplift_cents == pytest.approx(ep.sparse_uplift_max_c())


# --------------------------------------------------------------------------
# Adaptive states (2026-09-29): CHALLENGE_ELIGIBLE / SOFT_PENALTY replace the
# flat permanent block for matched-but-insufficient cells.
# --------------------------------------------------------------------------

def test_challenge_eligible_on_recent_contradiction():
    # Dense matched cell is historically poor (25% wr vs 77c entry) but the
    # recent-window sub-aggregate has flipped above break-even -> the stale
    # prior gets a bounded challenge instead of a permanent block.
    cells = {
        "SOL|no|50-74|mid": _cell(w=10, l=30, n_eff=40, entry=65,
                                  recent_w=6, recent_l=1),
    }
    d = _eval(cells, entry_price_cents=65.0, tte_seconds=450.0,
              net_edge_cents=5.0)
    assert d.code == "CHALLENGE_ELIGIBLE"
    assert d.allowed
    assert d.escape_required  # bounded lane: post-only, 1 contract, daily cap


def test_challenge_insufficient_when_model_edge_thin():
    cells = {
        "SOL|no|50-74|mid": _cell(w=10, l=30, n_eff=40, entry=65,
                                  recent_w=6, recent_l=1),
    }
    # req_margin ~= 3.0 + small uplift; 1.0c model edge cannot clear it.
    d = _eval(cells, entry_price_cents=65.0, tte_seconds=450.0,
              net_edge_cents=1.0)
    assert d.code == "CHALLENGE_INSUFFICIENT"
    assert not d.allowed


def test_soft_penalty_pass_requires_elevated_edge():
    # Same insufficient matched cell but recent outcomes do NOT contradict
    # the prior (recent wr stays below the 65c break-even).  Admission needs
    # margin + uplift + soft_penalty_extra on the model edge.
    cells = {
        "SOL|no|50-74|mid": _cell(w=10, l=30, n_eff=40, entry=65,
                                  recent_w=1, recent_l=6),
    }
    d = _eval(cells, entry_price_cents=65.0, tte_seconds=450.0,
              net_edge_cents=9.0)
    assert d.code == "SOFT_PENALTY_PASS"
    assert d.allowed and d.escape_required
    assert d.required_margin_cents > 3.0  # elevated above plain margin+uplift


def test_soft_penalty_insufficient_below_elevated_edge():
    cells = {
        "SOL|no|50-74|mid": _cell(w=10, l=30, n_eff=40, entry=65,
                                  recent_w=1, recent_l=6),
    }
    d = _eval(cells, entry_price_cents=65.0, tte_seconds=450.0,
              net_edge_cents=5.0)
    assert d.code == "SOFT_PENALTY_INSUFFICIENT"
    assert not d.allowed


def test_adaptive_states_kill_switch_restores_flat_block(monkeypatch):
    monkeypatch.setenv("MERID_EVIDENCE_ADAPTIVE_STATES", "0")
    cells = {
        "SOL|no|50-74|mid": _cell(w=10, l=30, n_eff=40, entry=65,
                                  recent_w=6, recent_l=1),
    }
    d = _eval(cells, entry_price_cents=65.0, tte_seconds=450.0,
              net_edge_cents=9.0)
    assert d.code == "CELL_EVIDENCE_INSUFFICIENT"
    assert not d.allowed


def test_toxic_cell_still_hard_blocks_despite_adaptive():
    # n_eff >= 50, deeply negative LCB EV, recent outcomes agree with the
    # toxic prior -> permanent hard block; no challenge path.
    cells = {
        "SOL|no|75-89|late": _cell(w=10, l=70, n_eff=80, entry=80,
                                   recent_w=1, recent_l=9),
    }
    d = _eval(cells, entry_price_cents=80.0, tte_seconds=200.0,
              net_edge_cents=9.0)
    assert d.code == "MATCHING_TOXIC_CELL"
    assert not d.allowed

def test_calibration_gap_reserve(monkeypatch):
    """FIX 12: the measured overconfidence of the quoting bin becomes a
    reserve charge; underconfident bins charge nothing; sparse bins fall
    back to positive asset mean_bias; cap and kill-switch bind."""
    monkeypatch.delenv("MERID_CALIBRATION_GAP_RESERVE", raising=False)
    monkeypatch.delenv("MERID_CALIBRATION_GAP_MIN_BIN_N", raising=False)
    monkeypatch.delenv("MERID_CALIBRATION_GAP_MAX", raising=False)
    monkeypatch.delenv("MERID_CALIBRATION_GAP_POOL_PRIOR_K", raising=False)
    ev = {
        "calibration_monitor": {
            "ETH": {
                "n": 600,
                "mean_bias": 0.02,
                "bins": {
                    "3": {"n": 120, "mean_p": 0.38, "wr": 0.33},  # +0.05 gap
                    "6": {"n": 80, "mean_p": 0.65, "wr": 0.68},   # underconf.
                    "8": {"n": 10, "mean_p": 0.85, "wr": 0.40},   # sparse
                },
            },
            "BTC": {"n": 500, "mean_bias": -0.07, "bins": {}},
        }
    }
    assert ep.calibration_gap_frac(ev, "ETH", 0.35) == pytest.approx(0.05)
    # Underconfident bin -> zero charge.
    assert ep.calibration_gap_frac(ev, "ETH", 0.65) == 0.0
    # Sparse favorite bin -> pooled favorite-region gap (the sparse bin is
    # the only populated favorite bin: gap 0.45 -> capped at the 0.15 max).
    assert ep.calibration_gap_frac(ev, "ETH", 0.85) == pytest.approx(0.15)
    # Sparse mid-range bin -> shrunk pooled non-favorite gap, not asset
    # mean_bias: (0.05*120 + (-0.03)*80) / (200 + prior_k=20) = 0.0164.
    assert ep.calibration_gap_frac(ev, "ETH", 0.45) == pytest.approx(0.0164, abs=1e-3)
    # Negative-bias asset -> nothing to charge anywhere.
    assert ep.calibration_gap_frac(ev, "BTC", 0.35) == 0.0
    # 2026-10-21 (live monitor shape): an asset whose positive mean_bias is
    # concentrated in the favorite region must not smear that charge onto
    # unmeasured mid-range quotes.  DOGE below mirrors the live artifact:
    # favorites overconfident (settled 0.42-0.58 vs claimed ~0.9), sparse
    # non-favorite bins net underconfident -> favorites still pay the cap,
    # mid-range pays ~zero.
    ev["calibration_monitor"]["DOGE"] = {
        "n": 60, "mean_bias": 0.20,
        "bins": {
            "0": {"n": 7, "mean_p": 0.05, "wr": 0.14},   # underconf.
            "4": {"n": 3, "mean_p": 0.45, "wr": 0.67},   # underconf.
            "8": {"n": 30, "mean_p": 0.89, "wr": 0.50},  # +0.39 measured
            "9": {"n": 20, "mean_p": 0.93, "wr": 0.75},  # +0.18 measured
        },
    }
    # Sparse mid-range bin pools only non-favorite bins:
    # (7*-0.09 + 3*-0.22)/10 = -0.129 -> positive-only clamp -> 0.
    assert ep.calibration_gap_frac(ev, "DOGE", 0.45) == 0.0
    # Bin 9 is populated (n=20 < min_n=30 -> sparse) so the favorite quote
    # pools the region: (30*0.39 + 20*0.18)/(50+20) = 0.2186 -> cap 0.15.
    assert ep.calibration_gap_frac(ev, "DOGE", 0.95) == pytest.approx(0.15)
    # A denser favorite region pools to its measured gap, still capped.
    ev["calibration_monitor"]["DOGE"]["bins"]["9"]["n"] = 200
    assert ep.calibration_gap_frac(ev, "DOGE", 0.85) == pytest.approx(0.15)
    # Missing asset/monitor/None -> no charge (fail-open on measurement).
    assert ep.calibration_gap_frac(ev, "SOL", 0.35) == 0.0
    assert ep.calibration_gap_frac(ev, "ETH", None) == 0.0
    assert ep.calibration_gap_frac({}, "ETH", 0.35) == 0.0
    # Cap binds on extreme measured gaps.
    monkeypatch.setenv("MERID_CALIBRATION_GAP_MAX", "0.03")
    assert ep.calibration_gap_frac(ev, "ETH", 0.35) == pytest.approx(0.03)
    monkeypatch.delenv("MERID_CALIBRATION_GAP_MAX")
    # Kill switch restores the pre-charge behavior entirely.
    monkeypatch.setenv("MERID_CALIBRATION_GAP_RESERVE", "0")
    assert ep.calibration_gap_frac(ev, "ETH", 0.35) == 0.0


def test_implementation_shortfall_reserve(monkeypatch):
    """FIX 13: the measured fill-vs-decision-price gap becomes a reserve —
    exact cohort -> asset rollup -> global -> static prior; negative Q75
    (price improvement) earns no credit; cap and kill-switch bind."""
    for k in (
        "MERID_IMPL_SHORTFALL_RESERVE", "MERID_IMPL_SHORTFALL_MIN_N",
        "MERID_IMPL_SHORTFALL_CAP_CENTS", "MERID_IMPL_SHORTFALL_PRIOR_CENTS",
    ):
        monkeypatch.delenv(k, raising=False)
    ev = {
        "implementation_shortfall": {
            "by_basis": {
                "XRP|no|bid": {"n": 40, "mean_cents": 1.2, "q75_cents": 6.0},
                "XRP|*|bid": {"n": 60, "mean_cents": 1.0, "q75_cents": 4.5},
                "ETH|*|ask": {"n": 30, "mean_cents": -0.8, "q75_cents": -2.0},
                "*|*|ask": {"n": 200, "mean_cents": 0.4, "q75_cents": 2.0},
                "SOL|yes|bid": {"n": 3, "mean_cents": 9.0, "q75_cents": 12.0},
            }
        }
    }
    # Exact cohort measured -> charge the Q75.
    assert ep.implementation_shortfall_cents(
        ev, "XRP", "no", "bid"
    ) == pytest.approx(6.0)
    # Missing side falls back to the asset rollup, then global.
    assert ep.implementation_shortfall_cents(
        ev, "XRP", "yes", "bid"
    ) == pytest.approx(4.5)
    assert ep.implementation_shortfall_cents(
        ev, "BTC", "yes", "ask"
    ) == pytest.approx(2.0)
    # Sparse exact cohort falls through to asset/global, not its own n=3.
    assert ep.implementation_shortfall_cents(
        ev, "SOL", "yes", "bid"
    ) == pytest.approx(1.0)  # no SOL rollup/global bid -> static prior
    # Negative measured Q75 (fills arrive under decision price) floors at 0.
    assert ep.implementation_shortfall_cents(ev, "ETH", "no", "ask") == 0.0
    # No block at all -> static prior.
    assert ep.implementation_shortfall_cents({}, "ETH", "no", "ask") == 1.0
    assert ep.implementation_shortfall_cents(
        None, "ETH", "no", "ask"
    ) == 1.0
    # fill_quality.jsonl measurement merges as max (a cost reserve is
    # conservative): log beats an absent artifact, loses to a larger one.
    assert ep.implementation_shortfall_cents(
        {}, "XRP", "no", "bid", fill_quality_meas=4.0
    ) == pytest.approx(4.0)
    assert ep.implementation_shortfall_cents(
        ev, "XRP", "no", "bid", fill_quality_meas=4.0
    ) == pytest.approx(6.0)
    assert ep.implementation_shortfall_cents(
        ev, "XRP", "no", "bid", fill_quality_meas=9.0
    ) == pytest.approx(9.0)
    # Cap binds on extreme measured gaps.
    monkeypatch.setenv("MERID_IMPL_SHORTFALL_CAP_CENTS", "3.0")
    assert ep.implementation_shortfall_cents(
        ev, "XRP", "no", "bid"
    ) == pytest.approx(3.0)
    monkeypatch.delenv("MERID_IMPL_SHORTFALL_CAP_CENTS")
    # Kill switch.
    monkeypatch.setenv("MERID_IMPL_SHORTFALL_RESERVE", "0")
    assert ep.implementation_shortfall_cents(ev, "XRP", "no", "bid") == 0.0

# --------------------------------------------------------------------------
# Evidence epoch + rehabilitation probes (2026-10-16 toxic-cell reset)
# --------------------------------------------------------------------------

def _epoch_cell(w, l, w_post=None, l_post=None, entry=50.0, **kw):
    """Synthetic cell with post-epoch mass (defaults: all mass post-epoch)."""
    c = _cell(w, l, entry=entry, **kw)
    wp = w if w_post is None else w_post
    lp = l if l_post is None else l_post
    c.update({
        "w_post": float(wp), "l_post": float(lp),
        "n_eff_post": float(wp + lp),
        "n_raw_post": int(wp + lp),
        "entry_wsum_post": float(entry) * float(wp + lp),
    })
    return c


def test_build_cells_post_epoch_split():
    """Rows settled before the epoch land in legacy mass only; rows at/after
    the boundary land in the post-epoch mass a hard block must use."""
    now = time.time()
    rows = [
        {"asset": "SOL", "side": "no", "ticker": "T1", "entry_cents": 35,
         "settled_yes": 0, "settled_at": now - 7200, "seconds_to_close": 400,
         "decision_ts": now - 7500},
        {"asset": "SOL", "side": "no", "ticker": "T2", "entry_cents": 36,
         "settled_yes": 0, "settled_at": now - 3600, "seconds_to_close": 400,
         "decision_ts": now - 3900},
        # Settled post-epoch but DECIDED pre-epoch: old-regime evidence must
        # not count toward the current-epoch hard-block mass.
        {"asset": "SOL", "side": "no", "ticker": "T3", "entry_cents": 37,
         "settled_yes": 0, "settled_at": now - 60, "seconds_to_close": 400,
         "decision_ts": now - 2000},
        {"asset": "SOL", "side": "no", "ticker": "T4", "entry_cents": 38,
         "settled_yes": 0, "settled_at": now - 30, "seconds_to_close": 400,
         "decision_ts": now - 100},
    ]
    epoch = now - 1800
    cells = ep.build_cells(rows, 7.0, now=now, epoch_ts=epoch)
    c = cells["SOL|no|25-49|mid"]
    assert c["n_raw"] == 4
    # Only the post-epoch *decision* counts: T3 settled post-epoch but was
    # decided before it and must not carry current-code standing.
    assert c["n_raw_post"] == 1
    assert c["n_eff_post"] > 0 and c["n_eff_post"] < c["n_eff"]
    # side=no + settled_yes=0 -> win: post mass lands on w_post, not l_post.
    assert c["w_post"] == pytest.approx(c["n_eff_post"])
    assert c["l_post"] == pytest.approx(0.0)


def test_epoch_unset_post_fields_track_full():
    """With every row post-epoch (epoch=0), post fields mirror the cell."""
    now = time.time()
    rows = [
        {"asset": "BTC", "side": "yes", "ticker": "T1", "entry_cents": 60,
         "settled_yes": 1, "settled_at": now - 100, "seconds_to_close": 500},
    ]
    cells = ep.build_cells(rows, 7.0, now=now, epoch_ts=0.0)
    c = cells["BTC|yes|50-74|mid"]
    assert c["n_eff_post"] == pytest.approx(c["n_eff"])
    assert c["w_post"] == pytest.approx(c["w"])


def test_pre_epoch_evidence_cannot_hard_block(monkeypatch):
    """A cohort toxic only on pre-epoch evidence loses hard-block standing:
    it falls back to the soft margin path instead of MATCHING_TOXIC_CELL."""
    monkeypatch.setenv("MERID_EVIDENCE_EPOCH_TS", str(time.time()))
    cells = {
        "XRP|yes|75-89|late": _epoch_cell(
            w=10, l=90, w_post=0, l_post=0, entry=77),
        "XRP|yes|75-89|mid": _epoch_cell(
            w=4, l=10, w_post=0, l_post=0, entry=77),
    }
    d = _eval(cells, asset="XRP", side="yes", entry_price_cents=77.0,
              tte_seconds=200.0)
    assert d.code != "MATCHING_TOXIC_CELL"
    assert not d.matching_hard_block


def test_post_epoch_evidence_restores_hard_block(monkeypatch):
    """Post-epoch mass re-earns the block on its own."""
    monkeypatch.setenv("MERID_EVIDENCE_EPOCH_TS", str(time.time()))
    cells = {
        "XRP|yes|75-89|late": _epoch_cell(w=10, l=90, entry=77),
    }
    d = _eval(cells, asset="XRP", side="yes", entry_price_cents=77.0,
              tte_seconds=200.0)
    assert not d.allowed
    assert d.code == "MATCHING_TOXIC_CELL"
    assert d.matching_hard_block


def test_rehab_probe_admits_once_then_cools_down(monkeypatch, tmp_path):
    """Challenge mode + a blocked cell: one probe per interval at normal
    margin, then the veto returns until the cooldown lapses."""
    monkeypatch.setenv("MERID_EVIDENCE_HARD_BLOCK_MODE", "challenge")
    monkeypatch.setenv(
        "MERID_EVIDENCE_REHAB_STATE_PATH", str(tmp_path / "rehab.json")
    )
    monkeypatch.setenv("MERID_EVIDENCE_REHAB_PROBE", "1")
    # Toxic dense cohort: w=10,l=90 @77c -> deep negative hb_ev; net_edge 4c
    # clears the 3c margin but not the ~7c challenge reserve.
    cells = {"XRP|yes|75-89|late": _cell(w=10, l=90, entry=77)}
    d1 = _eval(cells, asset="XRP", side="yes", entry_price_cents=77.0,
               tte_seconds=200.0, net_edge_cents=4.0)
    assert d1.allowed
    assert d1.code == "TOXIC_REHAB_PROBE"
    assert d1.escape_required
    # Same cell immediately after -> probe consumed; veto returns.
    d2 = _eval(cells, asset="XRP", side="yes", entry_price_cents=77.0,
               tte_seconds=200.0, net_edge_cents=4.0)
    assert not d2.allowed
    assert d2.code == "MATCHING_TOXIC_CELL"


def test_rehab_probe_requires_normal_margin(monkeypatch, tmp_path):
    """The probe is bounded exploration, not a free pass: net edge below the
    normal evidence margin stays blocked even when the probe is due."""
    monkeypatch.setenv("MERID_EVIDENCE_HARD_BLOCK_MODE", "challenge")
    monkeypatch.setenv(
        "MERID_EVIDENCE_REHAB_STATE_PATH", str(tmp_path / "rehab.json")
    )
    cells = {"XRP|yes|75-89|late": _cell(w=10, l=90, entry=77)}
    d = _eval(cells, asset="XRP", side="yes", entry_price_cents=77.0,
              tte_seconds=200.0, net_edge_cents=1.0)  # margin=3c
    assert not d.allowed
    assert d.code == "MATCHING_TOXIC_CELL"


def test_rehab_probe_disabled_stays_blocked(monkeypatch, tmp_path):
    monkeypatch.setenv("MERID_EVIDENCE_HARD_BLOCK_MODE", "challenge")
    monkeypatch.setenv(
        "MERID_EVIDENCE_REHAB_STATE_PATH", str(tmp_path / "rehab.json")
    )
    monkeypatch.setenv("MERID_EVIDENCE_REHAB_PROBE", "0")
    cells = {"XRP|yes|75-89|late": _cell(w=10, l=90, entry=77)}
    d = _eval(cells, asset="XRP", side="yes", entry_price_cents=77.0,
              tte_seconds=200.0, net_edge_cents=4.0)
    assert not d.allowed
    assert d.code == "MATCHING_TOXIC_CELL"


def test_rehab_probe_interval_respected(monkeypatch, tmp_path):
    """Cooldown is per cell+level and expires on schedule."""
    monkeypatch.setenv("MERID_EVIDENCE_HARD_BLOCK_MODE", "challenge")
    state = tmp_path / "rehab.json"
    monkeypatch.setenv("MERID_EVIDENCE_REHAB_STATE_PATH", str(state))
    monkeypatch.setenv("MERID_EVIDENCE_REHAB_PROBE_S", "600")
    key = "asset_side_price_tte|XRP|yes|75-89|late"
    now = time.time()
    assert ep._rehab_probe_due("XRP|yes|75-89|late",
                               "asset_side_price_tte", now, str(state))
    ep._record_rehab_probe("XRP|yes|75-89|late",
                           "asset_side_price_tte", now, str(state))
    assert not ep._rehab_probe_due("XRP|yes|75-89|late",
                                   "asset_side_price_tte",
                                   now + 300, str(state))
    assert ep._rehab_probe_due("XRP|yes|75-89|late",
                               "asset_side_price_tte",
                               now + 601, str(state))
    # A different level/cell is not covered by the stamp.
    assert ep._rehab_probe_due("XRP|yes|75-89|late",
                               "asset_side_price",
                               now + 300, str(state))
    assert ep._rehab_probe_due("XRP|yes|50-74|late",
                               "asset_side_price_tte",
                               now + 300, str(state))


# --------------------------------------------------------------------------
# 2026-10-17: pinned-favorite bounded-probe evidence domain
# --------------------------------------------------------------------------
#
# The 92-98c own-side cohort was classifier-vetoed for the entire evidence
# history, so the positive-uplift bound could never admit it.  Inside the
# armed lane window the lane's own floor substitutes for the uplift bound,
# the lane's durable daily cap substitutes for the shared escape budget,
# and a scored level admits on lcb_ev >= 0 (non-adverse posterior) instead
# of the margin+uplift hurdle.

def _pf_env(monkeypatch, floor="-6.0", daily_max="12"):
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MIN_EV_CENTS", floor)
    monkeypatch.setenv("MERID_PINNED_FAV_DAILY_MAX", daily_max)


def test_pinned_empty_cells_floor_substitution(monkeypatch):
    """No cells at all: a pinned candidate's bound is the lane floor, not
    the sparse uplift � net -4c passes as EVIDENCE_EMPTY_PASS where the
    normal bound would refuse."""
    _pf_env(monkeypatch)
    ev = _artifact({})
    d = ep.evaluate(
        ev, asset="SOL", side="yes", entry_price_cents=93.0,
        tte_seconds=600.0, fee_frac=0.01, margin_frac=0.03,
        net_edge_cents=-4.0,
    )
    assert d.allowed is True
    assert d.code == "EVIDENCE_EMPTY_PASS"
    assert d.escape_required is True


def test_pinned_empty_cells_below_floor_blocks(monkeypatch):
    _pf_env(monkeypatch)
    ev = _artifact({})
    d = ep.evaluate(
        ev, asset="SOL", side="yes", entry_price_cents=93.0,
        tte_seconds=600.0, fee_frac=0.01, margin_frac=0.03,
        net_edge_cents=-8.0,
    )
    assert d.allowed is False
    assert d.code == "EVIDENCE_EMPTY_INSUFFICIENT"


def test_pinned_floor_does_not_leak_out_of_band(monkeypatch):
    """The lane floor applies only inside the 92-98c window � a 50c
    candidate at the same -4c claim keeps the uplift bound."""
    _pf_env(monkeypatch)
    ev = _artifact({})
    d = ep.evaluate(
        ev, asset="SOL", side="yes", entry_price_cents=50.0,
        tte_seconds=600.0, fee_frac=0.01, margin_frac=0.03,
        net_edge_cents=-4.0,
    )
    assert d.allowed is False
    assert d.code == "EVIDENCE_EMPTY_INSUFFICIENT"


def test_pinned_lane_disabled_keeps_normal_bound(monkeypatch):
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "0")
    ev = _artifact({})
    d = ep.evaluate(
        ev, asset="SOL", side="yes", entry_price_cents=93.0,
        tte_seconds=600.0, fee_frac=0.01, margin_frac=0.03,
        net_edge_cents=-4.0,
    )
    assert d.allowed is False
    assert d.code == "EVIDENCE_EMPTY_INSUFFICIENT"


def test_pinned_daily_cap_exhaustion(monkeypatch):
    """The lane's own durable cap substitutes for the shared escape
    budget � and does not consume escape submissions."""
    _pf_env(monkeypatch, daily_max="2")
    from merid.prediction import directional_regime as _dr
    _p = os.environ["MERID_PINNED_FAV_STATE_PATH"]
    _dr.record_pinned_fav_submission(_p)
    _dr.record_pinned_fav_submission(_p)
    ev = _artifact({})
    d = ep.evaluate(
        ev, asset="SOL", side="yes", entry_price_cents=93.0,
        tte_seconds=600.0, fee_frac=0.01, margin_frac=0.03,
        net_edge_cents=-4.0,
    )
    assert d.allowed is False
    assert d.code == "PINNED_FAV_CAP_EXHAUSTED"
    # The shared escape budget is untouched.
    assert ep.escape_cap_remaining() == ep.escape_daily_max()


def test_pinned_scored_positive_posterior_passes(monkeypatch):
    """A scored 90-100c cell with a non-adverse posterior LCB admits the
    probe at lcb_ev >= 0 � the margin+uplift hurdle is for unproven model
    claims, not measured cohorts."""
    _pf_env(monkeypatch)
    cells = {"SOL|yes|90-100|mid": _cell(w=98, l=2, entry=93)}
    ev = _artifact(cells)
    d = ep.evaluate(
        ev, asset="SOL", side="yes", entry_price_cents=93.0,
        tte_seconds=600.0, fee_frac=0.01, margin_frac=0.03,
        net_edge_cents=-4.0,
    )
    assert d.allowed is True
    assert d.code == "CELL_EVIDENCE_PASS"


def test_pinned_scored_adverse_posterior_blocks(monkeypatch):
    """A measured-adverse posterior must still block the probe � the lane
    tests an unproven cohort, not a measured loser."""
    _pf_env(monkeypatch)
    cells = {"SOL|yes|90-100|mid": _cell(w=30, l=70, entry=93)}
    ev = _artifact(cells)
    d = ep.evaluate(
        ev, asset="SOL", side="yes", entry_price_cents=93.0,
        tte_seconds=600.0, fee_frac=0.01, margin_frac=0.03,
        net_edge_cents=-4.0,
    )
    assert d.allowed is False
    # A dense measured-loser cell is a toxic-cell hard block — the
    # strongest form of "measured adverse" the lane must never bypass.
    assert d.code in (
        "CELL_EVIDENCE_INSUFFICIENT",
        "CHALLENGE_INSUFFICIENT",
        "SOFT_PENALTY_INSUFFICIENT",
        "MATCHING_TOXIC_CELL",
    )


def test_pinned_scored_sparse_adverse_not_soft_probed(monkeypatch):
    """A *sparse* measured-adverse cell cannot use the soft-penalty lane —
    lcb_ev < 0 with no recent contradiction is a measured loser, and the
    pinned probe only exists for unproven cohorts."""
    _pf_env(monkeypatch)
    cells = {"SOL|yes|90-100|mid": _cell(w=2, l=6, entry=93)}
    ev = _artifact(cells)
    d = ep.evaluate(
        ev, asset="SOL", side="yes", entry_price_cents=93.0,
        tte_seconds=600.0, fee_frac=0.01, margin_frac=0.03,
        net_edge_cents=-4.0,
    )
    assert d.allowed is False
    assert d.code == "CELL_EVIDENCE_INSUFFICIENT"
