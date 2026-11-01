"""P0 must not forget old uncertain submissions on restart."""

import time
import sqlite3
from types import SimpleNamespace

import pytest

from merid.event_venues.kalshi import order_attempt_store as attempts
from merid.preflight.p0 import (
    _check_uncertain_submissions,
    _complete_snapshot,
    _open_order_snapshot,
    _position_snapshot,
    _rti_observations_fresh,
    _signed_yes_position_map,
    _trusted_ledger_signed_exposure,
    run_p0_preflight_checks,
)
from merid.resilience.result import OperationResult


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(attempts, "DEFAULT_DB_PATH", str(tmp_path / "attempts.db"))
    monkeypatch.setattr(attempts.OrderAttemptStore, "_instances", {})
    return attempts.OrderAttemptStore()


def test_empty_store_passes(store):
    assert _check_uncertain_submissions()[0]


@pytest.mark.parametrize("status", ["SUBMITTING", "SUBMISSION_UNKNOWN"])
def test_old_uncertain_attempt_fails_and_is_not_modified(store, status):
    old = time.time() - 400 * 86400
    store.persist_attempt(attempts.OrderAttemptRecord(
        order_attempt_id="oa-1", client_order_id="co-1", decision_id="dec-1",
        replaces_order_attempt_id=None, intent_id="intent-1", client_tag=None,
        run_id=None, process_id=None, fingerprint="fp-1", status=status,
        created_at=old, updated_at=old, payload_json="{}",
    ))
    assert not _check_uncertain_submissions()[0]
    assert store.get_by_order_attempt_id("oa-1").status == status
    assert store.get_unresolved() == []


def test_missing_store_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(attempts, "DEFAULT_DB_PATH", str(tmp_path / "missing.db"))
    assert not _check_uncertain_submissions()[0]
    assert not (tmp_path / "missing.db").exists()


def test_missing_exit_table_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "incomplete.db"
    monkeypatch.setattr(attempts, "DEFAULT_DB_PATH", str(path))
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE order_attempts (status TEXT)")
    assert not _check_uncertain_submissions()[0]


def test_uncertain_exit_attempt_fails(store):
    rec = store.create_exit_attempt(
        exit_intent_id="exit-1", position_key="pos-1",
        ticker="KXBTC15M-TEST", reason="test",
        client_order_id="exit-co-1", requested_quantity=100,
    )
    store.transition_exit_attempt(rec.attempt_id, "SUBMITTING", actor="test", reason="test")
    assert not _check_uncertain_submissions()[0]


@pytest.mark.asyncio
async def test_p0_stops_before_balance_or_funding(monkeypatch):
    monkeypatch.setattr(
        "merid.preflight.p0._check_uncertain_submissions",
        lambda: (False, "uncertain submissions"),
    )
    result = await run_p0_preflight_checks(
        client=SimpleNamespace(), bankroll=None, catalog=None,
    )
    assert result[-1] == (False, "uncertain submissions")


@pytest.mark.parametrize("result", [
    OperationResult.fail(RuntimeError("offline")),
    OperationResult(success=True, data=[], metadata={"truncated": True}),
    OperationResult.ok(None),
])
def test_incomplete_snapshots_are_not_empty_success(result):
    with pytest.raises(RuntimeError):
        _complete_snapshot(result, "fills")


@pytest.mark.asyncio
@pytest.mark.parametrize("snapshot_name,result_name,fallback_name", [
    (_position_snapshot, "get_positions_result", "get_positions"),
    (_open_order_snapshot, "get_open_orders_result", "get_open_orders"),
])
async def test_p0_uses_explicit_failed_result_not_silent_empty(
    snapshot_name, result_name, fallback_name,
):
    from unittest.mock import AsyncMock

    client = SimpleNamespace(**{
        result_name: AsyncMock(return_value=OperationResult.fail(RuntimeError("offline"))),
        fallback_name: AsyncMock(return_value=[]),
    })
    with pytest.raises(RuntimeError, match="incomplete"):
        await snapshot_name(client)
    getattr(client, fallback_name).assert_not_awaited()


def test_rti_requires_all_assets_and_valid_current_timestamps():
    now = 1793491200000
    good = SimpleNamespace(execution_eligible=True, observed_ts_ms=now - 10)
    missing_time = SimpleNamespace(execution_eligible=True, observed_ts_ms=0)
    future = SimpleNamespace(execution_eligible=True, observed_ts_ms=now + 1)
    stale = SimpleNamespace(execution_eligible=True, observed_ts_ms=now - 2001)
    assert _rti_observations_fresh({"BTC": good, "ETH": good}, ["BTC", "ETH"], 2000, now)[0]
    assert not _rti_observations_fresh({"BTC": good}, ["BTC", "ETH"], 2000, now)[0]
    for obs in (missing_time, future, stale):
        assert not _rti_observations_fresh({"BTC": obs}, ["BTC"], 2000, now)[0]


def test_position_projection_preserves_ticker_side_and_fractional_quantity():
    positions = [
        SimpleNamespace(market_id="BTC", outcome_id="yes", size="1.23"),
        SimpleNamespace(market_id="SOL", outcome_id="no", size="0.37"),
    ]
    assert _signed_yes_position_map(positions, exchange=True) == {"BTC": 123, "SOL": -37}
    cache = [
        {"market_id": "BTC", "side": "yes", "quantity_cc": 123},
        {"market_id": "SOL", "side": "no", "quantity_cc": 37},
    ]
    assert _signed_yes_position_map(cache, exchange=False) == {"BTC": 123, "SOL": -37}


@pytest.mark.parametrize("position,exchange", [
    (SimpleNamespace(market_id="BTC", outcome_id="unknown", size="1"), True),
    (SimpleNamespace(market_id="BTC", outcome_id="yes", size="0.001"), True),
    (SimpleNamespace(market_id="BTC", outcome_id="yes", size="-1"), True),
    (SimpleNamespace(market_id="BTC", outcome_id="yes", size=None), True),
    ({"market_id": "BTC", "side": "yes", "quantity_cc": 0, "contracts": 1}, False),
])
def test_invalid_position_projection_fails_closed(position, exchange):
    with pytest.raises((ValueError, ArithmeticError)):
        _signed_yes_position_map([position], exchange=exchange)


def _trusted_fill(**changes):
    values = {
        "market_ticker": "BTC",
        "canonicalization_state": "TRUSTED_LIVE_V1",
        "is_live": True,
        "fill_id": "fill-1",
        "order_id": "order-1",
        "client_order_id": "client-1",
        "quantity_cc": 123,
        "canonical_yes_delta_cc": 123,
        "canonical_position_action": "buy",
        "canonical_position_side": "yes",
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _canonical_view(*, authoritative=(), provisional=(), excluded=()):
    return SimpleNamespace(
        authoritative=list(authoritative),
        provisional=list(provisional),
        excluded=list(excluded),
    )


def test_ledger_replay_uses_exact_trusted_signed_deltas(monkeypatch):
    monkeypatch.setattr("merid.preflight.p0._reconciliation_quarantined", lambda ticker: False)
    fills = [
        _trusted_fill(),
        _trusted_fill(fill_id="fill-2", quantity_cc=23, canonical_yes_delta_cc=-23,
                      canonical_position_action="sell"),
        _trusted_fill(fill_id="fill-3", market_ticker="SOL", quantity_cc=37,
                      canonical_yes_delta_cc=-37, canonical_position_side="no"),
    ]
    assert _trusted_ledger_signed_exposure(_canonical_view(authoritative=fills)) == {
        "BTC": 100, "SOL": -37,
    }


@pytest.mark.parametrize("changes", [
    {"canonicalization_state": "UNTRUSTED_RAW"},
    {"unmatched": True},
    {"derived_id": True},
    {"side_conflict": True},
    {"order_id": None},
    {"client_order_id": None, "intent_id": None},
    {"quantity_cc": 0},
    {"canonical_yes_delta_cc": -123},
    {"is_live": False},
])
def test_ledger_replay_rejects_incomplete_or_untrusted_live_fill(monkeypatch, changes):
    monkeypatch.setattr("merid.preflight.p0._reconciliation_quarantined", lambda ticker: False)
    with pytest.raises(ValueError):
        _trusted_ledger_signed_exposure(
            _canonical_view(authoritative=[_trusted_fill(**changes)])
        )


def test_ledger_replay_preserves_quarantine_and_rejects_provisional(monkeypatch):
    monkeypatch.setattr(
        "merid.preflight.p0._reconciliation_quarantined",
        lambda ticker: ticker == "CLOSED",
    )
    expired = _trusted_fill(market_ticker="CLOSED", canonicalization_state="UNTRUSTED_RAW")
    assert _trusted_ledger_signed_exposure(_canonical_view(authoritative=[expired])) == {}
    with pytest.raises(ValueError, match="provisional"):
        _trusted_ledger_signed_exposure(_canonical_view(provisional=[_trusted_fill()]))
    with pytest.raises(ValueError, match="duplicate"):
        _trusted_ledger_signed_exposure(_canonical_view(excluded=[_trusted_fill()]))
    router_duplicate = _trusted_fill(fill_id="live_router_order")
    assert _trusted_ledger_signed_exposure(_canonical_view(excluded=[router_duplicate])) == {}
