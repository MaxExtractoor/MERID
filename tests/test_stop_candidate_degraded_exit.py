"""Residual-exposure branch for non-executable protective exits.

2026-10-04: when the execution firewall rejects a stop IOC with
``limit_not_executable``, the position must end in an explicit durable
state — degraded exit (bounded IOC at the real depth VWAP) or recorded
hold-to-settlement — never a silent carry to expiry.
"""

import asyncio
import types

import merid.event_venues.kalshi.stop_candidate as sc


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
    return types.SimpleNamespace(
        status="rejected",
        reason=(
            "firewall:firewall_rejected:limit_not_executable:"
            f"limit={limit}:vwap={vwap}"
        ),
        price_cents=limit,
    )


class _FakeLedger:
    def __init__(self):
        self.records = []

    def record_residual_decision(self, candidate, record):
        self.records.append(record)


def _patch_ledger(monkeypatch):
    ledger = _FakeLedger()
    monkeypatch.setattr(sc, "get_stop_candidate_ledger", lambda: ledger)
    return ledger


def test_parse_non_executable_vwap():
    assert sc.parse_non_executable_vwap_cents(
        "firewall:firewall_rejected:limit_not_executable:limit=22:vwap=18"
    ) == 18
    assert sc.parse_non_executable_vwap_cents(
        "firewall:firewall_rejected:insufficient_depth:depth=0"
    ) is None
    assert sc.parse_non_executable_vwap_cents("stop_candidate_edge_not_breached") is None
    assert sc.parse_non_executable_vwap_cents(None) is None


def test_hold_to_settlement_when_fair_above_degraded(monkeypatch):
    """Fair value still above the degraded exit proceeds -> explicit hold."""
    ledger = _patch_ledger(monkeypatch)
    cand = _candidate(fair_value_cents=25)  # 25 + costs(2) + hyst(1) > vwap 18
    asyncio.run(
        sc._maybe_degraded_stop_exit(
            cand, _reject_result(), held_side="no", held_contracts=3
        )
    )
    assert len(ledger.records) == 1
    rec = ledger.records[0]
    assert rec["decision"] == "HOLD_TO_SETTLEMENT_APPROVED"
    assert rec["basis"] == "fair_above_degraded_exit_value"
    assert rec["degraded_vwap_cents"] == 18


def test_residual_risk_breach_without_fair_value(monkeypatch):
    """Price-triggered stops with no model basis must escalate, not hold."""
    ledger = _patch_ledger(monkeypatch)
    cand = _candidate(fair_value_cents=None)
    asyncio.run(
        sc._maybe_degraded_stop_exit(
            cand, _reject_result(), held_side="no", held_contracts=3
        )
    )
    assert ledger.records[0]["decision"] == "RESIDUAL_RISK_BREACH"
    assert ledger.records[0]["basis"] == "no_fair_value"


def test_degraded_approved_observe_only(monkeypatch):
    """Approved but env-gated off -> recorded decision, no order."""
    ledger = _patch_ledger(monkeypatch)
    monkeypatch.setattr(sc, "degraded_exit_enabled", lambda: False)
    monkeypatch.setattr(sc, "_get_market_state", lambda t: (None, None))
    monkeypatch.setattr(sc, "_get_executable_exit_cents", lambda s, side: 18)
    cand = _candidate(fair_value_cents=10)  # 10 + 3 <= 18 -> exit justified
    asyncio.run(
        sc._maybe_degraded_stop_exit(
            cand, _reject_result(), held_side="no", held_contracts=3
        )
    )
    rec = ledger.records[0]
    assert rec["decision"] == "DEGRADED_EXIT_APPROVED"
    assert rec["basis"] == "observe_only_submission_disabled"
    assert rec["degraded_limit_cents"] == 16  # min(18,18) - 2c residual slip


def test_degraded_breach_when_depth_gone(monkeypatch):
    ledger = _patch_ledger(monkeypatch)
    monkeypatch.setattr(sc, "degraded_exit_enabled", lambda: True)
    monkeypatch.setattr(sc, "_get_market_state", lambda t: (None, None))
    monkeypatch.setattr(sc, "_get_executable_exit_cents", lambda s, side: None)
    cand = _candidate(fair_value_cents=10)
    asyncio.run(
        sc._maybe_degraded_stop_exit(
            cand, _reject_result(), held_side="no", held_contracts=3
        )
    )
    rec = ledger.records[0]
    assert rec["decision"] == "RESIDUAL_RISK_BREACH"
    assert rec["basis"] == "no_executable_depth"


def test_degraded_submit_uses_fresh_dg_coid(monkeypatch):
    """The degraded IOC must carry a fresh ``dg1`` client order id — the
    primary coid was consumed by the venue even though it was rejected."""
    ledger = _patch_ledger(monkeypatch)
    monkeypatch.setattr(sc, "degraded_exit_enabled", lambda: True)
    monkeypatch.setattr(sc, "_get_market_state", lambda t: (None, None))
    monkeypatch.setattr(sc, "_get_executable_exit_cents", lambda s, side: 17)

    captured = {}

    async def _fake_route(intent):
        captured["intent"] = intent
        return types.SimpleNamespace(status="filled", avg_fill_price_cents=17)

    from merid.event_venues.kalshi import order_router

    monkeypatch.setattr(order_router, "route_order_async", _fake_route)
    cand = _candidate(fair_value_cents=10)
    asyncio.run(
        sc._maybe_degraded_stop_exit(
            cand, _reject_result(), held_side="no", held_contracts=3
        )
    )
    intent = captured["intent"]
    assert intent.client_order_id.endswith("dg1")
    assert intent.intent_id.endswith(":dg1")
    # limit = min(vwap=18, fresh_bid=17) - 2c residual slip
    assert intent.price_cents == 15
    assert intent.time_in_force == "ioc"
    assert intent.reduce_only is True
    assert intent.action == "sell"
    assert intent.side == "no"
    assert intent.count == 3
    rec = ledger.records[0]
    assert rec["decision"] == "DEGRADED_EXIT_APPROVED"
    assert rec["basis"] == "degraded_ioc_submitted"
    assert rec["result"]["status"] == "filled"


def test_no_branch_on_other_rejections(monkeypatch):
    """Non-executable is the only residual trigger; other rejects stay
    terminal so their (different) recovery semantics are not conflated."""
    ledger = _patch_ledger(monkeypatch)
    cand = _candidate(fair_value_cents=10)
    other = types.SimpleNamespace(
        status="rejected", reason="firewall:firewall_rejected:stale_book"
    )
    asyncio.run(
        sc._maybe_degraded_stop_exit(
            cand, other, held_side="no", held_contracts=3
        )
    )
    assert ledger.records == []
