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

import datetime as _dt
import json
import math
import os
from decimal import Decimal

import pytest

import merid.prediction.trade_decision as _td
from merid.prediction import current_build_provisional as cbp
from merid.prediction.threshold_cells import cell_region_registered
from merid.prediction.trade_decision import (
    EdgeBreakdown,
    TradeDecision,
    _decompose_dynamic_min_required_edge,
    apply_bounded_live_domain_gate,
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
    cbp.reset_calibration_version_cache()
    from merid.prediction.threshold_cells import reset_cell_state_cache
    reset_cell_state_cache()
    # Catastrophic cell breaches now escalate to the side-level throttle —
    # isolate its file per test so a breach suspension cannot leak into a
    # later decision-level test in the same worker.
    from merid.prediction import directional_regime as _dr

    monkeypatch.setenv(
        "MERID_DIRECTIONAL_THROTTLE_PATH", str(tmp_path / "throttle.json")
    )
    monkeypatch.setenv(
        "MERID_DIRECTIONAL_REGIME_STATE_PATH", str(tmp_path / "regime.json")
    )
    _dr._throttle_cache = (0.0, {})
    _dr._regime_cache = (0.0, {})
    yield
    cbp.reset_provisional_state_cache()
    cbp.reset_calibration_version_cache()
    reset_cell_state_cache()
    _dr._throttle_cache = (0.0, {})
    _dr._regime_cache = (0.0, {})


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


def test_markout_arriving_before_fill_row_merges_and_suspends():
    """Poll order emits a standalone markout row while the order still looks
    unfilled; the fill record lands a pass later.  The fill recorder must
    absorb the standalone markout so the first-fill immediate rule sees it
    (live ordering observed 2026-10-01: 1s/5s markouts preceded the fill row
    by up to 6s)."""
    c = _prov_cell(side="no", px=45.0)
    cbp.record_provisional_markout(c.cell_id, "d0", 1, -4.0)
    cbp.record_provisional_markout(c.cell_id, "d0", 5, -3.5)
    # Standalone markouts must not suspend before any fill exists.
    assert cbp.get_cell_state(c.cell_id) != "SUSPENDED"
    cbp.record_provisional_fill(c.cell_id, decision_id="d0")
    st = cbp._load_state()
    outs = st["outcomes"][c.cell_id]
    assert not any(o.get("kind") == "markout" for o in outs)
    fills = [o for o in outs if o.get("kind") == "fill"]
    assert len(fills) == 1 and fills[0]["markout_5s_cents"] == -3.5
    assert fills[0]["markout_1s_cents"] == -4.0
    assert cbp.get_cell_state(c.cell_id) == "SUSPENDED"


def test_settlement_idempotent_on_repeated_attribution():
    """Exit-path attribution followed by the settlement join must update the
    same outcome row, not append a duplicate settled row."""
    c = _prov_cell(side="no", px=45.0)
    cbp.record_provisional_fill(c.cell_id, decision_id="d0", candidate_ev_cents=3.0)
    cbp.record_provisional_settlement("d0", net_pnl_cents=2.0)
    cbp.record_provisional_settlement("d0", net_pnl_cents=2.0)
    st = cbp._load_state()
    outs = st["outcomes"][c.cell_id]
    settled = [o for o in outs if o.get("kind") == "settled" and o.get("decision_id") == "d0"]
    assert len(settled) == 1 and settled[0]["net_pnl_cents"] == 2.0


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
    # Structural breach escalates to the side-level throttle (manual review).
    from merid.prediction import directional_regime as _dr
    blk = _dr.side_throttle_block("no")
    assert blk and "catastrophic" in blk


def test_invariant_violation_suspends_immediately():
    c = _prov_cell(side="no", px=45.0)
    cbp.record_provisional_invariant_violation(c.cell_id, "side_mismatch")
    assert cbp.get_cell_state(c.cell_id) == "SUSPENDED"
    from merid.prediction import directional_regime as _dr
    blk = _dr.side_throttle_block("no")
    assert blk and "catastrophic" in blk


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


def test_promotion_review_fires_once_at_thresholds(tmp_path):
    """The review report is build-scoped evidence: daily submission counters
    reset each UTC day, but attempts accumulate in submissions_total so the
    10-attempt review threshold is reachable despite the 5/day per-cell cap.
    The report is emitted exactly once per (build, cell)."""
    import time as _time
    c = _prov_cell(side="yes", px=45.0)
    today = _time.time()
    for _ in range(5):
        cbp.record_provisional_submission(cell_id=c.cell_id, now=today)
    for i in range(3):
        cbp.record_provisional_fill(
            c.cell_id, decision_id=f"d{i}",
            fill_ev_cents=2.0, candidate_ev_cents=3.0,
            fill_price_cents=44.0, limit_price_cents=45.0,
        )
        cbp.record_provisional_markout(c.cell_id, f"d{i}", 5, 0.5)
        cbp.record_provisional_settlement(f"d{i}", net_pnl_cents=2.0)
    # Day rollover: daily counters reset; cumulative evidence must persist.
    tomorrow = today + 86400
    for _ in range(5):
        cbp.record_provisional_submission(cell_id=c.cell_id, now=tomorrow)
    st = cbp._load_state(now=tomorrow)
    assert st["submissions"].get(c.cell_id) == 5        # daily scope
    assert st["submissions_total"].get(c.cell_id) == 10  # cumulative scope
    reports = list((tmp_path / "cbp_ev").rglob("promotion_review_*.json"))
    assert len(reports) == 1
    rep = json.loads(reports[0].read_text())
    row = next(r for r in rep["cells"] if r["cell_id"] == c.cell_id)
    assert row["promotion_ready"] is True
    assert row["attempts"] == 10 and row["fills"] == 3
    assert f"{cbp.current_build_sha()}:{c.cell_id}" in st["review_reported"]
    # Dedupe: later activity on the same build does not re-emit.
    cbp.record_provisional_submission(cell_id=c.cell_id, now=tomorrow)
    cbp.record_provisional_settlement(
        "d_extra", net_pnl_cents=1.0, cell_id=c.cell_id,
    )
    reports = list((tmp_path / "cbp_ev").rglob("promotion_review_*.json"))
    assert len(reports) == 1


def test_promotion_review_waits_for_settled_fills(tmp_path):
    """Fills without a settlement join are incomplete evidence — the report
    must not fire until review_min_fills carries realized PnL."""
    import time as _time
    c = _prov_cell(side="yes", px=45.0)
    now = _time.time()
    for _ in range(10):
        cbp.record_provisional_submission(cell_id=c.cell_id, now=now)
    for i in range(3):
        cbp.record_provisional_fill(
            c.cell_id, decision_id=f"d{i}",
            fill_ev_cents=2.0, candidate_ev_cents=3.0,
            fill_price_cents=44.0, limit_price_cents=45.0,
        )
    cbp.record_provisional_settlement("d0", net_pnl_cents=2.0)
    cbp.record_provisional_settlement("d1", net_pnl_cents=2.0)
    # 10 attempts + 3 fills but only 2 settled -> no report yet.
    assert not list((tmp_path / "cbp_ev").rglob("promotion_review_*.json"))
    cbp.record_provisional_settlement("d2", net_pnl_cents=2.0)
    reports = list((tmp_path / "cbp_ev").rglob("promotion_review_*.json"))
    assert len(reports) == 1


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

# ---------------------------------------------------------------------------
# signal -> candidate -> intent identity propagation (2026-09-30 live audit:
# CBP orders reached the router with lane="" / admission_owner="formula"
# because collect_order_candidate's whitelisted rebuild dropped every lane
# field and the canonical TradeDecision object).
# ---------------------------------------------------------------------------


def test_collect_order_candidate_carries_lane_identity():
    """The candidate whitelist must carry the lane fields + TradeDecision.

    Regression guard: collect_order_candidate rebuilds the signal dict key by
    key; any lane field not explicitly copied silently arrives at the router
    as a formula-lane order with no EV re-gate and no approved-size cap.
    """
    import inspect

    from merid.prediction.agent_grid_15m import LeanAgent15m

    src = inspect.getsource(LeanAgent15m.collect_order_candidate)
    for key in (
        "trade_decision",
        "decision_lane",
        "provisional_cell_id",
        "threshold_cell_id",
        "admission_owner",
        "provisional_required_edge_cents",
        "effective_required_edge_cents",
        "provisional_price_bucket",
        "provisional_tte_bucket",
        "legacy_risk_label",
        "threshold_source",
        "min_required_edge",
        "probability_inputs",
        "execution_mode",
        "liquidity_role",
        "time_in_force",
        "build_sha",
        "config_hash",
    ):
        assert f'"{key}": signal.get("{key}")' in src, (
            f"candidate whitelist dropped signal key {key!r} — lane identity "
            "will not reach the OrderIntent"
        )


def test_rejection_context_survives_no_trade_decision():
    """_build_trade_decision_rejection_context must not raise on a no-trade
    decision where selected_outcome is None.

    Regression guard: the context block referenced an unbound `side` and every
    no-trade decision crashed with NameError, silently yielding zero
    candidates across all assets (observed live 2026-09-30).
    """
    from types import SimpleNamespace

    from merid.prediction.agent_grid_15m import LeanAgent15m

    agent = LeanAgent15m.__new__(LeanAgent15m)
    agent._last_signal_vol_context = {"strike": 83440.51}
    agent._last_velocity_value = None
    agent._last_velocity_source = "test"
    agent._last_velocity_age_ms = None
    agent._last_velocity_threshold = None
    agent.market_state_store = None
    agent._resolve_runtime_signal_mode = lambda: "test"
    agent._get_candles_available = lambda asset: 0

    decision = SimpleNamespace(
        edge_threshold=0.02,
        indicators={
            "decision_lane": "current_build_provisional",
            "provisional_cell_id": "cbp_btc_no_40_50_t300_600",
            "yes_admission_owner": "formula",
            "no_admission_owner": "current_build_provisional",
        },
        ticker="KXBTC15M-T",
        decision_id="d1",
        p_yes_calibrated=0.4,
        p_no_calibrated=0.6,
        yes_net_edge=-0.01,
        no_net_edge=-0.005,
        gross_edge=0.0,
        net_edge=-0.005,
        data_state="ok",
        regime="r",
        confidence_valid=True,
        confidence_reasons=[],
        selected_outcome=None,
    )
    ctx = agent._build_trade_decision_rejection_context(
        "BTC", 100.0, 100.0, "ref", 300.0, decision=decision
    )
    assert ctx["decision_lane"] == "current_build_provisional"
    assert ctx["provisional_cell_id"] == "cbp_btc_no_40_50_t300_600"
    assert ctx["admission_owner"] is None
    assert ctx["no_admission_owner"] == "current_build_provisional"


def test_bounded_lane_normalizes_to_one_contract():
    """_execute_candidate must force exactly 1.0 contract for bounded lanes.

    Regression guard: the lane-cap block must restore a shrunk fractional
    count to 1.0 (the allocator pre-fit and compute_order_size may emit
    sub-contract quantities for cap-constrained accounts).
    """
    import inspect

    from merid import loop_15m

    src = inspect.getsource(loop_15m._execute_candidate)
    assert '"threshold_cell", "current_build_provisional"' in src
    # Lane block must trigger on any non-1.0 count, not only count > 1.0.
    assert "count != 1.0" in src
    assert "count = 1.0" in src


def test_allocator_prefit_does_not_shrink_bounded_lane():
    """The global-allocator cap pre-fit must not under-size a bounded lane."""
    import inspect

    from merid.prediction import agent_grid_15m

    src = inspect.getsource(agent_grid_15m.LeanAgentGrid15m.run_cycle)
    assert "_bounded_lane" in src
    assert '"threshold_cell", "current_build_provisional"' in src

# ---------------------------------------------------------------------------
# Bounded live-domain gate + tail LCB admission (2026-10-01 loss audit: the
# last three live losses were BTC YES@77 with LCB 1.68c < 2.5c required, XRP
# NO@75 emitted by the formula lane at TTE 823s -- outside the bounded
# 120-600s live domain -- with LCB 1.11c < 2.85c, and XRP NO@55 which only
# existed because a candidate-identity bug had disabled the per-asset cap).
# ---------------------------------------------------------------------------


def _mk_live_decision(*, asset="BTC", side="yes", tte=300.0, exec_price=0.77,
                      net_edge=0.0368, risk=0.02):
    """Minimal selected TradeDecision for apply_bounded_live_domain_gate."""
    bd = EdgeBreakdown(
        p_yes=0.84, p_no=0.16, selected_side=side,
        p_selected=0.84 if side == "yes" else 0.16,
        p_opposite=0.16 if side == "yes" else 0.84,
        executable_entry_price=exec_price,
        entry_fee=0.003, exit_cost_reserve=0.0,
        model_risk_reserve=risk,
        gross_edge=net_edge + 0.023, net_edge=net_edge,
    )
    return TradeDecision(
        run_id="t", decision_id="t", ticker=f"KX{asset}15M-X", asset=asset,
        timestamp_utc=_dt.datetime.now(_dt.timezone.utc),
        p_yes_raw=Decimal("0.84"), p_yes_calibrated=Decimal("0.84"),
        p_yes_uncertainty=Decimal(str(risk)),
        p_no_calibrated=Decimal("0.16"),
        seconds_to_expiry=Decimal(str(tte)),
        selected_outcome=side, selected_action="buy",
        selected_outcome_price=Decimal(str(exec_price)),
        edge_breakdown=bd,
        yes_edge_breakdown=bd if side == "yes" else None,
        no_edge_breakdown=bd if side == "no" else None,
        approved_size_cc=Decimal("100"),
        ev_gate_allowed=True,
        data_state="healthy",
        data_quality="live",
        regime="normal",
        regime_label="normal",
        confidence_valid=True,
        indicators={},
    )


def test_domain_gate_tte_ceiling_blocks_late_entry():
    """Formula-lane selection at TTE 823s (the XRP NO@75 loss) is vetoed."""
    d = _mk_live_decision(tte=823.0, exec_price=0.75)
    out = apply_bounded_live_domain_gate(
        d,
        yes_threshold=_decomp("BTC", "yes", 75, tte=300),
        no_threshold=_decomp("BTC", "no", 75, tte=300),
    )
    assert out.selected_outcome is None
    assert out.approved_size_cc == 0
    assert out.ev_gate_allowed is False
    assert out.no_trade_reason.startswith("bounded_domain_tte")
    rec = out.indicators["bounded_domain_gate"]
    assert rec["gate"] == "tte_ceiling"
    assert rec["seconds_to_expiry"] == 823.0


def test_domain_gate_tte_inside_domain_untouched():
    d = _mk_live_decision(tte=599.9, exec_price=0.45, net_edge=0.20)
    out = apply_bounded_live_domain_gate(
        d, yes_threshold=_decomp("BTC", "yes", 45, tte=300),
    )
    assert out.selected_outcome == "yes"


def test_domain_gate_tail_lcb_blocks_thin_tail_edge():
    """BTC YES@77 (lcb 1.68c < 2.5c required) must not admit."""
    thr = _decomp("BTC", "yes", 77, tte=300)
    d = _mk_live_decision(
        side="yes", exec_price=0.77,
        net_edge=float(thr.total) + 0.01,  # point EV clears, LCB does not
        risk=0.02,
    )
    out = apply_bounded_live_domain_gate(d, yes_threshold=thr)
    assert out.selected_outcome is None
    assert "tail_lcb_gate" in out.no_trade_reason
    rec = out.indicators["bounded_domain_gate"]
    assert rec["gate"] == "tail_lcb" and rec["price_cents"] == 77
    assert rec["lcb_cents"] < rec["required_cents"]


def test_domain_gate_tail_lcb_passes_when_edge_survives():
    """Deep edge in the tail (lcb >= required) still admits."""
    thr = _decomp("BTC", "yes", 77, tte=300)
    d = _mk_live_decision(
        side="yes", exec_price=0.77,
        net_edge=float(thr.total) + 0.05,  # lcb = total+0.03 > total
        risk=0.02,
    )
    out = apply_bounded_live_domain_gate(d, yes_threshold=thr)
    assert out.selected_outcome == "yes"
    rec = out.indicators["bounded_domain_gate"]
    assert rec["gate"] == "tail_lcb" and rec["passed"] is True


def test_domain_gate_tail_lcb_ignores_mid_band():
    """Sub-70c entries keep the plain point-EV bar (XRP NO@55 band)."""
    thr = _decomp("XRP", "no", 55, tte=300)
    d = _mk_live_decision(
        asset="XRP", side="no", exec_price=0.55,
        net_edge=float(thr.total) + 0.005,  # lcb below required, but mid-band
        risk=0.02,
    )
    out = apply_bounded_live_domain_gate(d, no_threshold=thr)
    assert out.selected_outcome == "no"
    assert "bounded_domain_gate" not in (out.indicators or {})


def test_domain_gate_end_to_end_tte_ceiling():
    """compute_trade_decision itself must veto a >600s live selection.

    Mirrors the XRP-2045 loss: XRP NO at ~77c executable, model ~0.82,
    TTE 823s — inside the formula lane's old window, outside the bounded
    live domain.
    """
    d = _decision(
        asset="XRP",
        spot_price=1.4863, strike_price=1.4886,
        seconds_to_expiry=823.0,
        yes_bid_cents=23.0, yes_ask_cents=25.0,
        no_bid_cents=75.0, no_ask_cents=77.0,
        p_yes_model=0.08,
        annualized_vol=0.30,
    )
    assert d.selected_outcome is None
    assert "bounded_domain_tte" in (d.no_trade_reason or "")
    assert d.indicators["bounded_domain_gate"]["gate"] == "tte_ceiling"


def test_entry_orders_share_bounded_rest_ttl():
    """All entry lanes must bind the 45s rest bound, not just cbp.

    Regression guard (2026-10-01 ETH NO@34 loss): non-cbp entry intents
    silently fell through to the 180s OrderIntent default; the order rested
    150s and filled into a repriced book at -23.5c stale edge.  Entries now
    share _entry_max_rest_seconds (env MERID_ENTRY_MAX_REST_S, default 45);
    exits keep the 180s default since they must fill rather than time out.
    """
    import inspect

    from merid import loop_15m

    src = inspect.getsource(loop_15m._execute_candidate)
    assert "entry_or_exit == \"entry\"" in src
    assert "_entry_max_rest_seconds()" in src
    assert "provisional_max_order_lifetime_s" in src
    # The intent must consume the resolved bound, not the bare 180 default.
    assert "max_rest_seconds=" in src

    fn_src = inspect.getsource(loop_15m._entry_max_rest_seconds)
    assert "MERID_ENTRY_MAX_REST_S" in fn_src


# ---------------------------------------------------------------------------
# Fill-space inversion guards (2026-10-01 audit): KalshiFill exposes
# canonical leg prices in the TRADED leg's space; a BUY_NO intent executes
# as a sell-YES leg whose price is YES-space.  fill_quality_tracker compared
# that against the NO-space limit/probability -> space-inverted fill EV and
# a false post_only_breach on every NO fill, which would suspend any cbp
# cell on first touch.  Same mixed-space comparison fed the side invariant
# (leg side 'yes' vs intent 'no' -> false side-flip suspension).
# ---------------------------------------------------------------------------


def _track_fill(tmp_path, monkeypatch, *, cell_px=34.0, leg_price_cents=66,
                leg_side="yes", leg_action="sell", p_selected=0.4253,
                limit=34):
    """Drive _detect_fill on a stub ledger; return (tracker, rec, cell)."""
    from types import SimpleNamespace

    from merid.execution import fill_quality_tracker as fqt

    monkeypatch.setenv("MERID_FILL_QUALITY_PATH", str(tmp_path / "fq.jsonl"))
    tracker = fqt.FillQualityTracker()
    cell = cbp.resolve_provisional_cell("ETH", "no", cell_px, 400.0)
    tracker.record_order(
        client_order_id="c1", intent_id="i1", order_id="o1",
        ticker="KXETH15M-X", side="BUY_NO", action="buy",
        limit_price_cents=limit, yes_bid_cents=63, yes_ask_cents=64,
        edge_pct=0.04, ev_net_cents=4.1, p_selected=p_selected,
        decision_id="d1", provisional_cell_id=cell.cell_id,
    )
    rec = tracker._records["c1"]
    fill = SimpleNamespace(
        order_id="o1", client_order_id="c1",
        side=leg_side, action=leg_action,
        canonical_position_side=leg_side,
        canonical_position_action=leg_action,
        price_cents=leg_price_cents,
        created_time=fqt._now(),
    )
    ledger = SimpleNamespace(get_fills_by_market=lambda _t: [fill])
    tracker._detect_fill(rec, ledger, fqt._now())
    return tracker, rec, cell


def test_no_fill_price_converted_to_outcome_space(tmp_path, monkeypatch):
    """ETH NO@34 (sell-YES@66 leg) must record fill price 34, not 66."""
    tracker, rec, cell = _track_fill(tmp_path, monkeypatch)
    assert rec.filled
    assert rec.fill_price_cents == 34
    ev = json.loads((tmp_path / "fq.jsonl").read_text().splitlines()[-1])
    assert ev["event"] == "fill"
    assert ev["fill_price_cents"] == 34
    assert abs(ev["gross_edge_cents_at_fill"] - 8.53) < 0.02
    # No false post-only breach / suspension on the provisional cell.
    st = cbp._load_state()
    outs = (st.get("outcomes") or {}).get(cell.cell_id, [])
    assert not any(o.get("kind") == "post_only_breach" for o in outs)
    assert cbp.get_cell_state(cell.cell_id) != cbp.CELL_STATE_SUSPENDED


def test_no_fill_sell_yes_leg_is_not_a_side_flip(tmp_path, monkeypatch):
    """The sell-YES leg of a BUY_NO fill must not flag the side invariant."""
    _track_fill(tmp_path, monkeypatch)
    cell = cbp.resolve_provisional_cell("ETH", "no", 34.0, 400.0)
    assert cbp.get_cell_state(cell.cell_id) != cbp.CELL_STATE_SUSPENDED


def test_true_side_flip_still_suspends(tmp_path, monkeypatch):
    """A real outcome mismatch (buy-YES fill on a BUY_NO intent) suspends."""
    tracker, rec, cell = _track_fill(
        tmp_path, monkeypatch, leg_side="yes", leg_action="buy",
        leg_price_cents=34,
    )
    assert cbp.get_cell_state(cell.cell_id) == cbp.CELL_STATE_SUSPENDED


# ---------------------------------------------------------------------------
# Adverse-selection reserve (2026-10-01): the EV gate's
# adverse_selection_reserve_per_contract input was hardcoded Decimal("0") so
# the authoritative net_ev never charged the pick-off cost, and the audit
# column adverse_selection_haircut_cents was always 0.  The reserve is now
# measured from the lane's own rolling 5s markouts (outcome-space), floored
# on cold cells, capped so one toxic window cannot veto the lane.
# ---------------------------------------------------------------------------


def test_adverse_selection_reserve_floor_when_cold():
    """No markout evidence -> bounded prior floor, not zero."""
    r = cbp.adverse_selection_reserve_cents("XRP", "no", 75.0, 400.0)
    assert r == pytest.approx(1.0)


def test_adverse_selection_reserve_from_cell_evidence():
    """Adverse markouts on the resolved cell raise the reserve (Q75 of cost)."""
    cell = cbp.resolve_provisional_cell("XRP", "no", 75.0, 400.0)
    st = cbp._load_state()
    st.setdefault("outcomes", {})[cell.cell_id] = [
        {"kind": "fill", "decision_id": "a", "markout_5s_cents": -4.0},
        {"kind": "fill", "decision_id": "b", "markout_5s_cents": -6.0},
    ]
    cbp._save_state()
    # costs [4,6] -> Q75 = 5.5 -> capped at 5.0
    assert cbp.adverse_selection_reserve_cents(
        "XRP", "no", 75.0, 400.0
    ) == pytest.approx(5.0)


def test_adverse_selection_reserve_widens_to_asset_side():
    """Cold cell inherits the asset+side aggregate evidence."""
    target = cbp.resolve_provisional_cell("ETH", "no", 35.0, 400.0)
    sibling = cbp.resolve_provisional_cell("ETH", "no", 75.0, 400.0)
    assert target.cell_id != sibling.cell_id
    st = cbp._load_state()
    st.setdefault("outcomes", {})[sibling.cell_id] = [
        {"kind": "fill", "decision_id": "a", "markout_5s_cents": -3.0},
        {"kind": "fill", "decision_id": "b", "markout_5s_cents": -1.0},
    ]
    cbp._save_state()
    # sibling costs [3,1] -> Q75 = 2.5 -> max(1.0, 2.5)
    assert cbp.adverse_selection_reserve_cents(
        "ETH", "no", 35.0, 400.0
    ) == pytest.approx(2.5)


def test_adverse_selection_reserve_healthy_cells_stay_at_floor():
    cell = cbp.resolve_provisional_cell("BTC", "yes", 45.0, 400.0)
    st = cbp._load_state()
    st.setdefault("outcomes", {})[cell.cell_id] = [
        {"kind": "fill", "decision_id": "a", "markout_5s_cents": 4.0},
    ]
    cbp._save_state()
    assert cbp.adverse_selection_reserve_cents(
        "BTC", "yes", 45.0, 400.0
    ) == pytest.approx(1.0)


def test_adverse_selection_reserve_regime_stratified():
    """Regime-tagged marks condition the estimate; other regimes don't leak in."""
    cell = cbp.resolve_provisional_cell("SOL", "no", 40.0, 400.0)
    st = cbp._load_state()
    st.setdefault("outcomes", {})[cell.cell_id] = [
        {"kind": "fill", "decision_id": "a", "markout_5s_cents": -8.0,
         "regime": "RALLY_CONFIRMED"},
        {"kind": "fill", "decision_id": "b", "markout_5s_cents": -7.0,
         "regime": "RALLY_CONFIRMED"},
        {"kind": "fill", "decision_id": "c", "markout_5s_cents": 3.0,
         "regime": "NEUTRAL"},
    ]
    cbp._save_state()
    # rally-conditioned: costs [8,7] -> Q75 7.75 -> cap 5.0
    assert cbp.adverse_selection_reserve_cents(
        "SOL", "no", 40.0, 400.0, regime_label="RALLY_CONFIRMED"
    ) == pytest.approx(5.0)
    # no regime requested -> all marks: costs [8,7,-3] -> Q75 = 7.5 -> cap 5.0
    assert cbp.adverse_selection_reserve_cents(
        "SOL", "no", 40.0, 400.0
    ) == pytest.approx(5.0)


def test_adverse_selection_reserve_regime_softens_when_warm():
    """Friendly regime-tagged marks lower the estimate vs hostile ones."""
    cell = cbp.resolve_provisional_cell("XRP", "no", 75.0, 400.0)
    st = cbp._load_state()
    st.setdefault("outcomes", {})[cell.cell_id] = [
        {"kind": "fill", "decision_id": "a", "markout_5s_cents": 2.0,
         "regime": "NEUTRAL"},
        {"kind": "fill", "decision_id": "b", "markout_5s_cents": 1.0,
         "regime": "NEUTRAL"},
        {"kind": "fill", "decision_id": "c", "markout_5s_cents": 0.5,
         "regime": "NEUTRAL"},
    ]
    cbp._save_state()
    # NEUTRAL costs [-2,-1,-0.5] -> Q75 = -0.75 -> floor 1.0
    assert cbp.adverse_selection_reserve_cents(
        "XRP", "no", 75.0, 400.0, regime_label="NEUTRAL"
    ) == pytest.approx(1.0)


def test_regime_markout_sample_count():
    """Countertrend cold-start gate counts only epoch+regime-tagged marks."""
    cell = cbp.resolve_provisional_cell("XRP", "no", 75.0, 400.0)
    st = cbp._load_state()
    st.setdefault("outcomes", {})[cell.cell_id] = [
        {"kind": "markout", "decision_id": "a", "markout_5s_cents": -1.0,
         "regime": "RALLY_CONFIRMED"},
        {"kind": "markout", "decision_id": "b", "markout_5s_cents": 2.0,
         "regime": "NEUTRAL"},
        {"kind": "markout", "decision_id": "c", "markout_5s_cents": -1.5,
         "regime": "RALLY_CONFIRMED", "policy_epoch": "pre_drawdown_legacy"},
    ]
    cbp._save_state()
    assert cbp.regime_markout_sample_count("XRP", "no") == 2
    assert cbp.regime_markout_sample_count("XRP", "no", "RALLY_CONFIRMED") == 1
    assert cbp.regime_markout_sample_count("XRP", "no", "SELL_OFF_CONFIRMED") == 0


def test_adverse_selection_reserve_disabled(monkeypatch):
    monkeypatch.setenv("MERID_ADV_SEL_RESERVE_ENABLED", "0")
    assert cbp.adverse_selection_reserve_cents("XRP", "no", 75.0, 400.0) == 0.0


def test_audit_side_row_carries_adverse_selection():
    """The audit side_ev row must record the decision's reserve in cents."""
    from dataclasses import replace

    from merid.execution import decision_audit_ledger as dal

    decision = _decision()
    assert decision.no_edge_breakdown is not None
    decision = replace(decision, adverse_selection_reserve=Decimal("0.015"))
    row = dal._build_side_ev_row(
        decision, "no", decision.indicators, None, None
    )
    assert row["adverse_selection_haircut_cents"] == pytest.approx(1.5)
