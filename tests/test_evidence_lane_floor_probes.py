"""Regression tests for the 2026-10-22 evidence deadlock fixes.

Two coupled defects were starving every bounded lane of evidence
admissions:

1. ``MERID_EVIDENCE_STALE_S`` (inner adaptive-state staleness bound inside
   ``evidence_policy.evaluate()``) defaulted to 3600s — below the artifact's
   own 4h data window and far below the real refresh cadence on the
   production DB.  Once an artifact aged past it, ``stale=True`` skipped the
   CHALLENGE_ELIGIBLE / SOFT_PENALTY tiers entirely, collapsing every sparse
   cell to ``*_INSUFFICIENT`` -> escape vetoes -> mass ``evidence_escape``
   blocks.  New default is 28800s so the release tier stays alive through
   realistic refresh lag; the outer health tiers (48h/96h/7d) still bound
   total artifact usability and hard blocks stay post-epoch-only.

2. The challenge-tier edge test (``ch_ok``) and the sparse/empty bound
   (``req_edge``) required the generic positive uplift for candidates that
   were *already inside an armed bounded lane* — structurally incapable of
   admitting the exact negative-floor candidates the lanes exist to rescue.
   The lane's own EV floor now substitutes (drift ~-6c, cheap_no -6c,
   pf -12c) whenever the candidate sits in the lane's armed band; the
   lane's own downstream gates (basis/asset/TTE/per-ticker cap) still bind
   admission, and a candidate below its lane floor stays blocked.
"""
from __future__ import annotations

import inspect
import time

import pytest

import merid.prediction.evidence_policy as ep


# ---------------------------------------------------------------------------
# Helpers — same fixture shape as tests/test_evidence_policy_cells.py
# ---------------------------------------------------------------------------

def _cell(w, l, n_eff=None, n_raw=None, entry=50.0, recent_w=None, recent_l=None):
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
        asset="DOGE", side="no", entry_price_cents=56.0, tte_seconds=400.0,
        fee_frac=0.0, margin_frac=0.03, net_edge_cents=5.0,
    )
    args.update(kw)
    return ep.evaluate(_artifact(cells), **args)


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    """Deterministic env: escape/rehab/pf/lane state off production files."""
    monkeypatch.setenv(
        "MERID_EVIDENCE_ESCAPE_STATE_PATH", str(tmp_path / "escape.json")
    )
    monkeypatch.setenv("MERID_EVIDENCE_HARD_SPARSE_TIER", "0")
    monkeypatch.setenv("MERID_EVIDENCE_HARD_BLOCK_MODE", "challenge")
    monkeypatch.setenv("MERID_EVIDENCE_EPOCH_TS", "0")
    monkeypatch.setenv(
        "MERID_EVIDENCE_REHAB_STATE_PATH", str(tmp_path / "rehab.json")
    )
    monkeypatch.setenv(
        "MERID_PINNED_FAV_STATE_PATH", str(tmp_path / "pinned_fav.json")
    )
    monkeypatch.setenv(
        "MERID_DRIFT_LANE_STATE_PATH", str(tmp_path / "drift.json")
    )
    # Lane envs pinned per-test; default them OFF so .env cannot leak a
    # different lane configuration into unrelated assertions.
    monkeypatch.setenv("MERID_DRIFT_LANE_ENABLED", "0")
    monkeypatch.setenv("MERID_CHEAP_NO_LANE_ENABLED", "0")
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "0")
    yield


def _drift_on(monkeypatch, floor=-6.0):
    monkeypatch.setenv("MERID_DRIFT_LANE_ENABLED", "1")
    monkeypatch.setenv("MERID_DRIFT_MIN_NET_EV_CENTS", str(floor))
    monkeypatch.setenv("MERID_DRIFT_PRICE_LO", "40")
    monkeypatch.setenv("MERID_DRIFT_PRICE_HI", "74")


def _cheap_on(monkeypatch, floor=-6.0):
    monkeypatch.setenv("MERID_CHEAP_NO_LANE_ENABLED", "1")
    monkeypatch.setenv("MERID_CHEAP_NO_MIN_NET_EV_CENTS", str(floor))
    monkeypatch.setenv("MERID_CHEAP_NO_PRICE_LO", "25")
    monkeypatch.setenv("MERID_CHEAP_NO_PRICE_HI", "40")


# A dense matched cell with a losing posterior but a winning recent window —
# the contradiction case that routes through the challenge tier.
def _contradicting_doge_cell():
    return {"DOGE|no|50-74|mid": _cell(w=10, l=30, n_eff=40, entry=56,
                                     recent_w=6, recent_l=1)}


# ---------------------------------------------------------------------------
# Challenge tier: lane-floor substitution
# ---------------------------------------------------------------------------

def test_challenge_admits_at_drift_floor(monkeypatch):
    """In-band drift candidate with EV >= lane floor must challenge-admit —
    the generic positive uplift is structurally unachievable by design."""
    _drift_on(monkeypatch, floor=-6.0)
    d = _eval(dict(_contradicting_doge_cell()),
              entry_price_cents=56.0, net_edge_cents=-4.0)
    assert d.code == "CHALLENGE_ELIGIBLE"
    assert d.allowed and d.escape_required


def test_challenge_generic_margin_when_lane_disabled():
    """Same contradiction, lane off -> the generic positive margin applies."""
    d = _eval(dict(_contradicting_doge_cell()),
              entry_price_cents=56.0, net_edge_cents=-4.0)
    assert d.code == "CHALLENGE_INSUFFICIENT"
    assert not d.allowed


def test_challenge_lane_floor_still_binds_below_floor(monkeypatch):
    """The lane floor is a bound, not a bypass: -7c < -6c stays blocked."""
    _drift_on(monkeypatch, floor=-6.0)
    d = _eval(dict(_contradicting_doge_cell()),
              entry_price_cents=56.0, net_edge_cents=-7.0)
    assert d.code == "CHALLENGE_INSUFFICIENT"
    assert not d.allowed


# ---------------------------------------------------------------------------
# Sparse / empty paths: lane-floor substitution for req_edge
# ---------------------------------------------------------------------------

def test_sparse_matched_pass_at_drift_floor(monkeypatch):
    """No price-matched dense cell -> economic bound = lane floor, not the
    max sparse uplift."""
    _drift_on(monkeypatch, floor=-6.0)
    cells = {"DOGE|no|75-89|late": _cell(w=8, l=12, entry=80)}
    d = _eval(cells, entry_price_cents=56.0, net_edge_cents=-4.0)
    assert d.code == "SPARSE_MATCHED_PASS"
    assert d.allowed and d.escape_required
    assert d.required_margin_cents == pytest.approx(-6.0)


def test_sparse_matched_insufficient_without_lane():
    cells = {"DOGE|no|75-89|late": _cell(w=8, l=12, entry=80)}
    d = _eval(cells, entry_price_cents=56.0, net_edge_cents=-4.0)
    assert d.code == "SPARSE_MATCHED_INSUFFICIENT"
    assert not d.allowed


def test_evidence_empty_pass_at_cheap_no_floor(monkeypatch):
    """No cell evidence at all -> lane floor substitutes the uplift bound."""
    _cheap_on(monkeypatch, floor=-6.0)
    d = _eval({}, side="no", entry_price_cents=30.0, net_edge_cents=-4.0)
    assert d.code == "EVIDENCE_EMPTY_PASS"
    assert d.allowed and d.escape_required


def test_cheap_no_floor_is_no_side_only(monkeypatch):
    """cheap_no is a NO-side lane; a YES candidate in-band gets the generic
    bound instead."""
    _cheap_on(monkeypatch, floor=-6.0)
    d = _eval({}, side="yes", entry_price_cents=30.0, net_edge_cents=-4.0)
    assert d.code == "EVIDENCE_EMPTY_INSUFFICIENT"
    assert not d.allowed


# ---------------------------------------------------------------------------
# Staleness bound: adaptive tier must survive refresh lag
# ---------------------------------------------------------------------------

def test_adaptive_tier_alive_on_stale_but_usable_artifact():
    """A 2h-old artifact is stale-but-usable: the challenge tier still runs
    instead of collapsing to *_INSUFFICIENT (the 2026-10-22 deadlock)."""
    cells = dict(_contradicting_doge_cell())
    art = _artifact(cells, generated_at=time.time() - 2 * 3600)
    d = ep.evaluate(
        art, asset="DOGE", side="no", entry_price_cents=56.0,
        tte_seconds=400.0, fee_frac=0.0, margin_frac=0.03,
        net_edge_cents=5.0,
    )
    assert not d.evidence_stale
    assert d.code == "CHALLENGE_ELIGIBLE"
    assert d.allowed


def test_adaptive_tier_dead_on_very_old_artifact(monkeypatch):
    """Past the (raised) bound the tier still closes — the flag remains a
    real bound, just one that spans refresh lag."""
    monkeypatch.setenv("MERID_EVIDENCE_STALE_S", "60")
    cells = dict(_contradicting_doge_cell())
    art = _artifact(cells, generated_at=time.time() - 120)
    d = ep.evaluate(
        art, asset="DOGE", side="no", entry_price_cents=56.0,
        tte_seconds=400.0, fee_frac=0.0, margin_frac=0.03,
        net_edge_cents=5.0,
    )
    assert d.evidence_stale
    # Stale artifact cannot hard-block AND cannot challenge — sparse fall.
    assert d.code != "CHALLENGE_ELIGIBLE"


# ---------------------------------------------------------------------------
# Probe-path generalization (trade_decision): source-scan guards
# ---------------------------------------------------------------------------

def test_probe_path_extends_to_drift_and_cheap_lanes():
    """The refused-evidence probe must consult drift/cheap lane gates, not
    just pinned_fav_reachable — otherwise a non-toxic INSUFFICIENT vetoes
    lane-admissible candidates even when the lane's own gates pass."""
    import merid.prediction.trade_decision as td
    src = inspect.getsource(td)
    assert "_drift_reach" in src
    assert "_cheap_reach" in src
    assert "_dl_pr.drift_block(" in src
    assert "_dl_pr.cheap_no_block(" in src
    # Lane floor must feed the escape margin check — a generic 0 bound
    # would re-veto every lane rescue on the shared mid-band margin.
    assert "_lane_floor_c" in src
    # Owner stamps must name the lane that owned the admission.
    assert '"drift_fav"' in src and '"cheap_no_settle"' in src


def test_probe_skip_late_window_requires_measured_support():
    """skip_late_window may lift only on the cell's own measured record —
    an adequate weighted sample clearing break-even (challenge parity), not
    merely a non-loss verdict."""
    import merid.prediction.trade_decision as td
    src = inspect.getsource(td)
    idx = src.find("skip_late_window=(")
    assert idx > 0
    block = src[idx:idx + 600]
    assert "min_cell_neff" in block
    assert "_pf_measured_loss" in block
