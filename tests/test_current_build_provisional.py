"""Current-build dual-side provisional lane tests
(merid/prediction/current_build_provisional.py).

The lane evaluates YES and NO independently for all five assets inside a
bounded domain (20-89c executable ask, 120-600s TTE) under current-build
economics, with legacy evidence demoted to labels and current-build evidence
owning suspension/promotion.  These tests prove:

  * the generated cell grid covers the approved domain exactly,
  * resolution + miss attribution behave on every boundary,
  * per-asset/per-side provisional thresholds (incl. the YES premium),
  * legacy evidence verdicts (incl. legacy hard blocks) admit via the lane
    when current EV clears the provisional threshold and caps are open,
  * the lane fails closed on state/cap breaches,
  * immediate + rolling suspension rules fire as specified,
  * decision-level integration stamps the lane and preserves registered-cell
    precedence.
"""
from __future__ import annotations

import json
import math
import os

import pytest

import merid.prediction.trade_decision as _td
from merid.prediction import current_build_provisional as cbp
from merid.prediction.threshold_cells import cell_region_registered
from merid.prediction.trade_decision import (
    _decompose_dynamic_min_required_edge,
    compute_trade_decision,
)


@pytest.fixture(autouse=True)
def _isolate_lane(monkeypatch, tmp_path):
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MIN_W", 0.0)
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MAX_W", 0.0)
    monkeypatch.setattr(_td, "MERID_CALIBRATION_CAP_FULL_RANGE", False)
    monkeypatch.delenv("MERID_THRESHOLD_CELLS", raising=False)
    monkeypatch.delenv("MERID_PROVISIONAL_LANE", raising=False)
    monkeypatch.delenv("MERID_PROVISIONAL_MAKER", raising=False)
    monkeypatch.delenv("MERID_PROVISIONAL_EVIDENCE_OVERRIDE", raising=False)
    monkeypatch.setenv(
        "MERID_PROVISIONAL_STATE_PATH", str(tmp_path / "cbp_state.json")
    )
    monkeypatch.setenv(
        "MERID_PROVISIONAL_LIFECYCLE_PATH", str(tmp_path / "cbp_lc.jsonl")
    )
    monkeypatch.setenv(
        "MERID_PROVISIONAL_EVIDENCE_DIR", str(tmp_path / "cbp_ev")
    )
    # The precedence tests mutate threshold-cell state — isolate that too.
    monkeypatch.setenv(
        "MERID_THRESHOLD_CELL_STATE_PATH", str(tmp_path / "tc_state.json")
    )
    cbp.reset_provisional_state_cache()
    from merid.prediction.threshold_cells import reset_cell_state_cache
    reset_cell_state_cache()
    yield
    cbp.reset_provisional_state_cache()
    reset_cell_state_cache()


def _decomp(asset, side, px, tte=None):
    return _decompose_dynamic_min_required_edge(
        asset=asset,
        price_cents=px,
        side=side,
        yes_bid_cents=40.0,
        yes_ask_cents=42.0,
        no_bid_cents=53.0,
        no_ask_cents=55.0,
        floor_min_required_edge=0.02,
        seconds_to_expiry=tte,
    )


# ---------------------------------------------------------------------------
# Grid + resolution
# ---------------------------------------------------------------------------

def test_cell_grid_covers_approved_domain():
    # 5 assets x 2 sides x 7 price bands (20-30..80-90) x 2 TTE bands.
    assert len(cbp.PROVISIONAL_CELLS) == 140
    ids = {c.cell_id for c in cbp.PROVISIONAL_CELLS}
    assert len(ids) == 140
    for c in cbp.PROVISIONAL_CELLS:
        assert 20 <= c.price_min_cents and c.price_max_cents <= 90
        assert 120 <= c.tte_min_seconds and c.tte_max_seconds <= 600
        assert c.min_net_ev_cents > 0
        assert c.cell_id.startswith("cbp_")


def test_resolution_boundaries():
    # Half-open price bands.
    c = cbp.resolve_provisional_cell("ETH", "yes", 40.0, 200.0)
    assert c.cell_id == "cbp_eth_yes_40_50_t120_300"
    assert cbp.resolve_provisional_cell("ETH", "yes", 49.99, 200.0).cell_id == c.cell_id
    assert cbp.resolve_provisional_cell("ETH", "yes", 50.0, 200.0).cell_id == "cbp_eth_yes_50_60_t120_300"
    # Domain edges.
    assert cbp.resolve_provisional_cell("BTC", "yes", 20.0, 200.0) is not None
    assert cbp.resolve_provisional_cell("BTC", "yes", 19.99, 200.0) is None
    assert cbp.resolve_provisional_cell("BTC", "yes", 89.99, 200.0) is not None
    assert cbp.resolve_provisional_cell("BTC", "yes", 90.0, 200.0) is None
    # TTE edges: [120,300] then (300,600] — final 120s disabled.
    assert cbp.resolve_provisional_cell("BTC", "yes", 45.0, 120.0) is not None
    assert cbp.resolve_provisional_cell("BTC", "yes", 45.0, 119.9) is None
    assert cbp.resolve_provisional_cell("BTC", "yes", 45.0, 300.0).tte_min_seconds == 120.0
    assert cbp.resolve_provisional_cell("BTC", "yes", 45.0, 300.01).tte_min_seconds == 300.0
    assert cbp.resolve_provisional_cell("BTC", "yes", 45.0, 600.0) is not None
    assert cbp.resolve_provisional_cell("BTC", "yes", 45.0, 600.01) is None


def test_both_sides_resolve_independently():
    cy = cbp.resolve_provisional_cell("SOL", "yes", 55.0, 400.0)
    cn = cbp.resolve_provisional_cell("SOL", "no", 55.0, 400.0)
    assert cy is not None and cn is not None
    assert cy.side == "yes" and cn.side == "no"
    assert cy.cell_id != cn.cell_id


def test_miss_reasons():
    assert cbp.explain_provisional_miss("BTC", "yes", 15.0, 200.0) == "provisional_price_below_min"
    assert cbp.explain_provisional_miss("BTC", "yes", 92.0, 200.0) == "provisional_price_above_max"
    assert cbp.explain_provisional_miss("BTC", "yes", 45.0, 60.0) == "provisional_tte_below_min"
    assert cbp.explain_provisional_miss("BTC", "yes", 45.0, 900.0) == "provisional_tte_above_max"
    assert cbp.explain_provisional_miss("BTC", "yes", None, 200.0) == "provisional_price_unknown"
    assert cbp.explain_provisional_miss("BTC", "yes", 45.0, None) == "provisional_tte_unknown"
    assert cbp.explain_provisional_miss("BTC", "yes", 45.0, 200.0) is None
    assert cbp.explain_provisional_miss("LINK", "yes", 45.0, 200.0) == "provisional_asset_not_in_universe"


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("MERID_PROVISIONAL_LANE", "0")
    assert cbp.resolve_provisional_cell("BTC", "yes", 45.0, 200.0) is None
    assert cbp.explain_provisional_miss("BTC", "yes", 45.0, 200.0) == "provisional_lane_disabled"
    ok, reason = cbp.provisional_admission_allowed(
        "cbp_btc_yes_40_50_t120_300", None, False, 9.0, 2.5
    )
    assert ok is False and reason == "provisional_lane_disabled"


def test_env_domain_narrowing_only(monkeypatch):
    # Widening attempts fail closed: the generated grid bounds the domain.
    monkeypatch.setenv("MERID_PROVISIONAL_PRICE_MIN_CENTS", "10")
    assert cbp.domain_price_min_cents() == 20
    monkeypatch.setenv("MERID_PROVISIONAL_PRICE_MAX_CENTS", "99")
    assert cbp.domain_price_max_cents() == 90
    # Narrowing is honored.
    monkeypatch.setenv("MERID_PROVISIONAL_TTE_MIN_S", "180")
    assert cbp.resolve_provisional_cell("BTC", "yes", 45.0, 150.0) is None
    assert cbp.resolve_provisional_cell("BTC", "yes", 45.0, 200.0) is not None


# ---------------------------------------------------------------------------
# Per-asset/per-side thresholds
# ---------------------------------------------------------------------------

def test_provisional_threshold_table():
    assert cbp.provisional_min_ev_cents("BTC", "no") == 2.0
    assert cbp.provisional_min_ev_cents("ETH", "no") == 2.0
    assert cbp.provisional_min_ev_cents("SOL", "no") == 2.5
    assert cbp.provisional_min_ev_cents("XRP", "no") == 2.5
    assert cbp.provisional_min_ev_cents("DOGE", "no") == 2.5
    # YES carries the +0.5c measurement premium.
    assert cbp.provisional_min_ev_cents("BTC", "yes") == 2.5
    assert cbp.provisional_min_ev_cents("ETH", "yes") == 2.5
    assert cbp.provisional_min_ev_cents("SOL", "yes") == 3.0
    assert cbp.provisional_min_ev_cents("XRP", "yes") == 3.0
    assert cbp.provisional_min_ev_cents("DOGE", "yes") == 3.0


def test_threshold_env_override(monkeypatch):
    monkeypatch.setenv("MERID_PROVISIONAL_MIN_EV_C_BTC_YES", "4.0")
    assert cbp.provisional_min_ev_cents("BTC", "yes") == 4.0
    monkeypatch.setenv("MERID_PROVISIONAL_MIN_EV_C", "1.75")
    assert cbp.provisional_min_ev_cents("ETH", "no") == 1.75


# ---------------------------------------------------------------------------
# Decompose integration: provisional replaces formula only in unregistered
# regions; registered cells keep sole authority.
# ---------------------------------------------------------------------------

def test_decompose_provisional_replaces_formula():
    # DOGE no at 35c: the tc registry has no cell in the 30-40 gap, and the
    # provisional domain covers it -> threshold becomes 2.5c, not ~3c+.
    assert not cell_region_registered("DOGE", "no", 35.0, 300.0)
    d = _decomp("DOGE", "no", 35, tte=300.0)
    assert d.cell_id is None
    assert d.provisional_cell_id == "cbp_doge_no_30_40_t120_300"
    assert math.isclose(d.total, 0.025, abs_tol=1e-9)
    assert math.isclose(d.provisional_min_ev_cents, 2.5, abs_tol=1e-9)
    assert d.formula_total is not None and d.formula_total > d.total


def test_decompose_registered_cell_wins():
    # SOL no 45c/300s is a qualified tc cell -> provisional never engages.
    d = _decomp("SOL", "no", 45, tte=300.0)
    assert d.cell_id == "sol_no_30_60_t120_600"
    assert d.provisional_cell_id is None
    assert math.isclose(d.total, 0.015, abs_tol=1e-9)


def test_decompose_suspended_registered_cell_keeps_authority():
    # Suspend the SOL cell; the provisional lane must NOT reopen its band.
    from merid.prediction.threshold_cells import (
        record_cell_router_attempt,
        record_cell_router_reject,
        reset_cell_state_cache,
    )
    reset_cell_state_cache()
    for _ in range(2):
        record_cell_router_attempt("sol_no_30_60_t120_600")
        record_cell_router_reject("sol_no_30_60_t120_600")
    d = _decomp("SOL", "no", 45, tte=300.0)
    assert d.cell_id is None  # tc lane blocked it
    assert d.cell_cap_exhausted is True
    assert d.provisional_cell_id is None  # region stays claimed
    assert d.total > 0.025  # back on the formula


def test_decompose_tc_disabled_still_claims_region(monkeypatch):
    # MERID_THRESHOLD_CELLS=0 is an emergency off for that lane — it must not
    # silently release registered regions to the provisional lane.
    monkeypatch.setenv("MERID_THRESHOLD_CELLS", "0")
    d = _decomp("SOL", "no", 45, tte=300.0)
    assert d.cell_id is None
    assert d.provisional_cell_id is None
    assert d.total > 0.02


def test_decompose_outside_domain_uses_formula():
    d = _decomp("SOL", "yes", 45, tte=90.0)  # inside final 120s -> disabled
    assert d.provisional_cell_id is None
    assert d.total > 0.02


# ---------------------------------------------------------------------------
# Legacy-evidence demotion
# ---------------------------------------------------------------------------

def _prov_cell(asset="DOGE", side="yes", px=35.0, tte=200.0):
    return cbp.resolve_provisional_cell(asset, side, px, tte)


def test_admission_clears_threshold():
    c = _prov_cell()
    ok, r = cbp.provisional_admission_allowed(
        c.cell_id, "SPARSE_MATCHED_INSUFFICIENT", False, 4.0, 3.0
    )
    assert ok and r is None


def test_admission_rejects_below_threshold():
    c = _prov_cell()
    ok, r = cbp.provisional_admission_allowed(
        c.cell_id, "SPARSE_MATCHED_INSUFFICIENT", False, 2.0, 3.0
    )
    assert not ok and r == "ev_below_provisional_threshold"


def test_admission_demotes_every_legacy_verdict():
    """Every cell-aware code AND a legacy hard block are labels, not vetoes."""
    c = _prov_cell()
    for code in (
        "SPARSE_MATCHED_INSUFFICIENT", "SOFT_PENALTY_INSUFFICIENT",
        "CHALLENGE_INSUFFICIENT", "ESCAPE_CAP_EXHAUSTED",
        "CELL_EVIDENCE_INSUFFICIENT", "MATCHING_TOXIC_CELL",
        "EVIDENCE_EMPTY_INSUFFICIENT",
    ):
        ok, r = cbp.provisional_admission_allowed(
            c.cell_id, code, code == "MATCHING_TOXIC_CELL", 4.0, 3.0
        )
        assert ok, (code, r)


def test_admission_override_kill_switch(monkeypatch):
    """MERID_PROVISIONAL_EVIDENCE_OVERRIDE=0 restores legacy vetoes."""
    monkeypatch.setenv("MERID_PROVISIONAL_EVIDENCE_OVERRIDE", "0")
    c = _prov_cell()
    ok, r = cbp.provisional_admission_allowed(
        c.cell_id, "SPARSE_MATCHED_INSUFFICIENT", False, 9.0, 3.0
    )
    assert not ok and r == "legacy_override_disabled"


def test_admission_state_and_caps():
    c = _prov_cell()
    cbp.set_cell_state(c.cell_id, "SUSPENDED", "test")
    ok, r = cbp.provisional_admission_allowed(
        c.cell_id, None, False, 9.0, 3.0
    )
    assert not ok and r == "cell_state_suspended"


# ---------------------------------------------------------------------------
# Caps: one-contract, fills/day, open-order bounds
# ---------------------------------------------------------------------------

def test_fill_caps_per_cell_asset_side_total():
    # YES defaults to 1/day globally; per-asset and per-cell caps are 1.
    c_btc_y = cbp.resolve_provisional_cell("BTC", "yes", 45.0, 200.0)
    cbp.record_provisional_fill(c_btc_y.cell_id, decision_id="d0")
    ok, r = cbp.provisional_cell_admission(c_btc_y.cell_id)
    assert not ok and r == "cell_fills_cap_exhausted"
    c_eth_y = cbp.resolve_provisional_cell("ETH", "yes", 45.0, 200.0)
    ok, r = cbp.provisional_cell_admission(c_eth_y.cell_id)
    assert not ok and r == "side_fills_cap_exhausted"
    # NO still admits (its side cap defaults to the lane total of 3).
    c_eth_n = cbp.resolve_provisional_cell("ETH", "no", 45.0, 200.0)
    ok, r = cbp.provisional_cell_admission(c_eth_n.cell_id)
    assert ok


def test_total_fill_cap(monkeypatch):
    monkeypatch.setenv("MERID_PROVISIONAL_DAILY_MAX_FILLS_TOTAL", "3")
    # Two NO fills + one YES fill reaches the total; the lane then fails
    # closed even though per-side NO headroom remains.
    cells = [
        cbp.resolve_provisional_cell("BTC", "no", 45.0, 200.0),
        cbp.resolve_provisional_cell("ETH", "no", 45.0, 200.0),
        cbp.resolve_provisional_cell("SOL", "yes", 45.0, 200.0),
    ]
    for i, c in enumerate(cells):
        cbp.record_provisional_fill(c.cell_id, decision_id=f"d{i}")
    c4 = cbp.resolve_provisional_cell("XRP", "no", 45.0, 200.0)
    ok, r = cbp.provisional_cell_admission(c4.cell_id)
    assert not ok and r == "lane_fills_total_cap_exhausted"


def test_open_order_caps():
    c = _prov_cell(side="no", px=45.0)
    cbp.record_provisional_order_open(c.cell_id, "ord-1")
    ok, r = cbp.provisional_cell_admission(c.cell_id)
    assert not ok and r == "cell_open_order_exists"
    c2 = cbp.resolve_provisional_cell("BTC", "no", 55.0, 200.0)
    ok, r = cbp.provisional_cell_admission(c2.cell_id)
    assert not ok and r == "lane_open_order_exists"
    cbp.record_provisional_order_closed(c.cell_id, "ord-1")
    ok, r = cbp.provisional_cell_admission(c2.cell_id)
    assert ok


def test_submission_reservation_release():
    c = _prov_cell(side="no", px=45.0)
    n0 = cbp.provisional_submissions_today()
    cbp.record_provisional_submission(cell_id=c.cell_id, decision_id="dd1")
    assert cbp.provisional_submissions_today() == n0 + 1
    cbp.record_provisional_pre_wire_reject(
        c.cell_id, decision_id="dd1", intent_id="i1",
        rejection_code="pre_submit_passivity",
    )
    assert cbp.provisional_submissions_today() == n0
    # The reservation release is idempotent.
    cbp.record_provisional_pre_wire_reject(
        c.cell_id, decision_id="dd1", intent_id="i1",
        rejection_code="pre_submit_passivity",
    )
    assert cbp.provisional_submissions_today() == n0


def test_daily_roll_resets_counters():
    import time as _time
    c = _prov_cell(side="no", px=45.0)
    cbp.record_provisional_fill(c.cell_id, decision_id="d0")
    assert cbp.provisional_fills_today(c.cell_id) == 1
    # Simulate a stale-state date so the loader rolls counters to a new day.
    state = cbp._load_state()
    state["date"] = "1970-01-01"
    cbp._save_state()
    cbp.reset_provisional_state_cache()
    assert cbp.provisional_fills_today(c.cell_id) == 0
    # Suspension state survives the roll (durable across days).
    cbp.set_cell_state(c.cell_id, "SUSPENDED", "persisted")
    cbp.reset_provisional_state_cache()
    assert cbp.get_cell_state(c.cell_id) == "SUSPENDED"


# ---------------------------------------------------------------------------
# Suspension rules
# ---------------------------------------------------------------------------

def test_first_fill_bad_markout_suspends():
    c = _prov_cell(side="no", px=45.0)
    cbp.record_provisional_fill(c.cell_id, decision_id="d0")
    cbp.record_provisional_markout(c.cell_id, "d0", 5, -3.5)
    assert cbp.get_cell_state(c.cell_id) == "SUSPENDED"
    ok, r = cbp.provisional_cell_admission(c.cell_id)
    assert not ok and r == "cell_suspended"


def test_first_fill_nonpositive_ev_suspends():
    c = _prov_cell(side="no", px=45.0)
    cbp.record_provisional_fill(
        c.cell_id, decision_id="d0", fill_ev_cents=0.0
    )
    assert cbp.get_cell_state(c.cell_id) == "SUSPENDED"


def test_first_fill_pnl_beyond_stress_suspends():
    c = _prov_cell(side="no", px=45.0)
    cbp.record_provisional_fill(
        c.cell_id, decision_id="d0", candidate_ev_cents=3.0
    )
    cbp.record_provisional_settlement("d0", net_pnl_cents=-5.5)
    # -(3.0 + 2.0) = -5.0 bound breached -> SUSPENDED.
    assert cbp.get_cell_state(c.cell_id) == "SUSPENDED"


def test_post_only_breach_suspends_immediately():
    c = _prov_cell(side="no", px=45.0)
    cbp.record_provisional_fill(
        c.cell_id, decision_id="d0",
        fill_price_cents=46.0, limit_price_cents=45.0, action="buy",
    )
    assert cbp.get_cell_state(c.cell_id) == "SUSPENDED"


def test_invariant_violation_suspends_immediately():
    c = _prov_cell(side="no", px=45.0)
    cbp.record_provisional_invariant_violation(c.cell_id, "side_mismatch")
    assert cbp.get_cell_state(c.cell_id) == "SUSPENDED"


def test_consecutive_router_rejects_suspend():
    c = _prov_cell(side="no", px=45.0)
    cbp.record_provisional_router_reject(c.cell_id)
    assert cbp.get_cell_state(c.cell_id) != "SUSPENDED"
    cbp.record_provisional_router_reject(c.cell_id)
    assert cbp.get_cell_state(c.cell_id) == "SUSPENDED"


def test_rolling_mean_pnl_suspends():
    c = _prov_cell(side="no", px=45.0)
    for i in range(3):
        cbp.record_provisional_fill(c.cell_id, decision_id=f"d{i}")
        cbp.record_provisional_settlement(f"d{i}", net_pnl_cents=-2.0)
    assert cbp.get_cell_state(c.cell_id) == "SUSPENDED"


def test_rolling_negative_markouts_suspend():
    c = _prov_cell(side="no", px=45.0)
    # Two of the last 3 markouts negative -> suspend (median -0.5 also < -1? no:
    # median of (-2,-0.5,+1)= -0.5 > -1 so the median rule alone wouldn't fire;
    # the two-of-three rule does).
    for i, m in enumerate((-2.0, -0.5, 1.0)):
        cbp.record_provisional_markout(c.cell_id, f"d{i}", 5, m)
    assert cbp.get_cell_state(c.cell_id) == "SUSPENDED"


def test_reject_rate_suspends_after_min_attempts():
    # Rolling rate rule: interleave order-opens so the consecutive-reject
    # counter resets — the suspension must come from the >40% rate rule,
    # not the consecutive emergency rule.
    c = _prov_cell(side="no", px=45.0)
    for i in range(5):
        cbp.record_provisional_router_attempt(c.cell_id)
        cbp.record_provisional_router_reject(c.cell_id)
        cbp.record_provisional_order_open(c.cell_id, f"ord-{i}")
    # attempts=5 rejects=5 -> rate 1.00 > 0.40 -> SUSPENDED.
    assert cbp.get_cell_state(c.cell_id) == "SUSPENDED"
    ok, r = cbp.provisional_cell_admission(c.cell_id)
    assert not ok and r == "cell_suspended"


def test_positive_outcomes_do_not_suspend():
    c = _prov_cell(side="no", px=45.0)
    for i in range(3):
        cbp.record_provisional_fill(
            c.cell_id, decision_id=f"d{i}", fill_ev_cents=2.0,
            candidate_ev_cents=3.0,
        )
        cbp.record_provisional_markout(c.cell_id, f"d{i}", 5, 1.0)
        cbp.record_provisional_settlement(f"d{i}", net_pnl_cents=3.0)
    assert cbp.get_cell_state(c.cell_id) != "SUSPENDED"
    ok, _ = cbp.provisional_cell_admission(c.cell_id)
    # fills cap is 1/day/cell — admission denied on the cap, not suspension.
    assert not ok
    assert cbp.get_cell_state(c.cell_id) != "SUSPENDED"


# ---------------------------------------------------------------------------
# Evidence store + promotion review
# ---------------------------------------------------------------------------

def test_evidence_store_versioned(tmp_path, monkeypatch):
    monkeypatch.setenv("MERID_BUILD_SHA", "testsha123")
    monkeypatch.setenv("MERID_MODEL_VERSION", "bachelier_twap")
    monkeypatch.setenv("MERID_CALIBRATION_VERSION", "calabc")
    cbp.record_cb_evidence(
        "fill", asset="BTC", side="YES",
        price_bucket="40-50", tte_bucket="120-300",
        fill_ev_cents=2.7, filled=True, markout_5s_cents=-0.4,
    )
    path = tmp_path / "cbp_ev" / "testsha123" / "bachelier_twap" / "resolutions.jsonl"
    assert path.exists()
    rec = json.loads(path.read_text().splitlines()[0])
    assert rec["build_sha"] == "testsha123"
    assert rec["model_version"] == "bachelier_twap"
    assert rec["calibration_version"] == "calabc"
    assert rec["admission_lane"] == "current_build_provisional"
    assert rec["record_kind"] == "fill"
    assert rec["fill_ev_cents"] == 2.7


def test_promotion_review_report():
    c = _prov_cell(side="yes", px=45.0)
    for i in range(4):
        cbp.record_provisional_submission(cell_id=c.cell_id)
        cbp.record_provisional_fill(
            c.cell_id, decision_id=f"d{i}",
            fill_ev_cents=2.0, candidate_ev_cents=3.0,
            fill_price_cents=44.0, limit_price_cents=45.0,
        )
        cbp.record_provisional_markout(c.cell_id, f"d{i}", 5, 0.5)
        cbp.record_provisional_settlement(f"d{i}", net_pnl_cents=2.0)
    rep = cbp.promotion_review_report(asset="DOGE", side="yes")
    row = next(r for r in rep["cells"] if r["cell_id"] == c.cell_id)
    assert row["attempts"] == 4 and row["fills"] == 4
    assert row["promotion_ready"] is False  # below min_attempts(10)
    assert rep["build_sha"] and rep["policy_version"] == "cbp_v1"


# ---------------------------------------------------------------------------
# Decision-level integration
# ---------------------------------------------------------------------------

def _decision(**kwargs):
    args = dict(
        run_id="t", decision_id="t", ticker="KXDOGE15M-X",
        asset="DOGE", spot_price=99.0, strike_price=100.0,
        seconds_to_expiry=300.0,
        yes_bid_cents=38.0, yes_ask_cents=40.0,
        no_bid_cents=58.0, no_ask_cents=60.0,
        yes_depth_cc=200.0, no_depth_cc=200.0,
        fee_per_contract_cents=1.0, annualized_vol=0.60,
        model_uncertainty=0.0, data_quality="live", regime="normal",
        min_required_edge=0.02, settlement_reference="cfb_rti_live",
    )
    args.update(kwargs)
    return compute_trade_decision(**args)


def test_decision_provisional_threshold_fields():
    # DOGE 30-40c YES at ask 40c sits in the tc 20-30..40-50 gap? No — DOGE tc
    # cells are 20-30/40-50 NO only, so YES is unregistered: cbp owns it.
    d = _decision(p_yes_model=0.50)
    ind = d.indicators
    assert ind["yes_threshold_source"] == "current_build_provisional"
    assert math.isclose(ind["yes_min_edge"], 0.030, abs_tol=1e-9)
    assert ind["yes_thr_prov_cell_id"] == "cbp_doge_yes_40_50_t120_300"


def test_decision_provisional_lane_stamp_on_selection():
    # p_yes=0.50 vs yes_ask 40c -> ~+7-8c net EV, clears the 3.0c DOGE YES
    # provisional bar -> the selected side is admitted by this lane.
    d = _decision(p_yes_model=0.50)
    ind = d.indicators
    if d.selected_outcome == "yes":
        assert ind["decision_lane"] == "current_build_provisional"
        assert ind["provisional_cell_id"] == "cbp_doge_yes_40_50_t120_300"
        assert ind["provisional_price_bucket"] == "40-50"
        assert ind["provisional_tte_bucket"] == "120-300"
    else:
        # A downstream gate vetoed selection; the side's enforced threshold
        # must still record the provisional bar it was measured against.
        assert ind["yes_threshold_source"] == "current_build_provisional"


def test_decision_outside_domain_keeps_formula():
    d = _decision(p_yes_model=0.50, seconds_to_expiry=90.0)
    ind = d.indicators
    assert ind["yes_threshold_source"] == "formula"
    assert ind["yes_thr_prov_cell_id"] is None


def test_domain_validation_report():
    rep = cbp.validate_provisional_domain()
    assert len(rep) == 140 and all(r["valid"] for r in rep)


def test_rollup_includes_all_five_assets():
    s = cbp.provisional_status_rollup()
    for a in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        assert f"{a}: cells=28" in s
    assert "lane: fills=0/3" in s
