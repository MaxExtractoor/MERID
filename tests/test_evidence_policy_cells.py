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
