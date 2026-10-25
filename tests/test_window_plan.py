"""Deterministic per-window trade plan — unit tests.

Covers: $3 budget cap, integer centi-contract fit, contract/submission
quotas, per-asset cap, correlated same-side cap, TTE pacing with
carry-forward, pending reservation release, durable submission counting,
and deterministic candidate ordering.  No fills ledger / resting monitor
singletons exist in this process, so the authoritative committed scan
returns zeros — committed exposure under test is driven through the
plan's own pending reservation map plus monkeypatched scans.
"""

import os
import sys
from decimal import Decimal
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.prediction import window_plan as wp


@pytest.fixture(autouse=True)
def _plan_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MERID_WINDOW_PLAN_ENABLED", "1")
    monkeypatch.setenv("MERID_WINDOW_PLAN_BUDGET_USD", "3.00")
    monkeypatch.setenv("MERID_WINDOW_PLAN_MAX_CONTRACTS", "5")
    monkeypatch.setenv("MERID_WINDOW_PLAN_MAX_SUBMISSIONS", "6")
    monkeypatch.setenv("MERID_WINDOW_PLAN_ORDER_CAP_USD", "3.00")
    monkeypatch.setenv("MERID_WINDOW_PLAN_MAX_QTY_CC", "400")
    monkeypatch.setenv("MERID_WINDOW_PLAN_PER_ASSET_CAP_USD", "3.00")
    monkeypatch.setenv("MERID_WINDOW_PLAN_CORR_CAP_PCT", "0.75")
    monkeypatch.setenv("MERID_WINDOW_PLAN_CELL_SHARES", "0.35,0.45,0.20")
    monkeypatch.setenv("MERID_WINDOW_PLAN_PENDING_TTL_S", "45")
    monkeypatch.setenv("MERID_WINDOW_PLAN_LIFT_SIZING", "1")
    monkeypatch.setenv("MERID_MAX_CONTRACTS_PER_ORDER", "4")
    monkeypatch.setenv("MERID_WINDOW_PLAN_STATE_PATH", str(tmp_path / "wp.json"))
    wp.reset_for_tests()
    yield
    wp.reset_for_tests()


def _no_committed():
    return Decimal("0"), 0, {}, {}, True


def _pending_cost_real(st, now):
    """Real pending-cost total without the monitor/ledger reconciliation
    scan (no singletons in this process)."""
    total = Decimal("0")
    for p in st.pending.values():
        total += Decimal(str(p.get("cost_usd", 0) or 0))
    return total


def _patches(committed=None):
    return (
        patch.object(wp, "_committed_from_authoritative",
                     return_value=committed if committed is not None else _no_committed()),
        patch.object(wp, "_reconcile_pending", side_effect=_pending_cost_real),
    )


def test_budget_fit_and_lift():
    """90c taker: corr cap leaves a $2.25 same-side room ->
    floor(2.25/0.9063 * 100) = 248cc = 2.48 contracts (~$2.25)."""
    p1, p2 = _patches()
    with p1, p2:
        ok, count, reason, detail = wp.admit(
            ticker="KXBTC15M-26OCT251445-45", asset="BTC", side="yes",
            price_cents=90, requested_count=1.0, tte_s=500, decision_id="d1",
        )
    assert ok and reason == "window_plan_admitted"
    assert count == pytest.approx(2.48)
    assert float(detail["reserved_usd"]) <= 3.0


def test_no_lift_clamps_only(monkeypatch):
    monkeypatch.setenv("MERID_WINDOW_PLAN_LIFT_SIZING", "0")
    p1, p2 = _patches()
    with p1, p2:
        ok, count, _, _ = wp.admit(
            ticker="KXBTC15M-26OCT251445-45", asset="BTC", side="yes",
            price_cents=90, requested_count=1.0, tte_s=500, decision_id="d1",
        )
    assert ok and count == 1.0


def test_bounded_lane_never_lifted():
    p1, p2 = _patches()
    with p1, p2:
        ok, count, _, _ = wp.admit(
            ticker="KXBTC15M-26OCT251445-45", asset="BTC", side="yes",
            price_cents=90, requested_count=1.0, tte_s=500,
            decision_id="d1", allow_lift=False,
        )
    assert ok and count == 1.0


def test_budget_exhausted():
    """$2.90 already committed on the NO side: only $0.10 room -> no size."""
    committed = (Decimal("2.90"), 300, {"SOL": Decimal("2.90")}, {"no": Decimal("2.90")}, True)
    p1, p2 = _patches(committed)
    with p1, p2:
        ok, count, reason, _ = wp.admit(
            ticker="KXETH15M-26OCT251445-45", asset="ETH", side="yes",
            price_cents=90, requested_count=1.0, tte_s=500, decision_id="d2",
        )
    assert not ok and reason == "window_plan_no_size"
    assert count == 0.0


def test_corr_cap_same_side_blocks_opposite_allows():
    """$2.25 same-side committed: another YES admission is corr-capped,
    a NO admission fits in the remaining $0.75."""
    committed = (Decimal("2.25"), 250, {"BTC": Decimal("2.25")}, {"yes": Decimal("2.25")}, True)
    p1, p2 = _patches(committed)
    with p1, p2:
        ok_yes, _, reason_yes, _ = wp.admit(
            ticker="KXETH15M-26OCT251445-45", asset="ETH", side="yes",
            price_cents=60, requested_count=1.0, tte_s=500, decision_id="dy",
        )
        ok_no, count_no, reason_no, _ = wp.admit(
            ticker="KXETH15M-26OCT251445-45", asset="ETH", side="no",
            price_cents=60, requested_count=1.0, tte_s=500, decision_id="dn",
        )
    assert not ok_yes and reason_yes == "window_plan_corr_cap"
    assert ok_no and reason_no == "window_plan_admitted"
    # $0.75 room at ~$0.617/ct -> floor(0.75/0.6168*100)=121cc = 1.21 contracts
    assert count_no == pytest.approx(1.21)


def test_per_asset_cap():
    committed = (Decimal("1.80"), 200, {"BTC": Decimal("1.80")}, {"yes": Decimal("1.80")}, True)
    p1, p2 = _patches(committed)
    with p1, p2, patch.object(wp, "plan_per_asset_cap_usd", return_value=Decimal("2.00")):
        ok, count, reason, detail = wp.admit(
            ticker="KXBTC15M-26OCT251445-45", asset="BTC", side="yes",
            price_cents=90, requested_count=1.0, tte_s=500, decision_id="d1",
        )
    # $0.20 asset room at ~$0.91/ct -> 0 contracts fit under the asset cap
    assert not ok and reason == "window_plan_no_size"


def test_submission_cap_and_pacing():
    """Cell allowances: early(>300s)=2, mid(120-300)=4, late(<=120)=6."""
    st = wp._get_state("26OCT251445")
    st.submissions = 2  # early allowance exhausted
    p1, p2 = _patches()
    with p1, p2:
        ok_early, _, reason_early, _ = wp.admit(
            ticker="KXBTC15M-26OCT251445-45", asset="BTC", side="yes",
            price_cents=50, requested_count=1.0, tte_s=500, decision_id="e3",
        )
        ok_mid, count_mid, reason_mid, _ = wp.admit(
            ticker="KXBTC15M-26OCT251445-45", asset="BTC", side="yes",
            price_cents=50, requested_count=1.0, tte_s=200, decision_id="m1",
        )
    assert not ok_early and reason_early == "window_plan_pacing"
    assert ok_mid and reason_mid == "window_plan_admitted"

    st2 = wp._get_state("26OCT251445")
    st2.submissions = 6
    p3, p4 = _patches()
    with p3, p4:
        ok, _, reason, _ = wp.admit(
            ticker="KXBTC15M-26OCT251445-45", asset="BTC", side="yes",
            price_cents=50, requested_count=1.0, tte_s=60, decision_id="l1",
        )
    assert not ok and reason == "window_plan_submission_cap"


def test_contract_cap():
    committed = (Decimal("1.0"), 500, {}, {}, True)  # 5.00 contracts already open
    p1, p2 = _patches(committed)
    with p1, p2:
        ok, _, reason, _ = wp.admit(
            ticker="KXBTC15M-26OCT251445-45", asset="BTC", side="yes",
            price_cents=20, requested_count=1.0, tte_s=500, decision_id="d1",
        )
    assert not ok and reason == "window_plan_contract_cap"


def test_record_submission_durable_and_release(tmp_path):
    p1, p2 = _patches()
    with p1, p2:
        ok, _, _, _ = wp.admit(
            ticker="KXBTC15M-26OCT251445-45", asset="BTC", side="yes",
            price_cents=90, requested_count=1.0, tte_s=500, decision_id="d1",
        )
        assert ok
        wp.record_submission("d1", client_order_id="coid_1", ticker="KXBTC15M-26OCT251445-45")
    st = wp._get_state("26OCT251445")
    assert st.submissions == 1
    # Restart simulation: state reloads the durable count for this window.
    wp.reset_for_tests()
    st2 = wp._get_state("26OCT251445")
    assert st2.submissions == 1
    assert "coid_1" in st2.submitted_ids

    # Pre-wire death releases the budget reservation.
    p3, p4 = _patches()
    with p3, p4:
        ok2, _, _, _ = wp.admit(
            ticker="KXETH15M-26OCT251445-45", asset="ETH", side="no",
            price_cents=50, requested_count=1.0, tte_s=500, decision_id="d2",
        )
        assert ok2
        wp.release_reservation("d2")
        st3 = wp._get_state("26OCT251445")
        assert "d2" not in st3.pending


def test_sort_deterministic():
    cands = [
        {"ticker": "KXSOL15M-26OCT251445-45", "edge_pct": 0.05, "confidence": 0.9, "candidate_id": "c3"},
        {"ticker": "KXBTC15M-26OCT251445-45", "edge_pct": 0.07, "confidence": 0.5, "candidate_id": "c1"},
        {"ticker": "KXETH15M-26OCT251445-45", "edge_pct": 0.07, "confidence": 0.5, "candidate_id": "c2"},
    ]
    out = wp.sort_candidates(cands)
    # equal edge -> confidence tie -> candidate_id tie-break keeps order stable
    assert [c["candidate_id"] for c in out] == ["c1", "c2", "c3"]
    out2 = wp.sort_candidates(reversed(cands))
    assert [c["candidate_id"] for c in out2] == ["c1", "c2", "c3"]


def test_disabled_passthrough_not_used_here():
    # plan_enabled is checked by callers; module functions still behave when
    # invoked directly — the flag gates call sites, not the math.
    assert wp.plan_enabled() is True

