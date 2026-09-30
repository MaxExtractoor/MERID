"""Shared execution-lane contract tests (2026-09-30).

Proves the canonical execution contract is identical for every crypto-15m
asset: BTC, ETH, SOL, XRP, DOGE.

  * a threshold-cell intent's immutable ExecutionPolicy cannot be downgraded
    to a marketable/taker order by maker/taker policy (the DOGE defect:
    aggressiveness recompute -> post_only=False on a lane that requires
    post-only),
  * a pre-wire stale-decision rejection releases the cell submission
    reservation AND counts toward router-reject suspension bookkeeping,
  * a decision older than the 3.5s ceiling can never reach the wire,
  * the cell lifecycle emits the complete terminal sequence for every
    pre-wire rejection.

State isolation: MERID_THRESHOLD_CELL_STATE_PATH / lifecycle path point at
tmp_path via the fixture, so no test touches production lane accounting.
"""

from __future__ import annotations

import json
import os
import time as _time

import pytest

import merid.prediction.threshold_cells as _tc
from merid.prediction.threshold_cells import (
    emit_cell_lifecycle,
    record_cell_pre_wire_reject,
    record_cell_submission,
    release_cell_submission_reservation,
    reset_cell_state_cache,
)


ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
TICKERS = {a: f"KX{a}15M-TEST{a}" for a in ASSETS}


@pytest.fixture(autouse=True)
def _isolate_lane_state(monkeypatch, tmp_path):
    monkeypatch.setenv("MERID_THRESHOLD_CELL_STATE_PATH", str(tmp_path / "cells.json"))
    monkeypatch.setenv(
        "MERID_THRESHOLD_CELL_LIFECYCLE_PATH", str(tmp_path / "lifecycle.jsonl")
    )
    reset_cell_state_cache()


def _cell_id(asset: str) -> str:
    return f"{asset.lower()}_no_40_60_t120_600"


def _cell_intent(asset: str, *, aggressiveness: float = 0.0, snapshot_age_s: float = 0.0):
    """Minimal threshold-cell intent with the immutable lane policy attached."""
    from merid.event_venues.kalshi.order_router import ExecutionPolicy, OrderIntent

    intent = OrderIntent(
        ticker=TICKERS[asset],
        price_cents=45,
        count=1.0,
        side="no",
        action="buy",
        post_only=True,
        aggressiveness=aggressiveness,
        decision_lane="threshold_cell",
        threshold_cell_id=_cell_id(asset),
        admission_owner="threshold_cell",
        entry_or_exit="entry",
        execution_policy=ExecutionPolicy(
            lane="threshold_cell",
            required_post_only=True,
            required_liquidity_role="maker",
            allow_taker_fallback=False,
            max_reprice_attempts=1,
            max_order_lifetime_s=60,
        ),
    )
    if snapshot_age_s:
        intent.snapshot_ts = _time.time() - snapshot_age_s
    return intent


def _lifecycle_stages(path_env: str = "MERID_THRESHOLD_CELL_LIFECYCLE_PATH"):
    path = os.environ[path_env]
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return [
            json.loads(line).get("stage")
            for line in fh
            if line.strip()
        ]


# ---------------------------------------------------------------------------
# 1. Immutable post-only contract — identical for all five assets
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("asset", ASSETS)
def test_execution_policy_is_immutable(asset):
    from merid.event_venues.kalshi.order_router import ExecutionPolicy

    policy = ExecutionPolicy(lane="threshold_cell", required_post_only=True)
    with pytest.raises(Exception):
        policy.required_post_only = False
    with pytest.raises(Exception):
        policy.allow_taker_fallback = True


@pytest.mark.parametrize("asset", ASSETS)
def test_threshold_cell_post_only_cannot_be_downgraded(asset):
    """The DOGE defect: aggressiveness=1.0 must not flip a cell order to taker."""
    from merid.event_venues.kalshi.maker_taker_integration import (
        apply_maker_taker_policy,
    )

    intent = _cell_intent(asset, aggressiveness=1.0)  # marketable posture
    apply_maker_taker_policy(intent)

    assert intent.post_only is True
    assert getattr(intent, "_execution_policy_violation", None) == (
        "PRE_WIRE_POST_ONLY_UNAVAILABLE"
    )


@pytest.mark.parametrize("asset", ASSETS)
def test_threshold_cell_post_only_preserved_for_resting_intent(asset):
    """A resting cell intent keeps post_only even if policy recommends taker."""
    from merid.event_venues.kalshi.maker_taker_integration import (
        apply_maker_taker_policy,
    )

    intent = _cell_intent(asset, aggressiveness=0.0)
    apply_maker_taker_policy(intent)

    assert intent.post_only is True
    assert getattr(intent, "_execution_policy_violation", None) is None


@pytest.mark.parametrize("asset", ASSETS)
def test_aggressiveness_never_recomputed_for_post_only_lane(asset):
    """order_router must not recompute posture for lane-owned intents."""
    from merid.event_venues.kalshi.order_router import _intent_requires_post_only

    intent = _cell_intent(asset)
    assert _intent_requires_post_only(intent) is True

    # Non-lane intents are unaffected — posture remains recomputable.
    intent.execution_policy = None
    intent.decision_lane = "formula"
    intent.post_only = False
    assert _intent_requires_post_only(intent) is False


# ---------------------------------------------------------------------------
# 2. Pre-wire rejection → complete cell bookkeeping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("asset", ASSETS)
def test_stale_pre_wire_rejection_releases_reservation_and_records_reject(asset):
    cell = _cell_id(asset)
    decision_id = f"dec-{asset}"
    intent_id = f"int-{asset}"

    # Candidate emission reserves a submission slot.
    record_cell_submission(cell_id=cell, decision_id=decision_id)
    assert _tc.cell_submissions_today() == 1
    st = _tc._load_state()
    assert st["submissions"][cell] == 1

    record_cell_pre_wire_reject(
        cell_id=cell,
        decision_id=decision_id,
        intent_id=intent_id,
        rejection_code="stale_decision_dropped:age_ms=12568",
        stage="pre_wire",
        asset=asset,
        ticker=TICKERS[asset],
    )

    st = _tc._load_state()
    # Reservation released — the slot is not burned by a no-wire attempt.
    assert st["submissions"][cell] == 0
    assert _tc.cell_submissions_today() == 0
    # Router reject counted toward the suspension rules.
    assert st["router_rejects"][cell] == 1
    assert st["router_consecutive_rejects"][cell] == 1
    # Idempotent: a second release attempt must not double-decrement.
    assert (
        release_cell_submission_reservation(
            cell, intent_id=intent_id, decision_id=decision_id
        )
        is False
    )
    assert _tc._load_state()["submissions"][cell] == 0


@pytest.mark.parametrize("asset", ASSETS)
def test_threshold_cell_lifecycle_is_complete(asset):
    """Every pre-wire reject ends in the exact terminal sequence."""
    cell = _cell_id(asset)
    emit_cell_lifecycle("candidate_emitted", threshold_cell_id=cell, asset=asset)
    emit_cell_lifecycle("intent_created", threshold_cell_id=cell, asset=asset)

    record_cell_pre_wire_reject(
        cell_id=cell,
        decision_id=f"dec-{asset}",
        intent_id=f"int-{asset}",
        rejection_code="stale_decision_dropped",
        asset=asset,
        ticker=TICKERS[asset],
    )

    assert _lifecycle_stages() == [
        "candidate_emitted",
        "intent_created",
        "router_rejected",
        "submission_reservation_released",
        "lane_state_updated",
    ]


# ---------------------------------------------------------------------------
# 3. Stale-decision ceiling — cannot submit beyond 3.5s
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("asset", ASSETS)
def test_execution_latency_breach_cannot_submit(asset):
    """A 3.5s+ decision must be dropped pre-wire (stale gate stays in place)."""
    from merid.event_venues.kalshi.order_router import _prepare_order_for_gate
    from merid.prediction.trading_mode import TradingMode

    intent = _cell_intent(asset, snapshot_age_s=4.0)  # 4000ms > 3500ms ceiling
    rejection, _state = _prepare_order_for_gate(intent, TradingMode.LIVE, _time.monotonic())

    assert rejection is not None
    assert rejection.status == "rejected"
    assert rejection.reason.startswith("stale_decision_dropped")
    assert rejection.submission_attempted is False


@pytest.mark.parametrize("asset", ASSETS)
def test_fresh_decision_passes_stale_gate(asset):
    """A fresh cell intent clears the stale-decision band (may still be
    rejected downstream on data, but never as stale_decision_dropped)."""
    from merid.event_venues.kalshi.order_router import _prepare_order_for_gate
    from merid.prediction.trading_mode import TradingMode

    intent = _cell_intent(asset, snapshot_age_s=0.5)
    rejection, _state = _prepare_order_for_gate(intent, TradingMode.LIVE, _time.monotonic())

    if rejection is not None:
        assert not str(rejection.reason).startswith("stale_decision")


# ---------------------------------------------------------------------------
# 4. Stage-latency record — one record per attempt, monotonic-based
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("asset", ASSETS)
def test_execution_stage_latency_record(asset, caplog):
    from merid.event_venues.kalshi.order_router import (
        _emit_execution_stage_latency,
        _exec_stamp,
        OrderResult,
    )
    from merid.prediction.trading_mode import TradingMode

    intent = _cell_intent(asset)
    _exec_stamp(intent, "intent_created")
    _exec_stamp(intent, "canonical_pass")
    _exec_stamp(intent, "risk_check_start")
    _exec_stamp(intent, "risk_check_end")
    _exec_stamp(intent, "router_terminal")

    result = OrderResult(
        status="rejected", mode=TradingMode.LIVE, reason="stale_decision_dropped"
    )
    with caplog.at_level("INFO"):
        _emit_execution_stage_latency(intent, result)

    rec = next(
        json.loads(m.message.split("EXECUTION-STAGE-LATENCY ", 1)[1])
        for m in caplog.records
        if "EXECUTION-STAGE-LATENCY" in m.message
    )
    assert rec["event"] == "execution_stage_latency"
    assert rec["asset"] == asset
    assert rec["lane"] == "threshold_cell"
    assert rec["threshold_cell_id"] == _cell_id(asset)
    assert rec["risk_ms"] is not None and rec["risk_ms"] >= 0
    assert rec["total_to_terminal_ms"] is not None
    assert rec["outcome"] == "rejected"
