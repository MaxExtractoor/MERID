"""Canary-lane bound propagation + allocator canonical-EV regression.

Regression target: 2026-10-06 post-restart cohort where every canary
admission (edge >= canary floor but < the post-caution route bound) was
guaranteed to die downstream — the candidate carried the route bound as
``effective_required_edge_cents``, so the allocator's lane-bound re-check
always vetoed it as EXPECTED_VALUE_BELOW_MINIMUM and the loop's EV re-gate
compared against the wrong floor.  Additionally the allocator compared raw
``edge_pct`` while the decision-side gate enforced the EPC-adjusted
``gate_ev`` — a second EV re-computation that vetoed EPC-rescued
candidates a layer downstream (e.g. gate 6.95c vs bound 5c, allocator
rejecting raw 3.04c < 5c).

Contract after the fix:
  * ``effective_required_edge_cents`` is the bound the candidate was
    actually admitted under — the canary floor for canary lanes, the cell
    bound for cell lanes, the enforced route bound otherwise.
  * The allocator re-checks the same quantity the gate enforced
    (``gate_ev_cents`` when present, ``edge_pct`` fallback).
"""
from __future__ import annotations

import math
from typing import Optional

import pytest

from merid.prediction.trade_decision import (
    MERID_CANARY_MIN_EDGE,
    compute_trade_decision,
)
from merid.risk.profiles.global_allocator import (
    GlobalAllocator,
    OrderCandidate,
)


# ── decision-level fixture (mirrors the reconciliation suite) ────────


def _patch_economics_isolation(monkeypatch) -> None:
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_TRADE_DECISION_ALLOW_HYBRID_P", True
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_TAIL_CALIBRATION_ENABLED", False
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_MIN_HELD_PRICE_CENTS", 0.0
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_FADE_BLOCK_MIN_LEAN_CENTS", 99.0
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_MARKET_ANCHOR_MIN_W", 0.0
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision.MERID_MARKET_ANCHOR_MAX_W", 0.0
    )
    # EPC off -> the effective edge compared at the gate is exactly net_edge,
    # keeping the fixture inside the canary window deterministically.
    monkeypatch.setenv("MERID_EMPIRICAL_CAL_MODE", "off")
    # No live evidence / tail calibrator -> evidence_ok stays True; the
    # production calibrator blocks every canary-window edge in this fixture.
    monkeypatch.setattr(
        "merid.prediction.trade_decision.load_tail_calibrator",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "merid.prediction.trade_decision._load_live_evidence",
        lambda *a, **k: None,
    )


def _canary_decision(monkeypatch, *, route: str = "taker"):
    """Decision whose best-side edge clears the canary floor (1.5c) but not
    the enforced bound (5c) -> canary admission on a pristine quote."""
    _patch_economics_isolation(monkeypatch)
    return compute_trade_decision(
        run_id="test_run",
        decision_id="test_canary",
        ticker="KXBTC15M-26OCT060000-00",
        asset="BTC",
        spot_price=100.0,
        strike_price=100.0,
        seconds_to_expiry=600.0,
        yes_bid_cents=83.0,
        yes_ask_cents=83.0,
        no_bid_cents=17.0,
        no_ask_cents=17.0,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=1.0,
        annualized_vol=0.60,
        model_uncertainty=0.05,
        data_quality="live",
        regime="normal",
        min_required_edge=0.05,
        settlement_reference="cfb_rti_live",
        p_yes_model=0.73,  # p_no=0.27 -> net_edge = 0.27-0.24 = +3c
        entry_price_basis="ask",
        adverse_selection_reserve=0.0,
        route=route,
        indicators={"quote_owner": "WS_FRESH_VERIFIED"},
    )


# ── canary admission stamps the lane floor as the admission bound ────


@pytest.mark.parametrize("route,expected_lane", [("taker", "canary_taker"), ("maker", "canary_maker")])
def test_canary_admission_stamps_lane_floor_as_required_edge(
    monkeypatch, route, expected_lane
):
    d = _canary_decision(monkeypatch, route=route)
    assert d.selected_outcome == "no", (
        "fixture must land in the canary window; got lane=%s reason=%s"
        % (d.indicators.get("decision_lane"), d.no_trade_reason)
    )
    assert d.indicators.get("decision_lane") == expected_lane
    # The admission bound downstream consumers re-check must be the canary
    # floor — the bound the candidate was actually admitted under.
    assert d.indicators["no_effective_required_edge_cents"] == pytest.approx(
        MERID_CANARY_MIN_EDGE * 100.0
    )
    # The superseded full route bound stays attributable in the lane record —
    # strictly above the canary floor (that's what made this a canary
    # admission rather than a normal qualify).  The indicators record key is
    # the historical "canary_taker" label for both routes; the lane name is
    # carried inside the record.
    lane_rec = d.indicators.get("canary_taker") or {}
    assert lane_rec.get("lane") == expected_lane
    assert lane_rec.get("full_bound_cents") is not None
    assert lane_rec["full_bound_cents"] > MERID_CANARY_MIN_EDGE * 100.0
    assert lane_rec.get("canary_floor_cents") == pytest.approx(
        MERID_CANARY_MIN_EDGE * 100.0
    )


def test_non_canary_selection_keeps_route_bound(monkeypatch):
    """A full-bound pass must keep the enforced bound as effective_required
    — the canary restamp must not leak onto normal admissions."""
    _patch_economics_isolation(monkeypatch)
    d = compute_trade_decision(
        run_id="test_run",
        decision_id="test_normal",
        ticker="KXBTC15M-26OCT060000-00",
        asset="BTC",
        spot_price=100.0,
        strike_price=100.0,
        seconds_to_expiry=600.0,
        yes_bid_cents=83.0,
        yes_ask_cents=83.0,
        no_bid_cents=17.0,
        no_ask_cents=17.0,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=1.0,
        annualized_vol=0.60,
        model_uncertainty=0.05,
        data_quality="live",
        regime="normal",
        min_required_edge=0.02,
        settlement_reference="cfb_rti_live",
        p_yes_model=0.637,  # net_edge ~= 10.3c >> 2c bound
        entry_price_basis="ask",
        route="taker",
        indicators={"quote_owner": "WS_FRESH_VERIFIED"},
    )
    assert d.selected_outcome == "no"
    assert "canary" not in str(d.indicators.get("decision_lane"))
    # Route bound preserved — the canary floor restamp must not leak onto
    # normal admissions (bound = min_edge + margin components > floor).
    assert d.indicators["no_effective_required_edge_cents"] > (
        MERID_CANARY_MIN_EDGE * 100.0
    )


# ── allocator: compare the quantity the gate enforced ────────────────


def _alloc() -> GlobalAllocator:
    return GlobalAllocator(venue_cap_usd=50.00, min_edge_pct=0.025)


def _candidate(**kw) -> OrderCandidate:
    base = dict(
        asset="BTC",
        ticker="KXBTC15M-TEST",
        side="no",
        action="buy",
        price_cents=83,
        count=1.0,
        edge_pct=3.04,
        confidence=0.80,
        model_prob=0.27,
        agent_name="BTC_15M",
        candidate_id="cand_test",
    )
    base.update(kw)
    return OrderCandidate(**base)


def test_allocator_lane_bound_compares_gate_ev_not_raw_edge():
    """EPC-rescued candidate: gate_ev >= bound while raw edge < bound must
    NOT be vetoed a second time on the raw metric (the 2026-10-06
    EXPECTED_VALUE_BELOW_MINIMUM dead-letter)."""
    alloc = _alloc()
    cand = _candidate(
        decision_lane="threshold_cell",
        threshold_cell_id="cell_1",
        effective_required_edge_cents=5.0,
        gate_ev_cents=6.95,   # what the gate compared
        edge_pct=3.04,        # raw net_ev — below the bound
    )
    chosen = alloc.allocate([cand])
    assert any(c.candidate_id == "cand_test" for c in chosen)


def test_allocator_canary_candidate_passes_at_lane_floor():
    """Canary admission (effective bound = 1.5c floor) passes the EDGE
    re-check at its lane bound rather than the superseded route bound."""
    alloc = _alloc()
    cand = _candidate(
        decision_lane="canary_maker",
        effective_required_edge_cents=1.5,
        gate_ev_cents=3.04,
        edge_pct=3.04,
    )
    chosen = alloc.allocate([cand])
    assert any(c.candidate_id == "cand_test" for c in chosen)


def test_allocator_canary_below_floor_still_rejected():
    """Below the canary floor the lane bound still vetoes — no bypass."""
    alloc = _alloc()
    cand = _candidate(
        decision_lane="canary_maker",
        effective_required_edge_cents=1.5,
        gate_ev_cents=1.0,
        edge_pct=1.0,
    )
    chosen = alloc.allocate([cand])
    assert not any(c.candidate_id == "cand_test" for c in chosen)


def test_allocator_raw_fallback_when_gate_ev_absent():
    """Candidates without a gate_ev stamp keep the raw-edge comparison —
    the fallback preserves the pre-fix conservative check."""
    alloc = _alloc()
    cand = _candidate(
        decision_lane="threshold_cell",
        threshold_cell_id="cell_1",
        effective_required_edge_cents=5.0,
        gate_ev_cents=None,
        edge_pct=3.04,
    )
    chosen = alloc.allocate([cand])
    assert not any(c.candidate_id == "cand_test" for c in chosen)


# ── telemetry: the admission lane is recorded on the side_ev row ─────


def test_side_ev_row_carries_decision_lane(monkeypatch):
    """selected=1 & passed_edge_gate=0 is interpretable only with the
    admission lane on the row."""
    from merid.execution.decision_audit_ledger import _build_side_ev_row

    d = _canary_decision(monkeypatch)
    row = _build_side_ev_row(d, "no", dict(d.indicators or {}), None, None)
    assert row["decision_lane"] == "canary_taker"
    assert row["selected"] is True


# ── durable attempt record carries the submitted parameters ──────────


def test_order_attempt_payload_records_submitted_order():
    from decimal import Decimal
    from merid.event_venues.kalshi.order_identity import _build_record
    from merid.event_venues.kalshi.order_router import OrderIntent

    intent = OrderIntent(
        ticker="KXDOGE15M-26OCT060645-45",
        side="no",
        action="buy",
        price_cents=83,
        count=3.0,
        count_fp=Decimal("3.0"),
        decision_lane="maker_bid",
        liquidity_role="maker",
    )
    rec = _build_record("oa_test", "coid_test", intent, "fp")
    import json as _json

    payload = _json.loads(rec.payload_json)
    order = payload["order"]
    assert order["ticker"] == "KXDOGE15M-26OCT060645-45"
    assert order["side"] == "no"
    assert order["action"] == "buy"
    assert order["price_cents"] == 83
    assert order["count_fp"] == "3.000000"
    assert order["decision_lane"] == "maker_bid"
    assert order["liquidity_role"] == "maker"


def test_order_attempt_status_update_merges_payload(tmp_path):
    """update_status(payload=...) must merge, not replace — the seeded
    order parameters are the audit record of what was submitted."""
    import json as _json
    from decimal import Decimal
    from merid.event_venues.kalshi.order_attempt_store import OrderAttemptStore
    from merid.event_venues.kalshi.order_identity import _build_record
    from merid.event_venues.kalshi.order_router import OrderIntent

    store = OrderAttemptStore(db_path=str(tmp_path / "attempts.db"))
    intent = OrderIntent(
        ticker="KXDOGE15M-26OCT060645-45",
        side="no",
        action="buy",
        price_cents=83,
        count=3.0,
        count_fp=Decimal("3.0"),
        decision_lane="canary_maker",
    )
    rec = _build_record("oa_merge", "coid_merge", intent, "fp")
    store.persist_attempt(rec)

    store.update_status(
        "oa_merge",
        "CANCELED",
        payload={"terminalized_by": "post_route_cleanup", "route_reason": "timeout"},
    )
    row = store._get_conn().execute(
        "SELECT payload_json FROM order_attempts WHERE order_attempt_id = 'oa_merge'"
    ).fetchone()
    payload = _json.loads(row[0])
    # Seeded order fields survive the status-transition write.
    assert payload["order"]["ticker"] == "KXDOGE15M-26OCT060645-45"
    assert payload["order"]["count_fp"] == "3.000000"
    assert payload["order"]["decision_lane"] == "canary_maker"
    # The transition metadata is appended, not lost.
    assert payload["terminalized_by"] == "post_route_cleanup"


# ── lane suppression is a persisted lifecycle event ─────────────────


def test_lane_suppressed_event_persists(tmp_path):
    """A post-selection lane suppression must produce a durable event —
    the 2026-10-06 silent drop (selected=1, zero downstream events)."""
    import sqlite3
    from merid.execution.decision_audit_ledger import (
        DecisionAuditLedger,
        DECISION_EVENT_LANE_SUPPRESSED,
    )

    ledger = DecisionAuditLedger(db_path=tmp_path / "audit.db")
    ledger._ensure_db()
    event_id = ledger.append_decision_event(
        decision_id="cand_754e:maker",
        event_type=DECISION_EVENT_LANE_SUPPRESSED,
        stage="ALLOCATION",
        reason_code="canary_daily_cap_or_window",
        reason_detail={"side": "no", "lane": "canary_maker"},
        ticker="KXDOGE15M-26OCT060645-45",
        asset="DOGE",
    )
    assert event_id
    conn = sqlite3.connect(str(tmp_path / "audit.db"))
    row = conn.execute(
        "SELECT event_type, stage, reason_code, reason_detail_json FROM "
        "strategy_decision_events WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "LANE_SUPPRESSED"
    assert row[1] == "ALLOCATION"
    assert row[2] == "canary_daily_cap_or_window"
    import json as _json

    detail = _json.loads(row[3])
    assert detail["lane"] == "canary_maker"
