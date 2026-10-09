"""Residual-exposure branch for non-executable protective exits.

2026-10-04: when the execution firewall rejects a stop IOC with
``limit_not_executable``, the position must end in an explicit durable
state — a genuine hold decision, a bounded degraded IOC, or an explicit
could-not-decide/risk-breach — never a silent carry to expiry.  The
ResidualExitTracker owns idempotency across monitor cycles.
"""

import asyncio
import types

import merid.event_venues.kalshi.stop_candidate as sc
from merid.event_venues.kalshi.residual_exit import (
    ResidualExitTracker,
    ResidualStatus,
)


def _candidate(**kw):
    args = dict(
        market_ticker="KXSOL15M-TEST",
        trigger_reason="HARD_STOP",
        position_from_exchange_cc=-300,  # 3 NO contracts
        candidate_id="sc-test-dg",
        seconds_to_expiry=400.0,
        quote_age_ms=250,
    )
    args.update(kw)
    return sc.StopCandidate(**args)


def _reject_result(vwap=18, limit=22):
    reason = "firewall:firewall_rejected:limit_not_executable:"
    if vwap is not None:
        reason += f"limit={limit}:vwap={vwap}"
    else:
        reason += f"limit={limit}:vwap=unknown"
    return types.SimpleNamespace(
        status="rejected", reason=reason, price_cents=limit,
    )


class _FakeLedger:
    def __init__(self):
        self.records = []

    def record_residual_decision(self, candidate, record):
        self.records.append(record)


def _patch_env(monkeypatch, tmp_path):
    ledger = _FakeLedger()
    tracker = ResidualExitTracker(tmp_path / "residuals.json")
    monkeypatch.setattr(sc, "get_stop_candidate_ledger", lambda: ledger)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.residual_exit.get_residual_exit_tracker",
        lambda path=None: tracker,
    )
    monkeypatch.setattr(sc, "_resolve_position_epoch", lambda t: "fill-ep-1")
    monkeypatch.setattr(sc, "_get_market_state", lambda t: (None, None))
    monkeypatch.setattr(sc, "_get_executable_exit_cents", lambda s, side: 18)
    return ledger, tracker


def _run(cand, result, **kw):
    return asyncio.run(
        sc._maybe_degraded_stop_exit(
            cand, result, held_side="no", held_qty_cc=300, **kw
        )
    )


def test_parse_non_executable_vwap():
    assert sc.parse_non_executable_vwap_cents(
        "firewall:firewall_rejected:limit_not_executable:limit=22:vwap=18"
    ) == 18
    assert sc.parse_non_executable_vwap_cents(
        "firewall:firewall_rejected:insufficient_depth:depth=0"
    ) is None
    assert sc.parse_non_executable_vwap_cents("stop_candidate_edge_not_breached") is None
    assert sc.parse_non_executable_vwap_cents(None) is None


def test_hold_to_settlement_when_fair_above_degraded(monkeypatch, tmp_path):
    """Fair value still above the degraded exit proceeds -> genuine hold
    for a non-mandatory trigger.  (Mandatory hard-risk triggers bypass this
    EV hold — see test_mandatory_trigger_bypasses_fair_hold.)"""
    ledger, tracker = _patch_env(monkeypatch, tmp_path)
    cand = _candidate(trigger_reason="TRAILING_STOP", fair_value_cents=25)  # 25 + costs(2) + hyst(1) > vwap 18
    _run(cand, _reject_result())
    assert ledger.records[0]["decision"] == "HOLD_TO_SETTLEMENT_APPROVED"
    assert ledger.records[0]["basis"] == "fair_above_degraded_exit_value"
    res = next(iter(tracker._records.values()))
    assert res.status == ResidualStatus.HOLD_APPROVED.value


def test_mandatory_trigger_bypasses_fair_hold(monkeypatch, tmp_path):
    """2026-10-09 precedence: a HARD_STOP is a mandatory risk exit — the
    discretionary "fair > vwap -> hold" comparison must not veto it.  The
    candidate proceeds to the degraded-exit path (bounded, repriced to the
    fresh book) instead of riding to settlement on a lagging model fair."""
    ledger, tracker = _patch_env(monkeypatch, tmp_path)
    cand = _candidate(trigger_reason="HARD_STOP", fair_value_cents=25)
    _run(cand, _reject_result())
    rec = ledger.records[0]
    assert rec["mandatory_fair_bypass"] is True
    # fair=25 > vwap=18 would have been a hold under the old precedence;
    # now the candidate reaches the submission gate (observe-only here).
    assert rec["decision"] == "DEGRADED_EXIT_APPROVED"
    assert rec["basis"] == "observe_only_submission_disabled"


def test_data_unavailable_without_fair_value(monkeypatch, tmp_path):
    """No model basis is could-not-decide — not a positive hold."""
    ledger, _ = _patch_env(monkeypatch, tmp_path)
    cand = _candidate(fair_value_cents=None)
    _run(cand, _reject_result())
    rec = ledger.records[0]
    assert rec["decision"] == "RESIDUAL_EXIT_DATA_UNAVAILABLE"
    assert rec["basis"] == "no_fair_value"


def test_data_unavailable_malformed_vwap(monkeypatch, tmp_path):
    """limit_not_executable with an unparsable/zero VWAP must still produce
    a durable could-not-decide record — never a silent skip."""
    ledger, _ = _patch_env(monkeypatch, tmp_path)
    cand = _candidate(fair_value_cents=10)
    _run(cand, _reject_result(vwap=None))
    assert ledger.records[0]["decision"] == "RESIDUAL_EXIT_DATA_UNAVAILABLE"
    _run(cand, _reject_result(vwap=0))
    assert ledger.records[1]["decision"] == "RESIDUAL_EXIT_DATA_UNAVAILABLE"


def test_data_unavailable_vwap_diverged_from_book(monkeypatch, tmp_path):
    ledger, _ = _patch_env(monkeypatch, tmp_path)
    monkeypatch.setattr(sc, "_get_executable_exit_cents", lambda s, side: 40)
    cand = _candidate(fair_value_cents=10)
    _run(cand, _reject_result(vwap=18))  # fresh bid 40 vs vwap 18: stale
    assert ledger.records[0]["decision"] == "RESIDUAL_EXIT_DATA_UNAVAILABLE"
    assert ledger.records[0]["basis"] == "vwap_stale_vs_fresh_book"


def test_data_unavailable_no_depth(monkeypatch, tmp_path):
    ledger, _ = _patch_env(monkeypatch, tmp_path)
    monkeypatch.setattr(sc, "_get_executable_exit_cents", lambda s, side: None)
    cand = _candidate(fair_value_cents=10)
    _run(cand, _reject_result())
    assert ledger.records[0]["decision"] == "RESIDUAL_EXIT_DATA_UNAVAILABLE"
    assert ledger.records[0]["basis"] == "no_executable_depth"


def test_hold_near_settlement_window(monkeypatch, tmp_path):
    ledger, _ = _patch_env(monkeypatch, tmp_path)
    cand = _candidate(fair_value_cents=10, seconds_to_expiry=30.0)
    _run(cand, _reject_result())
    assert ledger.records[0]["decision"] == "HOLD_TO_SETTLEMENT_APPROVED"
    assert ledger.records[0]["basis"] == "settlement_close_window"


def test_degraded_simulated_observe_only(monkeypatch, tmp_path):
    """Approved but env-gated off -> simulated decision, no order."""
    ledger, tracker = _patch_env(monkeypatch, tmp_path)
    monkeypatch.setattr(sc, "degraded_exit_enabled", lambda: False)
    cand = _candidate(fair_value_cents=10)  # 10 + 3 <= 18 -> exit justified
    _run(cand, _reject_result())
    rec = ledger.records[0]
    assert rec["decision"] == "DEGRADED_EXIT_APPROVED"
    assert rec["basis"] == "observe_only_submission_disabled"
    assert rec["degraded_limit_cents"] == 16  # min(18,18) - 2c residual slip
    assert rec["policy"]["code"] == "residual_exit_v1"
    res = next(iter(tracker._records.values()))
    assert res.status == ResidualStatus.DEGRADED_EXIT_SIMULATED.value


def test_degraded_submit_uses_fresh_dg_coid(monkeypatch, tmp_path):
    """The degraded IOC carries a fresh ``dg1`` coid — the primary coid was
    consumed by the venue even though it was rejected."""
    ledger, _ = _patch_env(monkeypatch, tmp_path)
    monkeypatch.setattr(sc, "degraded_exit_enabled", lambda: True)
    monkeypatch.setattr(sc, "_get_executable_exit_cents", lambda s, side: 17)

    captured = {}

    async def _fake_route(intent):
        captured["intent"] = intent
        return types.SimpleNamespace(
            status="filled", fill={"count": 3}, submission_certainty="ack_received"
        )

    from merid.event_venues.kalshi import order_router

    monkeypatch.setattr(order_router, "route_order_async", _fake_route)
    cand = _candidate(fair_value_cents=10)
    _run(cand, _reject_result())
    intent = captured["intent"]
    assert intent.client_order_id.endswith("dg1")
    assert intent.intent_id.endswith(":dg1")
    # limit = min(vwap=18, fresh_bid=17) - 2c residual slip
    assert intent.price_cents == 15
    assert intent.time_in_force == "ioc"
    assert intent.reduce_only is True
    assert intent.action == "sell" and intent.side == "no" and intent.count == 3
    assert intent.count_fp == 3 and intent.pre_position_fp == 300
    rec = ledger.records[0]
    assert rec["decision"] == "DEGRADED_EXIT_APPROVED"
    assert rec["basis"] == "degraded_ioc_submitted"


def test_residual_idempotency_blocks_second_attempt(monkeypatch, tmp_path):
    """A second monitor cycle on the same position epoch cannot emit a
    second degraded IOC — the attempt budget is durable."""
    ledger, tracker = _patch_env(monkeypatch, tmp_path)
    monkeypatch.setattr(sc, "degraded_exit_enabled", lambda: True)

    calls = []

    async def _fake_route(intent):
        calls.append(intent)
        return types.SimpleNamespace(status="rejected", reason="expired")

    from merid.event_venues.kalshi import order_router

    monkeypatch.setattr(order_router, "route_order_async", _fake_route)
    cand = _candidate(fair_value_cents=10)
    _run(cand, _reject_result())          # cycle 1: dg1 submitted
    _run(_candidate(fair_value_cents=10), _reject_result())  # cycle 2
    assert len(calls) == 1
    assert ledger.records[1]["decision"] == "RESIDUAL_RISK_BREACH"
    assert ledger.records[1]["basis"] == "degraded_attempt_budget_exhausted"
    res = next(iter(tracker._records.values()))
    assert res.degraded_attempt_number == 1
    assert len(res.degraded_client_order_ids) == 1


def test_new_position_epoch_gets_fresh_residual(monkeypatch, tmp_path):
    """A new entry after the old one closed is a new epoch -> independent
    workflow with its own attempt budget."""
    ledger, tracker = _patch_env(monkeypatch, tmp_path)
    monkeypatch.setattr(sc, "degraded_exit_enabled", lambda: True)

    async def _fake_route(intent):
        return types.SimpleNamespace(status="rejected", reason="expired")

    from merid.event_venues.kalshi import order_router

    monkeypatch.setattr(order_router, "route_order_async", _fake_route)
    cand = _candidate(fair_value_cents=10)
    _run(cand, _reject_result())   # epoch fill-ep-1
    monkeypatch.setattr(sc, "_resolve_position_epoch", lambda t: "fill-ep-2")
    _run(cand, _reject_result())   # epoch fill-ep-2 -> allowed again
    assert ledger.records[1]["decision"] == "DEGRADED_EXIT_APPROVED"
    assert len(tracker._records) == 2


def _route_returning(monkeypatch, result, calls=None):
    from merid.event_venues.kalshi import order_router

    async def _fake_route(intent):
        if calls is not None:
            calls.append(intent)
        return result

    monkeypatch.setattr(order_router, "route_order_async", _fake_route)


def test_full_fill_closes_residual(monkeypatch, tmp_path):
    ledger, tracker = _patch_env(monkeypatch, tmp_path)
    monkeypatch.setattr(sc, "degraded_exit_enabled", lambda: True)
    _route_returning(monkeypatch, types.SimpleNamespace(
        status="filled", fill={"count": 3}, submission_certainty="ack_received"))
    _run(_candidate(fair_value_cents=10), _reject_result())
    res = next(iter(tracker._records.values()))
    assert res.status == ResidualStatus.CLOSED.value
    assert res.remaining_quantity_cc == 0


def test_partial_fill_tracks_remaining_and_blocks_reattempt(monkeypatch, tmp_path):
    ledger, tracker = _patch_env(monkeypatch, tmp_path)
    monkeypatch.setattr(sc, "degraded_exit_enabled", lambda: True)
    calls = []
    _route_returning(monkeypatch, types.SimpleNamespace(
        status="partial", fill={"count": 1}, submission_certainty="ack_received"), calls)
    _run(_candidate(fair_value_cents=10), _reject_result())
    res = next(iter(tracker._records.values()))
    assert res.status == ResidualStatus.PARTIALLY_FILLED.value
    assert res.remaining_quantity_cc == 200
    assert res.venue_acknowledged_quantity == 100
    # Next cycle on the same epoch: budget spent -> explicit breach, no order.
    _run(_candidate(fair_value_cents=10), _reject_result())
    assert len(calls) == 1
    assert ledger.records[-1]["decision"] == "RESIDUAL_RISK_BREACH"


def test_ambiguous_ack_holds_lease_no_second_order(monkeypatch, tmp_path):
    """Delayed/ambiguous venue outcome: the system must not issue a second
    order on top of an unconfirmed one."""
    ledger, tracker = _patch_env(monkeypatch, tmp_path)
    monkeypatch.setattr(sc, "degraded_exit_enabled", lambda: True)
    calls = []
    _route_returning(monkeypatch, types.SimpleNamespace(
        status="unknown", fill=None, submission_certainty="in_flight"), calls)
    _run(_candidate(fair_value_cents=10), _reject_result())
    res = next(iter(tracker._records.values()))
    assert res.status == ResidualStatus.DEGRADED_EXIT_SUBMITTED.value
    assert ledger.records[0]["basis"] == "degraded_ioc_ambiguous_awaiting_reconciliation"
    _run(_candidate(fair_value_cents=10), _reject_result())
    assert len(calls) == 1
    assert ledger.records[1]["decision"] == "DEGRADED_EXIT_PENDING_RECONCILIATION"


def test_unfilled_ioc_is_risk_breach(monkeypatch, tmp_path):
    ledger, tracker = _patch_env(monkeypatch, tmp_path)
    monkeypatch.setattr(sc, "degraded_exit_enabled", lambda: True)
    _route_returning(monkeypatch, types.SimpleNamespace(
        status="unfilled_ioc", fill={"count": 0}, submission_certainty="ack_received"))
    _run(_candidate(fair_value_cents=10), _reject_result())
    res = next(iter(tracker._records.values()))
    assert res.status == ResidualStatus.RISK_BREACH.value
    assert ledger.records[0]["basis"].startswith("degraded_ioc_unfilled")


def test_settlement_crossed_before_submit(monkeypatch, tmp_path):
    """Remaining time crosses the close window between evaluation and
    submission -> hold under explicit policy, no order."""
    ledger, tracker = _patch_env(monkeypatch, tmp_path)
    monkeypatch.setattr(sc, "degraded_exit_enabled", lambda: True)
    calls = []
    _route_returning(monkeypatch, types.SimpleNamespace(status="filled", fill={"count": 3}), calls)
    real_get = tracker.get_or_create

    def _get_with_near_deadline(*a, **kw):
        rec = real_get(*a, **kw)
        rec.settlement_deadline = sc.time.time() + 5  # inside close buffer
        return rec

    monkeypatch.setattr(tracker, "get_or_create", _get_with_near_deadline)
    _run(_candidate(fair_value_cents=10, seconds_to_expiry=400.0), _reject_result())
    assert calls == []
    assert ledger.records[0]["basis"] == "settlement_close_window_at_submit"


def test_flag_off_never_routes(monkeypatch, tmp_path):
    ledger, _ = _patch_env(monkeypatch, tmp_path)
    monkeypatch.setattr(sc, "degraded_exit_enabled", lambda: False)
    calls = []
    _route_returning(monkeypatch, types.SimpleNamespace(status="filled", fill={"count": 3}), calls)
    _run(_candidate(fair_value_cents=10), _reject_result())
    assert calls == []
    assert ledger.records[0]["basis"] == "observe_only_submission_disabled"


def test_restart_recovery_preserves_claim(tmp_path):
    """A claim persisted before routing survives a crash/restart: the
    reloaded tracker refuses a second degraded attempt."""
    path = tmp_path / "residuals.json"
    t1 = ResidualExitTracker(path)
    rec = t1.get_or_create("KXT", "no", "ep1", trigger_id="c1",
                           trigger_reason="HARD_STOP", quantity_cc=300)
    ok, _, coid = t1.claim_degraded_attempt(rec, client_order_id_prefix="stopcand_c1",
                                            limit_cents=16)
    assert ok and coid == "stopcand_c1dg1"
    t2 = ResidualExitTracker(path)  # simulated restart
    rec2 = t2.get_or_create("KXT", "no", "ep1", trigger_id="c2",
                            trigger_reason="HARD_STOP", quantity_cc=300)
    assert rec2.degraded_attempt_number == 1
    ok2, reason, _ = t2.claim_degraded_attempt(rec2, client_order_id_prefix="stopcand_c2",
                                               limit_cents=16)
    assert not ok2
    assert reason == "degraded_already_submitted"


def test_close_for_ticker_on_flat(tmp_path):
    t = ResidualExitTracker(tmp_path / "r.json")
    t.get_or_create("KXA", "no", "ep1", trigger_id="c", trigger_reason="HARD_STOP", quantity_cc=100)
    t.get_or_create("KXB", "yes", "ep2", trigger_id="d", trigger_reason="HARD_STOP", quantity_cc=100)
    assert t.close_for_ticker("KXA") == 1
    assert [r.ticker for r in t.open_records()] == ["KXB"]


def test_normalize_never_expands_loss_envelope():
    """Tick normalization is a one-way ratchet: for a reduce-only sell the
    limit is a minimum acceptable price, so sub-cent residue must round up
    (tighter), never down past the computed bound."""
    assert sc._normalize_venue_limit(15.4, "no") == 16
    assert sc._normalize_venue_limit(15.4, "yes") == 16
    assert sc._normalize_venue_limit(15.0, "no") == 15
    assert sc._normalize_venue_limit(0.2, "no") == 1      # venue floor
    assert sc._normalize_venue_limit(99.6, "no") == 99    # venue ceiling
    for raw in (1.0, 5.5, 22.3, 50.0, 80.9, 98.99):
        for side in ("yes", "no"):
            assert sc._normalize_venue_limit(raw, side) >= int(raw)


def test_no_branch_on_other_rejections(monkeypatch, tmp_path):
    """Non-executable is the only residual trigger; other rejects stay
    terminal so their different recovery semantics are not conflated."""
    ledger, tracker = _patch_env(monkeypatch, tmp_path)
    cand = _candidate(fair_value_cents=10)
    other = types.SimpleNamespace(
        status="rejected", reason="firewall:firewall_rejected:stale_book"
    )
    _run(cand, other)
    assert ledger.records == []
    assert tracker._records == {}
