"""Fractional-exposure lifecycle regression tests (2026-10-08 audit).

Venue fills carry exact fixed-point quantities (``count_fp`` / centi-contract
``quantity_cc``).  Prior to this fix the stop-candidate path rejected any
position whose quantity was not a whole number of contracts
(``stop_candidate_fractional_qty``), and the live-order reconcile path floored
``Decimal`` filled sizes with ``int()`` — ``int(0.75) == 0`` — so a real
partial fill looked like an unfilled IOC.  These tests pin the exact-quantity
behavior at 0.01 / 0.75 / 1.55 / 3.00 granularity end to end.
"""

import asyncio
import types
from decimal import Decimal

import pytest

import merid.event_venues.kalshi.stop_candidate as sc
from merid.event_venues.kalshi.residual_exit import (
    ResidualExitTracker,
    ResidualStatus,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _candidate(position_cc, **kw):
    args = dict(
        market_ticker="KXSOL15M-TEST",
        trigger_reason="HARD_STOP",          # operational: no EV-gate consult
        position_from_exchange_cc=position_cc,
        candidate_id="sc-frac-test",
        seconds_to_expiry=400.0,
        consecutive_edge_below=3,            # >= STOP_EDGE_MIN_CONSECUTIVE
        fair_value_cents=10,
        executable_exit_cents=18,
        total_exit_cost_cents=2,
        hysteresis_cents=1,
        quote_age_ms=250,
    )
    args.update(kw)
    return sc.StopCandidate(**args)


class _FakeLedger:
    def __init__(self):
        self.candidates = []
        self.submissions = []
        self.residuals = []

    def record_stop_candidate(self, candidate):
        self.candidates.append(candidate)

    def record_submission(self, candidate, result, **kw):
        self.submissions.append((candidate, result))

    def record_residual_decision(self, candidate, record):
        self.residuals.append(record)


def _patch_submit_env(monkeypatch, tmp_path, position_cc):
    """Patch every external dependency of maybe_submit_stop_candidate."""
    ledger = _FakeLedger()
    tracker = ResidualExitTracker(tmp_path / "residuals.json")

    monkeypatch.setattr(sc, "get_stop_candidate_ledger", lambda: ledger)
    monkeypatch.setattr(sc, "record_stop_candidate", lambda c: ledger.candidates.append(c))
    monkeypatch.setattr(
        "merid.event_venues.kalshi.residual_exit.get_residual_exit_tracker",
        lambda path=None: tracker,
    )
    monkeypatch.setattr(sc, "_resolve_position_epoch", lambda t: "fill-ep-1")
    monkeypatch.setattr(sc, "_get_market_state", lambda t: (None, None))
    monkeypatch.setattr(sc, "_get_executable_exit_cents", lambda s, side: 18)

    async def _fake_exposure(ticker, timeout=1.0, fallback_to_cache=True):
        side = "yes" if position_cc > 0 else "no"
        return position_cc, 40, side

    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_intent_contract.fetch_fresh_signed_yes_exposure",
        _fake_exposure,
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.position_cache.get_position_cache",
        lambda: None,
    )
    return ledger, tracker


def _submit(cand, monkeypatch):
    calls = []

    async def _fake_route(intent):
        calls.append(intent)
        return types.SimpleNamespace(
            status="filled",
            fill={"count_fp": str(intent.count_fp), "quantity_cc": int(intent.count_fp * 100)},
            submission_certainty="ack_received",
        )

    from merid.event_venues.kalshi import order_router

    monkeypatch.setattr(order_router, "route_order_async", _fake_route)
    result = asyncio.run(sc.maybe_submit_stop_candidate(cand))
    return result, calls


# ── primary stop path: fractional quantities must submit ─────────────────────

@pytest.mark.parametrize("position_cc,expected_fp", [
    (-1,   Decimal("0.01")),   # smallest representable position
    (-75,  Decimal("0.75")),   # sub-one-contract
    (-155, Decimal("1.55")),   # fractional > 1
    (-300, Decimal("3.00")),   # whole contracts still work
])
def test_stop_candidate_fractional_position_submits_exact_qty(
    monkeypatch, tmp_path, position_cc, expected_fp
):
    """Every centi-contract of actual exposure is closeable — no % 100 gate."""
    _patch_submit_env(monkeypatch, tmp_path, position_cc)
    cand = _candidate(position_cc)
    result, calls = _submit(cand, monkeypatch)
    assert len(calls) == 1, f"expected submission, got {result!r}"
    intent = calls[0]
    assert intent.count_fp == expected_fp
    assert intent.count == float(expected_fp)
    assert intent.pre_position_fp == abs(position_cc)
    assert intent.expected_post_position_fp == 0
    assert intent.reduce_only is True and intent.time_in_force == "ioc"


def test_stop_candidate_sub_one_contract_still_exit_eligible(
    monkeypatch, tmp_path
):
    """A 0.75-contract position is real exposure, not dust — it must not be
    suppressed by an integer-contract floor."""
    _patch_submit_env(monkeypatch, tmp_path, -75)
    result, calls = _submit(_candidate(-75), monkeypatch)
    assert calls and calls[0].count_fp == Decimal("0.75")


def test_stop_candidate_clamps_to_actual_position(monkeypatch, tmp_path):
    """Candidate may never close more than the exchange-visible position."""
    _patch_submit_env(monkeypatch, tmp_path, -75)
    cand = _candidate(-75)
    result, calls = _submit(cand, monkeypatch)
    assert len(calls) == 1
    assert calls[0].count_fp == Decimal("0.75")


def test_stop_candidate_zero_qty_still_rejected(monkeypatch, tmp_path):
    _patch_submit_env(monkeypatch, tmp_path, -75)
    cand = _candidate(0)
    result, calls = _submit(cand, monkeypatch)
    assert calls == []
    assert getattr(result, "status", "") == "rejected"


# ── degraded residual path: exact fractional tracking ────────────────────────

def _degraded_run(cand, result, held_qty_cc, **kw):
    return asyncio.run(
        sc._maybe_degraded_stop_exit(
            cand, result, held_side="no", held_qty_cc=held_qty_cc, **kw
        )
    )


def _patch_degraded_env(monkeypatch, tmp_path):
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
    monkeypatch.setattr(sc, "degraded_exit_enabled", lambda: True)
    return ledger, tracker


def _reject():
    return types.SimpleNamespace(
        status="rejected",
        reason="firewall:firewall_rejected:limit_not_executable:limit=22:vwap=18",
        price_cents=22,
    )


def test_degraded_fractional_position_records_exact_qty(monkeypatch, tmp_path):
    """Residual tracker quantity is centi-contracts, not floored contracts."""
    ledger, tracker = _patch_degraded_env(monkeypatch, tmp_path)
    calls = []

    async def _fake_route(intent):
        calls.append(intent)
        return types.SimpleNamespace(
            status="filled",
            fill={"count_fp": "0.75", "quantity_cc": 75},
            submission_certainty="ack_received",
        )

    from merid.event_venues.kalshi import order_router
    monkeypatch.setattr(order_router, "route_order_async", _fake_route)

    _degraded_run(_candidate(-75, fair_value_cents=10), _reject(), held_qty_cc=75)
    res = next(iter(tracker._records.values()))
    assert res.original_quantity_cc == 75
    assert res.venue_acknowledged_quantity == 75
    assert calls and calls[0].count_fp == Decimal("0.75")
    assert calls[0].pre_position_fp == 75
    assert calls[0].expected_post_position_fp == 0
    assert res.status == ResidualStatus.CLOSED.value
    assert res.remaining_quantity_cc == 0


def test_degraded_partial_fractional_fill_leaves_exact_balance(
    monkeypatch, tmp_path
):
    """A 0.20 fill against 0.75 exposure leaves exactly 0.55 tracked."""
    ledger, tracker = _patch_degraded_env(monkeypatch, tmp_path)

    async def _fake_route(intent):
        return types.SimpleNamespace(
            status="partial",
            fill={"count_fp": "0.20", "quantity_cc": 20},
            submission_certainty="ack_received",
        )

    from merid.event_venues.kalshi import order_router
    monkeypatch.setattr(order_router, "route_order_async", _fake_route)

    _degraded_run(_candidate(-75, fair_value_cents=10), _reject(), held_qty_cc=75)
    res = next(iter(tracker._records.values()))
    assert res.status == ResidualStatus.PARTIALLY_FILLED.value
    assert res.remaining_quantity_cc == 55
    assert res.venue_acknowledged_quantity == 20


def test_degraded_sub_contract_fill_not_erased(monkeypatch, tmp_path):
    """fill=0.75 via count_fp must be seen as execution — not int()-floor to 0
    and misclassified as an unfilled IOC risk breach."""
    ledger, tracker = _patch_degraded_env(monkeypatch, tmp_path)

    async def _fake_route(intent):
        return types.SimpleNamespace(
            status="filled",
            fill={"count_fp": "0.75"},
            submission_certainty="ack_received",
        )

    from merid.event_venues.kalshi import order_router
    monkeypatch.setattr(order_router, "route_order_async", _fake_route)

    _degraded_run(_candidate(-75, fair_value_cents=10), _reject(), held_qty_cc=75)
    res = next(iter(tracker._records.values()))
    assert res.status == ResidualStatus.CLOSED.value
    assert res.venue_acknowledged_quantity == 75
    assert ledger.residuals[0]["filled_qty_cc"] == 75


# ── live-order reconcile: Decimal sizes must not be int()-floored ─────────────

def _reconciled_result(filled, remaining=None, size="1.00"):
    from merid.event_venues.kalshi import order_router
    from merid.event_venues.kalshi.order_router import OrderIntent, TradingMode

    order = types.SimpleNamespace(
        order_id="oid-1",
        client_order_id="coid-1",
        status="filled" if Decimal(str(remaining or 0)) == 0 else "resting",
        size=Decimal(str(size)),
        filled_size=Decimal(str(filled)),
        remaining_size=(
            Decimal(str(remaining)) if remaining is not None else None
        ),
        price_cents=20,
        outcome="no",
        side="sell",
    )
    intent = OrderIntent(
        ticker="KXSOL15M-TEST", price_cents=20, count=1.0,
        side="no", action="sell", reduce_only=True, entry_or_exit="exit",
    )
    return order_router._order_snapshot_to_reconciled_result(
        order, intent, TradingMode.LIVE, 12.0
    )


def test_reconciled_result_preserves_fractional_fill():
    res = _reconciled_result(filled="0.75", remaining="0.25")
    assert res.executed_quantity_cc == 75
    assert res.remaining_quantity_cc == 25
    assert res.has_execution is True
    assert res.fill["quantity_cc"] == 75
    assert res.fill["count_fp"] == "0.75"


def test_reconciled_result_fractional_over_one_contract():
    res = _reconciled_result(filled="1.55", remaining="0.45", size="2.00")
    assert res.executed_quantity_cc == 155
    assert res.remaining_quantity_cc == 45
    assert res.fill["count"] == 1          # display floor only
    assert res.fill["quantity_cc"] == 155  # exact


def test_reconciled_result_zero_fill_unchanged():
    res = _reconciled_result(filled="0", remaining="1.00")
    assert res.executed_quantity_cc == 0
    assert res.has_execution is False


# ── fee floor with fractional sizes ──────────────────────────────────────────

def test_net_profit_floor_scales_with_fractional_size():
    """Net-liquidation check must use the exact fractional quantity."""
    from merid.event_venues.kalshi.fees import is_exit_net_profitable

    ok_whole, net_whole = is_exit_net_profitable(50, 60, Decimal("1.00"))
    ok_frac, net_frac = is_exit_net_profitable(50, 60, Decimal("0.50"))
    # Half the quantity: ~half the gross, proportionally smaller fees.
    assert net_frac > 0 and net_whole > 0
    assert abs(net_frac * 2 - net_whole) < Decimal("0.05")

    # A 0.75 size must not be treated as zero or rounded to one.
    ok_075, net_075 = is_exit_net_profitable(50, 55, Decimal("0.75"))
    _, net_100 = is_exit_net_profitable(50, 55, Decimal("1.00"))
    assert Decimal("0") < net_075 < net_100


def test_qty_cc_helper_preserves_fraction():
    from merid.event_venues.kalshi.fees import _quantity_cc_for_size

    assert _quantity_cc_for_size("0.01") == Decimal("1")
    assert _quantity_cc_for_size("0.75") == Decimal("75")
    assert _quantity_cc_for_size(Decimal("1.55")) == Decimal("155")
    assert _quantity_cc_for_size(3) == Decimal("300")
